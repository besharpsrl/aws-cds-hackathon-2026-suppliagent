import { createHash } from 'node:crypto';
import * as path from 'node:path';
import {
  CfnOutput,
  CfnResource,
  Duration,
  RemovalPolicy,
  Stack,
  Validations,
  type StackProps,
} from 'aws-cdk-lib';
import * as bedrock from 'aws-cdk-lib/aws-bedrock';
import * as agentcore from 'aws-cdk-lib/aws-bedrockagentcore';
import type * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import type * as events from 'aws-cdk-lib/aws-events';
import * as iam from 'aws-cdk-lib/aws-iam';
import type { IKey } from 'aws-cdk-lib/aws-kms';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import type * as s3 from 'aws-cdk-lib/aws-s3';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import * as cr from 'aws-cdk-lib/custom-resources';
import { Construct } from 'constructs';
import { MANDATORY_TAGS, type EnvConfig } from '../../config/environments.js';
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
 * Agent runtime: Gateway (MCP, IAM inbound auth) with the tool targets, an AgentCore Runtime running
 * the Strands agent from a zip (no container), AgentCore Memory, a Bedrock Guardrail and the
 * Runtime's observability (traces, application logs, log group retention and CMK) (T-40, T-41, T-54).
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
        PRIVACY_NOTICE_VERSION: config.parameters.privacyNoticeVersion,
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
      ['dynamodb:GetItem', 'dynamodb:PutItem', 'dynamodb:DeleteItem', 'dynamodb:UpdateItem'],
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
    // share the customer scope checks; only `orders` writes (Orders, Issues, and Conversations
    // mode/handoff for handoff_to_human) and emits events.
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
    // handoff_to_human (T-49): table-level grant; the tool keys the update on caller.conversationId.
    allowOrders(['dynamodb:UpdateItem'], tables.Conversations.tableArn);
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

    // AgentCore Memory (T-54, FN-25): `actorId` = contact, `sessionId` = conversation. The agent
    // recalls the `preferences` and `facts` namespaces (agent/src/suppliagent_agent/app.py).
    const memory = new agentcore.Memory(this, 'Memory', {
      memoryName: `suppliagent_${config.envName}_memory`,
      description: 'Conversation history and long-term notes per contact',
      expirationDuration: Duration.days(30),
      kmsKey: key,
      memoryStrategies: [
        agentcore.MemoryStrategy.usingUserPreference({
          strategyName: 'preferences',
          namespaces: ['/preferences/{actorId}'],
        }),
        agentcore.MemoryStrategy.usingSemantic({
          strategyName: 'facts',
          namespaces: ['/facts/{actorId}'],
        }),
        agentcore.MemoryStrategy.usingSummarization({
          strategyName: 'summaries',
          namespaces: ['/summaries/{actorId}/{sessionId}'],
        }),
      ],
    });

    acknowledgeWildcards(memory, {
      'Action::kms:ReEncrypt*':
        'Memory L2 grantEncryptDecrypt on the project CMK for its service role.',
      'Action::kms:GenerateDataKey*':
        'Memory L2 grantEncryptDecrypt on the project CMK for its service role.',
    });

    const guardrail = new AgentGuardrail(this, 'Guardrail', {
      prefix,
      key,
      // the EU guardrail profile routes to the same regions as the `eu.` model profile
      destinationRegions: config.model.destinationRegions,
    });

    // Application logs and traces of the Runtime (T-54): our log group, with the CMK and retention.
    const applicationLogs = new logs.LogGroup(this, 'RuntimeApplicationLogs', {
      logGroupName: `/aws/vendedlogs/bedrock-agentcore/${prefix}-agent`,
      retention: config.logRetention,
      encryptionKey: key,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    this.runtime = new agentcore.Runtime(this, 'Runtime', {
      runtimeName: `suppliagent_${config.envName}_agent`,
      description: 'SuppliAgent Strands agent (T-41).',
      agentRuntimeArtifact: agentcore.AgentRuntimeArtifact.fromCodeAsset({
        path: path.join(REPO_ROOT, 'agent'),
        runtime: agentcore.AgentCoreRuntime.PYTHON_3_12,
        // ADOT (aws-opentelemetry-distro) instruments the agent: spans to CloudWatch GenAI Observability.
        entrypoint: ['opentelemetry-instrument', 'main.py'],
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
        PRIVACY_NOTICE_URL: config.parameters.privacyNoticeUrl,
        MEMORY_ID: memory.memoryId,
        GUARDRAIL_ID: guardrail.guardrailId,
        GUARDRAIL_VERSION: guardrail.version,
        AGENT_OBSERVABILITY_ENABLED: 'true',
        OTEL_PYTHON_DISTRO: 'aws_distro',
        OTEL_PYTHON_CONFIGURATOR: 'aws_configurator',
        // Strands: message texts, prompts and tool inputs/results are redacted in the spans (no
        // message contents, phone numbers or emails in traces, AGENTS.md §7).
        OTEL_SEMCONV_STABILITY_OPT_IN: 'gen_ai_unredacted_attributes=',
        OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT: 'false',
      },
      tracingEnabled: true,
      loggingConfigs: [
        {
          logType: agentcore.LogType.APPLICATION_LOGS,
          destination: agentcore.LoggingDestination.cloudWatchLogs(applicationLogs),
        },
      ],
    });
    gateway.grantInvoke(this.runtime);
    memory.grantRead(this.runtime);
    memory.grantWrite(this.runtime);
    this.runtime.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['bedrock:ApplyGuardrail'],
        resources: guardrail.resources,
      }),
    );
    // Memory and Guardrail are encrypted with the CMK: the caller's role needs the key.
    key.grant(this.runtime, 'kms:Decrypt', 'kms:GenerateDataKey');
    retainRuntimeLogs(this, this.runtime, config, key);
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
    new CfnOutput(this, 'MemoryId', { value: memory.memoryId });
    new CfnOutput(this, 'GuardrailId', { value: guardrail.guardrailId });

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

interface AgentGuardrailProps {
  readonly prefix: string;
  readonly key: IKey;
  /** Regions `eu.guardrail.v1:0` routes to from this region: IAM needs the profile in each. */
  readonly destinationRegions: readonly string[];
}

/**
 * Bedrock Guardrail of the agent (T-54, FN-32, E-06), checked on the user's latest message and on
 * every reply. Calibrated not to block normal ordering: no PII filter on names, phone numbers,
 * emails or VAT numbers (identification needs them); "other customers' data" is enforced by the
 * tools (scope checks), which know who the caller is, not by a topic classifier.
 */
class AgentGuardrail extends Construct {
  readonly guardrailId: string;
  readonly version: string;
  /** ARNs for `bedrock:ApplyGuardrail`: the guardrail and the EU guardrail profile in each region. */
  readonly resources: string[];

  constructor(scope: Construct, id: string, props: AgentGuardrailProps) {
    super(scope, id);
    const stack = Stack.of(this);
    // Standard tier: content filters and denied topics in Italian too (Classic: English, French,
    // Spanish only); it requires the cross-region guardrail profile, EU only.
    const profileArn = (region: string) =>
      `arn:aws:bedrock:${region}:${stack.account}:guardrail-profile/eu.guardrail.v1:0`;
    const filter = (type: string, strength = 'MEDIUM') => ({
      type,
      inputStrength: strength,
      outputStrength: strength,
    });
    const blocked = (type: string) => ({ type, action: 'BLOCK' });
    const policy = {
      contentPolicyConfig: {
        contentFiltersTierConfig: { tierName: 'STANDARD' },
        filtersConfig: [
          filter('HATE'),
          filter('INSULTS'),
          filter('SEXUAL'),
          filter('VIOLENCE'),
          filter('MISCONDUCT'),
          { type: 'PROMPT_ATTACK', inputStrength: 'MEDIUM', outputStrength: 'NONE' },
        ],
      },
      topicPolicyConfig: {
        topicsTierConfig: { tierName: 'STANDARD' },
        topicsConfig: [
          {
            name: 'Unauthorized discounts',
            type: 'DENY',
            // Output only: a user asking for a discount must reach the agent, which hands off
            // (OUT_OF_SCOPE); the agent itself must never grant one.
            inputEnabled: false,
            outputEnabled: true,
            definition:
              'The assistant grants, promises or confirms a discount, special price, free goods, credit or payment terms for the customer.',
            examples: [
              'Ok, ti faccio il 10% di sconto su questo ordine.',
              'I can give you the olive oil at 5 euros instead of 7.',
              'Va bene, la consegna te la regalo e paghi a 90 giorni.',
            ],
          },
          {
            name: 'Medical advice',
            type: 'DENY',
            definition:
              'Medical or health advice for a person: diagnoses, treatments, or whether a food is safe for their illness, pregnancy or intolerance.',
            examples: [
              'Sono celiaco, posso mangiare questa pasta senza stare male?',
              'What should I take for food poisoning?',
              'Sono incinta, posso mangiare la burrata?',
            ],
          },
        ],
      },
      sensitiveInformationPolicyConfig: {
        piiEntitiesConfig: [
          blocked('CREDIT_DEBIT_CARD_NUMBER'),
          blocked('CREDIT_DEBIT_CARD_CVV'),
          blocked('CREDIT_DEBIT_CARD_EXPIRY'),
          blocked('PIN'),
          blocked('PASSWORD'),
          blocked('AWS_ACCESS_KEY'),
          blocked('AWS_SECRET_KEY'),
        ],
      },
    };
    const guardrail = new bedrock.CfnGuardrail(this, 'Resource', {
      name: `${props.prefix}-agent`,
      description: 'SuppliAgent agent: harmful content, prompt attacks, discounts, medical advice.',
      // Replaced in the reply by the agent's localized safe answer (E-06).
      blockedInputMessaging: 'Non posso aiutarti con questa richiesta. / I cannot help with that.',
      blockedOutputsMessaging:
        'Non posso aiutarti con questa richiesta. / I cannot help with that.',
      kmsKeyArn: props.key.keyArn,
      crossRegionConfig: { guardrailProfileArn: profileArn(stack.region) },
      ...policy,
    });
    // A version is immutable: a new one is published whenever the policy changes.
    const digest = createHash('sha256').update(JSON.stringify(policy)).digest('hex').slice(0, 16);
    const version = new bedrock.CfnGuardrailVersion(this, 'Version', {
      guardrailIdentifier: guardrail.attrGuardrailId,
      description: `Policy ${digest}`,
    });
    this.guardrailId = guardrail.attrGuardrailId;
    this.version = version.attrVersion;
    this.resources = [
      guardrail.attrGuardrailArn,
      ...new Set([stack.region, ...props.destinationRegions].map(profileArn)),
    ];
  }
}

/**
 * The Runtime writes stdout and the OTel logs to `/aws/bedrock-agentcore/runtimes/<id>-DEFAULT`,
 * a log group it creates itself at the first invocation (outside CloudFormation): create it first if
 * missing, then set retention, the CMK and the mandatory tags (AGENTS.md §7) on it.
 */
function retainRuntimeLogs(
  scope: Construct,
  runtime: agentcore.Runtime,
  config: EnvConfig,
  key: IKey,
) {
  const stack = Stack.of(scope);
  const logGroupName = `/aws/bedrock-agentcore/runtimes/${runtime.agentRuntimeId}-DEFAULT`;
  const logGroupArn = `arn:aws:logs:${stack.region}:${stack.account}:log-group:${logGroupName}`;
  const tags = { ...MANDATORY_TAGS, Env: config.envName };
  const call = (action: string, parameters: Record<string, unknown>, ignore?: string) => ({
    service: 'CloudWatchLogs',
    action,
    parameters,
    physicalResourceId: cr.PhysicalResourceId.of(logGroupName),
    ...(ignore ? { ignoreErrorCodesMatching: ignore } : {}),
  });
  const policy = cr.AwsCustomResourcePolicy.fromStatements([
    new iam.PolicyStatement({
      actions: [
        'logs:CreateLogGroup',
        'logs:PutRetentionPolicy',
        'logs:AssociateKmsKey',
        'logs:TagResource',
      ],
      resources: [logGroupArn, `${logGroupArn}:*`],
    }),
  ]);
  const steps: [string, ReturnType<typeof call>][] = [
    [
      'RuntimeLogGroup',
      call(
        'createLogGroup',
        { logGroupName, kmsKeyId: key.keyArn, tags },
        'ResourceAlreadyExistsException',
      ),
    ],
    ['RuntimeLogGroupKey', call('associateKmsKey', { logGroupName, kmsKeyId: key.keyArn })],
    [
      'RuntimeLogGroupRetention',
      call('putRetentionPolicy', { logGroupName, retentionInDays: config.logRetention }),
    ],
    ['RuntimeLogGroupTags', call('tagResource', { resourceArn: logGroupArn, tags })],
  ];
  let previous: Construct | undefined;
  for (const [id, sdkCall] of steps) {
    const resource = new cr.AwsCustomResource(scope, id, {
      onCreate: sdkCall,
      onUpdate: sdkCall,
      policy,
      installLatestAwsSdk: false,
    });
    if (previous) resource.node.addDependency(previous);
    previous = resource;
    acknowledgeWildcards(resource, {
      [`Resource::arn:aws:logs:${stack.region}:<AWS::AccountId>:log-group:/aws/bedrock-agentcore/runtimes/<${stack.getLogicalId(runtime.node.defaultChild as CfnResource)}.AgentRuntimeId>-DEFAULT:*`]:
        'The log-group ARN form IAM matches for CloudWatch Logs actions; this runtime log group only.',
    });
  }
  // The shared Lambda of AwsCustomResource (one per stack).
  const provider = stack.node.tryFindChild(
    `AWS${cr.AwsCustomResource.PROVIDER_FUNCTION_UUID.replace(/-/g, '')}`,
  );
  if (provider) {
    Validations.of(provider).acknowledge({
      id: 'AwsSolutions-IAM4[Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole]',
      reason: 'AwsCustomResource provider: CloudWatch Logs write for its own log group only.',
    });
  }
}
