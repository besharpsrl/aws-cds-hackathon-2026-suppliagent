import * as path from 'node:path';
import { CfnOutput, CfnResource, Stack, Validations, type StackProps } from 'aws-cdk-lib';
import * as agentcore from 'aws-cdk-lib/aws-bedrockagentcore';
import type * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import type * as events from 'aws-cdk-lib/aws-events';
import * as iam from 'aws-cdk-lib/aws-iam';
import type { IKey } from 'aws-cdk-lib/aws-kms';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import { Construct } from 'constructs';
import type { EnvConfig } from '../../config/environments.js';
import { PythonLambda } from '../constructs/python-lambda.js';
import { REPO_ROOT, uvBundling } from '../constructs/uv-bundling.js';
import type { TableName } from './data-stack.js';
import { CUSTOMERS_TOOLS } from './tool-schemas.js';

export interface AgentStackProps extends StackProps {
  readonly config: EnvConfig;
  readonly key: IKey;
  readonly tables: Readonly<Record<TableName, dynamodb.TableV2>>;
  readonly eventBus: events.IEventBus;
}

// Provided by the Lambda runtime and the Powertools layer: not bundled.
const LAMBDA_PLATFORM_PACKAGES = ['boto3', 'botocore', 's3transfer', 'aws-lambda-powertools'];

/**
 * Agent runtime (T-40, reduced): Gateway (MCP, IAM inbound auth) with the `customers` tool target
 * and an AgentCore Runtime running the Strands agent from a zip (no container). Memory, Guardrail,
 * the other tool targets and observability extras: T-54.
 */
export class AgentStack extends Stack {
  readonly runtime: agentcore.Runtime;

  constructor(scope: Construct, id: string, props: AgentStackProps) {
    super(scope, id, props);
    const { config, key, tables, eventBus } = props;
    const prefix = `suppliagent-${config.envName}`;

    const customersTool = new PythonLambda(this, 'CustomersTool', {
      config,
      key,
      name: 'tool-customers',
      code: lambda.Code.fromAsset(
        path.join(REPO_ROOT, 'services/tools/customers'),
        uvBundling({
          package: 'suppliagent-tool-customers',
          sources: {
            'services/shared/src/suppliagent_shared': 'suppliagent_shared',
            'services/tools/customers/src/suppliagent_tool_customers': 'suppliagent_tool_customers',
          },
          omit: LAMBDA_PLATFORM_PACKAGES,
        }),
      ),
      handler: 'suppliagent_tool_customers.handler.lambda_handler',
      environment: {
        TABLE_PREFIX: `${prefix}-`,
        EVENT_BUS_NAME: eventBus.eventBusName,
        IDENTIFICATION_MAX_ATTEMPTS: config.parameters.identificationMaxAttempts,
      },
    }).function;
    // Least privilege (INFRASTRUCTURE_DESIGN §5.3.2): exactly the calls the tool makes; no table
    // grant helpers, which add every index (`index/*`) and KMS wildcards.
    const allow = (actions: string[], ...resources: string[]) =>
      customersTool.addToRolePolicy(new iam.PolicyStatement({ actions, resources }));
    const customers = tables.Customers.tableArn;
    allow(
      ['dynamodb:GetItem', 'dynamodb:Scan', 'dynamodb:Query'],
      customers,
      `${customers}/index/by-repId`,
    );
    allow(
      ['dynamodb:GetItem', 'dynamodb:PutItem', 'dynamodb:DeleteItem'],
      tables.Contacts.tableArn,
    );
    allow(['dynamodb:PutItem'], tables.ChannelIdentities.tableArn);
    allow(['dynamodb:Query'], tables.OrderHistory.tableArn);
    allow(['dynamodb:GetItem'], tables.CustomerInsights.tableArn);
    allow(['dynamodb:UpdateItem'], tables.Conversations.tableArn);
    key.grant(customersTool, 'kms:Decrypt', 'kms:Encrypt', 'kms:GenerateDataKey');
    eventBus.grantPutEventsTo(customersTool);

    const gateway = new agentcore.Gateway(this, 'Gateway', {
      gatewayName: `${prefix}-gateway`,
      description: 'SuppliAgent tools (MCP); invoked only by the agent runtime (SigV4).',
      authorizerConfiguration: agentcore.GatewayAuthorizer.usingAwsIam(),
      // No searchType: the semantic search tool would be one more tool exposed to the model.
      protocolConfiguration: agentcore.GatewayProtocol.mcp({
        supportedVersions: [
          agentcore.MCPProtocolVersion.MCP_2025_06_18,
          agentcore.MCPProtocolVersion.MCP_2025_03_26,
        ],
      }),
      kmsKey: key,
    });
    gateway.addLambdaTarget('CustomersTarget', {
      gatewayTargetName: 'customers',
      description: 'Contact identification and customer profile (T-42).',
      lambdaFunction: customersTool,
      toolSchema: agentcore.ToolSchema.fromInline(CUSTOMERS_TOOLS),
    });
    const gatewayUrl = gateway.gatewayUrl;
    if (!gatewayUrl) throw new Error('Gateway L2 returned no gatewayUrl');

    this.runtime = new agentcore.Runtime(this, 'Runtime', {
      runtimeName: `suppliagent_${config.envName}_agent`,
      description: 'SuppliAgent Strands agent (T-41).',
      agentRuntimeArtifact: agentcore.AgentRuntimeArtifact.fromCodeAsset({
        path: path.join(REPO_ROOT, 'agent'),
        runtime: agentcore.AgentCoreRuntime.PYTHON_3_12,
        entrypoint: ['main.py'],
        ...uvBundling({
          package: 'suppliagent-agent',
          sources: {
            'agent/main.py': 'main.py',
            'agent/src/suppliagent_agent': 'suppliagent_agent',
          },
        }),
      }),
      environmentVariables: {
        GATEWAY_URL: gatewayUrl,
        MODEL_ID: config.model.profileId,
        AWS_REGION: this.region,
      },
    });
    gateway.grantInvoke(this.runtime);
    const foundationModel = config.model.profileId.replace(/^eu\./, '');
    this.runtime.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
        resources: [
          `arn:aws:bedrock:${this.region}:${this.account}:inference-profile/${config.model.profileId}`,
          ...config.model.destinationRegions.map(
            (region) => `arn:aws:bedrock:${region}::foundation-model/${foundationModel}`,
          ),
        ],
      }),
    );
    // The L2s create the resource without waiting for the role's DefaultPolicy, and the service
    // checks the permissions at creation (Gateway: KMS on its CMK): wait for the policies.
    for (const [resource, role] of [
      [gateway, gateway.role],
      [this.runtime, this.runtime.role],
    ] as const) {
      // L1 to L1 only: the role is a child of the construct, a construct-level dependency is a cycle.
      const policy = role.node.tryFindChild('DefaultPolicy')?.node.defaultChild;
      const cfnResource = resource.node.defaultChild;
      if (policy instanceof CfnResource && cfnResource instanceof CfnResource) {
        cfnResource.node.addDependency(policy);
      }
    }

    // Read by the turn dispatcher (T-22) and by scripts/invoke_agent.py.
    new ssm.StringParameter(this, 'RuntimeArnParameter', {
      parameterName: `/suppliagent/${config.envName}/agentRuntimeArn`,
      stringValue: this.runtime.agentRuntimeArn,
    });
    new CfnOutput(this, 'RuntimeArn', { value: this.runtime.agentRuntimeArn });
    new CfnOutput(this, 'GatewayUrl', { value: gatewayUrl });

    acknowledgeWildcards(gateway, {
      'Action::kms:GenerateDataKey*': 'Gateway L2 grantEncryptDecrypt on the project CMK.',
      'Action::kms:ReEncrypt*': 'Gateway L2 grantEncryptDecrypt on the project CMK.',
      'Resource::<CustomersToolFunction4E53AA48.Arn>:*':
        'lambda.grantInvoke covers the versions/aliases of the single tool function.',
    });
    acknowledgeWildcards(this.runtime, {
      'Resource::*': 'Runtime L2 default role: X-Ray and CloudWatch metrics need Resource *.',
      [`Resource::arn:aws:logs:${this.region}:<AWS::AccountId>:log-group:*`]:
        'Runtime L2 default role: DescribeLogGroups needs the log-group wildcard.',
      [`Resource::arn:aws:logs:${this.region}:<AWS::AccountId>:log-group:/aws/bedrock-agentcore/runtimes/*`]:
        'Runtime L2 default role: log groups of AgentCore runtimes, created by the service.',
      [`Resource::arn:aws:logs:${this.region}:<AWS::AccountId>:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*`]:
        'Runtime L2 default role: log streams of AgentCore runtimes, created by the service.',
      [`Resource::arn:aws:bedrock-agentcore:${this.region}:<AWS::AccountId>:workload-identity-directory/default/workload-identity/*`]:
        'Runtime L2 default role: workload access token of the runtime identity.',
      'Action::s3:GetBucket*': 'Read of the CDK-managed code asset (fromCodeAsset grantRead).',
      'Action::s3:GetObject*': 'Read of the CDK-managed code asset (fromCodeAsset grantRead).',
      'Action::s3:List*': 'Read of the CDK-managed code asset (fromCodeAsset grantRead).',
      [`Resource::arn:aws:s3:::cdk-hnb659fds-assets-<AWS::AccountId>-${this.region}/*`]:
        'fromCodeAsset grantRead covers the whole CDK assets bucket (code assets only, no data); accepted for the hackathon account.',
    });
  }
}

/** cdk-nag IAM5 acknowledgements for policies generated by L2 constructs, one reason each. */
function acknowledgeWildcards(scope: Construct, findings: Record<string, string>) {
  for (const [finding, reason] of Object.entries(findings)) {
    Validations.of(scope).acknowledge({ id: `AwsSolutions-IAM5[${finding}]`, reason });
  }
}
