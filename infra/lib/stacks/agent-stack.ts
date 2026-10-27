import * as path from 'node:path';
import { CfnOutput, CfnResource, Duration, Stack, Validations, type StackProps } from 'aws-cdk-lib';
import * as agentcore from 'aws-cdk-lib/aws-bedrockagentcore';
import type * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import type * as events from 'aws-cdk-lib/aws-events';
import * as iam from 'aws-cdk-lib/aws-iam';
import type { IKey } from 'aws-cdk-lib/aws-kms';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import type * as s3 from 'aws-cdk-lib/aws-s3';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import { Construct } from 'constructs';
import type { EnvConfig } from '../../config/environments.js';
import { PythonLambda } from '../constructs/python-lambda.js';
import { REPO_ROOT, uvBundling } from '../constructs/uv-bundling.js';
import type { TableName } from './data-stack.js';
import {
  CATALOG_TOOLS,
  CUSTOMERS_TOOLS,
  INVENTORY_PRICING_TOOLS,
  ORDER_INTAKE_TOOLS,
  ORDERS_TOOLS,
} from './tool-schemas.js';

export interface AgentStackProps extends StackProps {
  readonly config: EnvConfig;
  readonly key: IKey;
  readonly tables: Readonly<Record<TableName, dynamodb.TableV2>>;
  readonly eventBus: events.IEventBus;
  readonly mediaBucket: s3.IBucket;
  /** S3 Vectors bucket name and `products` index ARN from the CatalogStack (T-06). */
  readonly vectorBucketName: string;
  readonly productsIndexArn: string;
}

// Provided by the Lambda runtime and the Powertools layer: not bundled.
const LAMBDA_PLATFORM_PACKAGES = ['boto3', 'botocore', 's3transfer', 'aws-lambda-powertools'];

/**
 * Agent runtime (T-40, reduced): Gateway (MCP, IAM inbound auth) with the `customers` and
 * `order_intake` and `catalog` tool targets and an AgentCore Runtime running the Strands agent from a zip (no container). Memory, Guardrail,
 * the other tool targets and observability extras: T-54.
 */
export class AgentStack extends Stack {
  readonly runtime: agentcore.Runtime;

  constructor(scope: Construct, id: string, props: AgentStackProps) {
    super(scope, id, props);
    const { config, key, tables, eventBus, mediaBucket, vectorBucketName, productsIndexArn } =
      props;
    const prefix = `suppliagent-${config.envName}`;

    const foundationModel = config.model.profileId.replace(/^eu\./, '');
    const modelResources = [
      `arn:aws:bedrock:${this.region}:${this.account}:inference-profile/${config.model.profileId}`,
      ...config.model.destinationRegions.map(
        (region) => `arn:aws:bedrock:${region}::foundation-model/${foundationModel}`,
      ),
    ];

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

    const orderIntake = new PythonLambda(this, 'OrderIntakeTool', {
      config,
      key,
      name: 'tool-order-intake',
      code: lambda.Code.fromAsset(
        path.join(REPO_ROOT, 'services/tools/order_intake'),
        uvBundling({
          package: 'suppliagent-tool-order-intake',
          sources: {
            'services/shared/src/suppliagent_shared': 'suppliagent_shared',
            'services/tools/order_intake/src/suppliagent_tool_order_intake':
              'suppliagent_tool_order_intake',
          },
          omit: LAMBDA_PLATFORM_PACKAGES,
        }),
      ),
      handler: 'suppliagent_tool_order_intake.handler.lambda_handler',
      // Voice notes wait for Transcribe (up to 60 s in the tool) before the model call.
      timeout: Duration.seconds(120),
      environment: {
        MEDIA_BUCKET: mediaBucket.bucketName,
        MODEL_ID: config.model.profileId,
        KMS_KEY_ARN: key.keyArn,
        EVENT_BUS_NAME: eventBus.eventBusName,
      },
    });
    const orderIntakeTool = orderIntake.function;
    // Least privilege: media read, transcripts written by Transcribe with the tool's credentials.
    const allowIntake = (actions: string[], ...resources: string[]) =>
      orderIntakeTool.addToRolePolicy(new iam.PolicyStatement({ actions, resources }));
    allowIntake(
      ['s3:GetObject'],
      mediaBucket.arnForObjects('media/*'),
      mediaBucket.arnForObjects('transcripts/*'),
    );
    allowIntake(['s3:PutObject'], mediaBucket.arnForObjects('transcripts/*'));
    allowIntake(
      ['transcribe:StartTranscriptionJob', 'transcribe:GetTranscriptionJob'],
      `arn:aws:transcribe:${this.region}:${this.account}:transcription-job/ordint-*`,
    );
    allowIntake(['bedrock:InvokeModel'], ...modelResources);
    key.grant(orderIntakeTool, 'kms:Decrypt', 'kms:Encrypt', 'kms:GenerateDataKey');
    eventBus.grantPutEventsTo(orderIntakeTool);

    // the role policy lives under the construct, not under the function
    acknowledgeWildcards(orderIntake, {
      [`Resource::${prefix}-foundation:ExportsOutputFnGetAttMediaBucketBCBB02BAArnB94B784B/media/*`]:
        'One object per inbound media under media/<owner>/<messageId>/; read-only.',
      [`Resource::${prefix}-foundation:ExportsOutputFnGetAttMediaBucketBCBB02BAArnB94B784B/transcripts/*`]:
        'One transcript per voice note under transcripts/<job>.json, written by Transcribe with the tool credentials and read back.',
      [`Resource::arn:aws:transcribe:${this.region}:<AWS::AccountId>:transcription-job/ordint-*`]:
        'Job names are derived from the media key (ordint-<hash>), unknown at deploy time; this account and region only.',
    });

    const catalog = new PythonLambda(this, 'CatalogTool', {
      config,
      key,
      name: 'tool-catalog',
      code: lambda.Code.fromAsset(
        path.join(REPO_ROOT, 'services/tools/catalog'),
        uvBundling({
          package: 'suppliagent-tool-catalog',
          sources: {
            'services/shared/src/suppliagent_shared': 'suppliagent_shared',
            'services/tools/catalog/src/suppliagent_tool_catalog': 'suppliagent_tool_catalog',
          },
          omit: LAMBDA_PLATFORM_PACKAGES,
        }),
      ),
      handler: 'suppliagent_tool_catalog.handler.lambda_handler',
      environment: {
        TABLE_PREFIX: `${prefix}-`,
        EVENT_BUS_NAME: eventBus.eventBusName,
        VECTOR_BUCKET_NAME: vectorBucketName,
        INDEX_NAME: 'products',
        MATCH_AUTO_THRESHOLD: config.parameters.matchAutoThreshold,
        MATCH_ASK_THRESHOLD: config.parameters.matchAskThreshold,
      },
    });
    const catalogTool = catalog.function;
    const allowCatalog = (actions: string[], ...resources: string[]) =>
      catalogTool.addToRolePolicy(new iam.PolicyStatement({ actions, resources }));
    const customersTable = tables.Customers.tableArn;
    allowCatalog(
      ['dynamodb:GetItem', 'dynamodb:Query'],
      customersTable,
      `${customersTable}/index/by-repId`,
    );
    allowCatalog(['dynamodb:GetItem'], tables.Contacts.tableArn);
    allowCatalog(['dynamodb:Query'], tables.OrderHistory.tableArn);
    allowCatalog(['dynamodb:GetItem'], tables.Products.tableArn, tables.Stock.tableArn);
    allowCatalog(['s3vectors:QueryVectors', 's3vectors:GetVectors'], productsIndexArn);
    allowCatalog(
      ['bedrock:InvokeModel'],
      `arn:aws:bedrock:${this.region}::foundation-model/amazon.titan-embed-text-v2:0`,
    );
    key.grant(catalogTool, 'kms:Decrypt', 'kms:Encrypt', 'kms:GenerateDataKey');
    eventBus.grantPutEventsTo(catalogTool);

    // Stock, prices and delivery dates (T-45) and the order lifecycle (T-46): read-mostly tools that
    // share the customer scope checks; only `orders` writes (Orders, Issues) and emits events.
    const allowScope = (fn: lambda.IFunction) => {
      const allowOn = (actions: string[], ...resources: string[]) =>
        fn.addToRolePolicy(new iam.PolicyStatement({ actions, resources }));
      allowOn(
        ['dynamodb:GetItem', 'dynamodb:Query'],
        customersTable,
        `${customersTable}/index/by-repId`,
      );
      allowOn(['dynamodb:GetItem'], tables.Contacts.tableArn);
      allowOn(['dynamodb:GetItem'], tables.PriceLists.tableArn, tables.DeliveryCalendar.tableArn);
      allowOn(['dynamodb:Query'], `${tables.Promotions.tableArn}/index/by-sku`);
      key.grant(fn, 'kms:Decrypt', 'kms:Encrypt', 'kms:GenerateDataKey');
      return allowOn;
    };
    const deliveryRules = {
      DELIVERY_CUTOFF: config.parameters.deliveryCutoff,
      MIN_ORDER_VALUE: config.parameters.minOrderValue,
    };

    const inventoryPricingTool = new PythonLambda(this, 'InventoryPricingTool', {
      config,
      key,
      name: 'tool-inventory-pricing',
      code: lambda.Code.fromAsset(
        path.join(REPO_ROOT, 'services/tools/inventory_pricing'),
        uvBundling({
          package: 'suppliagent-tool-inventory-pricing',
          sources: {
            'services/shared/src/suppliagent_shared': 'suppliagent_shared',
            'services/tools/inventory_pricing/src/suppliagent_tool_inventory_pricing':
              'suppliagent_tool_inventory_pricing',
          },
          omit: LAMBDA_PLATFORM_PACKAGES,
        }),
      ),
      handler: 'suppliagent_tool_inventory_pricing.handler.lambda_handler',
      environment: { TABLE_PREFIX: `${prefix}-`, ...deliveryRules },
    }).function;
    allowScope(inventoryPricingTool)(
      ['dynamodb:GetItem'],
      tables.Products.tableArn,
      tables.Stock.tableArn,
    );

    const ordersTool = new PythonLambda(this, 'OrdersTool', {
      config,
      key,
      name: 'tool-orders',
      code: lambda.Code.fromAsset(
        path.join(REPO_ROOT, 'services/tools/orders'),
        uvBundling({
          package: 'suppliagent-tool-orders',
          sources: {
            'services/shared/src/suppliagent_shared': 'suppliagent_shared',
            'services/tools/orders/src/suppliagent_tool_orders': 'suppliagent_tool_orders',
          },
          omit: LAMBDA_PLATFORM_PACKAGES,
        }),
      ),
      handler: 'suppliagent_tool_orders.handler.lambda_handler',
      environment: {
        TABLE_PREFIX: `${prefix}-`,
        EVENT_BUS_NAME: eventBus.eventBusName,
        MEDIA_BUCKET: mediaBucket.bucketName,
        ...deliveryRules,
      },
    }).function;
    const allowOrders = allowScope(ordersTool);
    allowOrders(['dynamodb:GetItem'], tables.Products.tableArn, tables.Deliveries.tableArn);
    allowOrders(
      ['dynamodb:GetItem', 'dynamodb:PutItem', 'dynamodb:UpdateItem'],
      tables.Orders.tableArn,
    );
    allowOrders(['dynamodb:Query'], `${tables.Orders.tableArn}/index/by-customerId`);
    allowOrders(['dynamodb:PutItem'], tables.Issues.tableArn);
    // Evidence that the customer answered after the summary (confirm_order): read-only.
    allowOrders(['dynamodb:Query'], tables.Messages.tableArn);
    eventBus.grantPutEventsTo(ordersTool);

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
    gateway.addLambdaTarget('OrderIntakeTarget', {
      // Target names take no underscore: the tool the model sees is `order-intake___extract_order_lines`.
      gatewayTargetName: 'order-intake',
      description: 'Order lines from photos, voice notes and text (T-43).',
      lambdaFunction: orderIntakeTool,
      toolSchema: agentcore.ToolSchema.fromInline(ORDER_INTAKE_TOOLS),
    });
    gateway.addLambdaTarget('CatalogTarget', {
      gatewayTargetName: 'catalog',
      description: 'Product matching with order history and catalog search (T-44).',
      lambdaFunction: catalogTool,
      toolSchema: agentcore.ToolSchema.fromInline(CATALOG_TOOLS),
    });
    gateway.addLambdaTarget('InventoryPricingTarget', {
      gatewayTargetName: 'inventory-pricing',
      description: 'Stock with substitutes, price lists and delivery dates (T-45).',
      lambdaFunction: inventoryPricingTool,
      toolSchema: agentcore.ToolSchema.fromInline(INVENTORY_PRICING_TOOLS),
    });
    gateway.addLambdaTarget('OrdersTarget', {
      gatewayTargetName: 'orders',
      description: 'Order drafts, confirmation, changes, status and delivery issues (T-46).',
      lambdaFunction: ordersTool,
      toolSchema: agentcore.ToolSchema.fromInline(ORDERS_TOOLS),
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
    this.runtime.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
        resources: modelResources,
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
      'Resource::<OrderIntakeToolFunctionCF96ADCC.Arn>:*':
        'lambda.grantInvoke covers the versions/aliases of the single tool function.',
      'Resource::<CatalogToolFunctionA3D81DAD.Arn>:*':
        'lambda.grantInvoke covers the versions/aliases of the single tool function.',
      'Resource::<InventoryPricingToolFunction29E9FD79.Arn>:*':
        'lambda.grantInvoke covers the versions/aliases of the single tool function.',
      'Resource::<OrdersToolFunction85C7D529.Arn>:*':
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
