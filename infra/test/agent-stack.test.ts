import { App } from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { describe, expect, it } from 'vitest';
import { getConfig } from '../config/environments.js';
import { buildApp } from '../lib/app.js';
import { context } from './context.js';

const template = Template.fromStack(buildApp(new App({ context }), getConfig('dev')).agent);

type Statement = { Action: string | string[]; Resource: unknown };
const statementsOf = (roleLogicalIdPrefix: string): Statement[] =>
  Object.entries(template.findResources('AWS::IAM::Policy'))
    .filter(([id]) => id.startsWith(roleLogicalIdPrefix))
    .flatMap(([, policy]) => policy.Properties.PolicyDocument.Statement as Statement[]);
const actions = (statements: Statement[]) => statements.flatMap((s) => [s.Action].flat());

describe('AgentStack (T-40, T-41 reduced, FN-32)', () => {
  it('exposes the tool targets on an MCP gateway with IAM auth and no semantic search', () => {
    template.hasResourceProperties('AWS::BedrockAgentCore::Gateway', {
      AuthorizerType: 'AWS_IAM',
      ProtocolType: 'MCP',
      ProtocolConfiguration: { Mcp: Match.objectEquals({ SupportedVersions: Match.anyValue() }) },
      KmsKeyArn: Match.anyValue(),
    });
    const targets = Object.values(template.findResources('AWS::BedrockAgentCore::GatewayTarget'));
    const toolsOf = (name: string) =>
      targets.find((t) => t.Properties.Name === name)?.Properties.TargetConfiguration.Mcp.Lambda
        .ToolSchema.InlinePayload;
    expect(targets).toHaveLength(6);
    expect(toolsOf('customers').map((t: { Name: string }) => t.Name)).toEqual([
      'identify_contact',
      'get_customer_profile',
      'update_privacy',
      'set_order_email',
    ]);
    expect(toolsOf('order-intake').map((t: { Name: string }) => t.Name)).toEqual([
      'extract_order_lines',
    ]);
    expect(toolsOf('catalog').map((t: { Name: string }) => t.Name)).toEqual([
      'match_products',
      'search_catalog',
    ]);
    expect(toolsOf('inventory-pricing').map((t: { Name: string }) => t.Name)).toEqual([
      'check_availability',
      'get_prices',
      'get_delivery_options',
    ]);
    expect(toolsOf('orders').map((t: { Name: string }) => t.Name)).toEqual([
      'create_order_draft',
      'update_order_draft',
      'request_order_confirmation',
      'confirm_order',
      'cancel_order',
      'get_order_status',
      'report_delivery_issue',
      'handoff_to_human',
    ]);
    expect(toolsOf('reco').map((t: { Name: string }) => t.Name)).toEqual([
      'recommend_products',
      'record_suggestion_outcome',
    ]);
    for (const tool of [
      ...toolsOf('customers'),
      ...toolsOf('order-intake'),
      ...toolsOf('catalog'),
      ...toolsOf('inventory-pricing'),
      ...toolsOf('orders'),
      ...toolsOf('reco'),
    ]) {
      expect(tool.InputSchema.Properties.caller.Type).toBe('object'); // forwarded to the Lambda
    }
  });

  it('runs the agent from a zip on Python 3.12 with the eu. model from config', () => {
    template.hasResourceProperties('AWS::BedrockAgentCore::Runtime', {
      AgentRuntimeName: 'suppliagent_dev_agent',
      AgentRuntimeArtifact: {
        CodeConfiguration: {
          EntryPoint: ['opentelemetry-instrument', 'main.py'],
          Runtime: 'PYTHON_3_12',
          Code: Match.anyValue(),
        },
      },
      EnvironmentVariables: Match.objectLike({
        MODEL_ID: 'eu.amazon.nova-pro-v1:0',
        GATEWAY_URL: { 'Fn::GetAtt': [Match.stringLikeRegexp('^Gateway'), 'GatewayUrl'] },
        AWS_REGION: 'eu-west-1',
        PRIVACY_NOTICE_URL: 'UNSET',
        MEMORY_ID: { 'Fn::GetAtt': [Match.stringLikeRegexp('^Memory'), 'MemoryId'] },
        GUARDRAIL_ID: { 'Fn::GetAtt': [Match.stringLikeRegexp('^Guardrail'), 'GuardrailId'] },
        GUARDRAIL_VERSION: {
          'Fn::GetAtt': [Match.stringLikeRegexp('^GuardrailVersion'), 'Version'],
        },
        // no message contents in the spans (AGENTS.md §7)
        OTEL_SEMCONV_STABILITY_OPT_IN: 'gen_ai_unredacted_attributes=',
      }),
    });
  });

  it('keeps conversations and per-contact notes in AgentCore Memory, encrypted with the CMK (FN-25)', () => {
    template.hasResourceProperties('AWS::BedrockAgentCore::Memory', {
      Name: 'suppliagent_dev_memory',
      EncryptionKeyArn: Match.anyValue(),
      EventExpiryDuration: 30,
    });
    const [memory] = Object.values(template.findResources('AWS::BedrockAgentCore::Memory'));
    const namespaces = JSON.stringify(memory.Properties.MemoryStrategies);
    // the namespaces the agent recalls (agent/src/suppliagent_agent/app.py)
    expect(namespaces).toContain('/preferences/{actorId}');
    expect(namespaces).toContain('/facts/{actorId}');
    const runtime = actions(statementsOf('RuntimeExecutionRole'));
    expect(runtime).toEqual(
      expect.arrayContaining(['bedrock-agentcore:CreateEvent', 'bedrock-agentcore:ListEvents']),
    );
    // DeleteEvent only: the guardrail redaction replaces a blocked message in the history
    expect(runtime.filter((a) => /Delete|CreateMemory|UpdateMemory/.test(a))).toEqual([
      'bedrock-agentcore:DeleteEvent',
    ]);
  });

  it('applies a guardrail that does not filter the contact data needed to identify a caller (FN-32)', () => {
    const [guardrail] = Object.values(template.findResources('AWS::Bedrock::Guardrail'));
    expect(guardrail.Properties.KmsKeyArn).toBeDefined();
    // Standard tier (Italian) through the EU guardrail profile only
    expect(JSON.stringify(guardrail.Properties.CrossRegionConfig)).toContain(
      ':guardrail-profile/eu.guardrail.v1:0',
    );
    const pii = JSON.stringify(guardrail.Properties.SensitiveInformationPolicyConfig);
    for (const type of ['EMAIL', 'PHONE', 'NAME', 'ADDRESS'])
      expect(pii).not.toContain(`"${type}"`);
    const topics = guardrail.Properties.TopicPolicyConfig.TopicsConfig as {
      Name: string;
      InputEnabled?: boolean;
    }[];
    // a discount request must reach the agent, which hands off (OUT_OF_SCOPE)
    expect(topics.find((t) => t.Name === 'Unauthorized discounts')?.InputEnabled).toBe(false);
    const apply = statementsOf('RuntimeExecutionRole').filter((s) =>
      [s.Action].flat().includes('bedrock:ApplyGuardrail'),
    );
    expect(JSON.stringify(apply)).toContain('GuardrailArn');
    for (const region of ['eu-west-1', 'eu-central-1', 'eu-west-3', 'eu-north-1']) {
      expect(JSON.stringify(apply)).toContain(`arn:aws:bedrock:${region}:`);
    }
    template.resourceCountIs('AWS::Bedrock::GuardrailVersion', 1);
  });

  it('sends runtime traces and application logs to a CMK log group with retention', () => {
    template.hasResourceProperties('AWS::Logs::LogGroup', {
      LogGroupName: '/aws/vendedlogs/bedrock-agentcore/suppliagent-dev-agent',
      RetentionInDays: 14,
      KmsKeyId: Match.anyValue(),
    });
    template.hasResourceProperties('AWS::Logs::Delivery', {});
    // the log group the Runtime creates itself gets retention, CMK and tags
    const calls = JSON.stringify(template.findResources('Custom::AWS'));
    for (const call of ['createLogGroup', 'associateKmsKey', 'putRetentionPolicy', 'tagResource']) {
      expect(calls).toContain(call);
    }
    const policies = JSON.stringify(template.findResources('AWS::IAM::Policy'));
    expect(policies).toContain('kms:DescribeKey');
  });

  it('lets the runtime invoke only the Nova Pro profile and its EU foundation models', () => {
    const bedrock = statementsOf('RuntimeExecutionRole').filter((s) =>
      [s.Action].flat().some((a) => a.startsWith('bedrock:Invoke')),
    );
    expect(bedrock).toHaveLength(1);
    const resources = JSON.stringify(bedrock[0].Resource);
    expect(resources).toContain('inference-profile/eu.amazon.nova-pro-v1:0');
    expect(resources).toContain('eu-central-1::foundation-model/amazon.nova-pro-v1:0');
    expect(resources).not.toMatch(/foundation-model\/\*|"\*"/);
  });

  it('lets only the runtime invoke the gateway', () => {
    const invokers = Object.entries(template.findResources('AWS::IAM::Policy')).filter(
      ([, policy]) => JSON.stringify(policy).includes('bedrock-agentcore:InvokeGateway'),
    );
    expect(invokers.map(([id]) => id)).toEqual([expect.stringMatching(/^RuntimeExecutionRole/)]);
  });

  it('gives the customers tool exactly the DynamoDB calls it makes, without index wildcards', () => {
    const statements = statementsOf('CustomersToolRole');
    expect(new Set(actions(statements))).toEqual(
      new Set([
        'logs:CreateLogStream',
        'logs:PutLogEvents',
        'xray:PutTraceSegments',
        'xray:PutTelemetryRecords',
        'dynamodb:GetItem',
        'dynamodb:Scan',
        'dynamodb:Query',
        'dynamodb:PutItem',
        'dynamodb:DeleteItem',
        'dynamodb:UpdateItem',
        'kms:Decrypt',
        'kms:Encrypt',
        'kms:GenerateDataKey',
        'events:PutEvents',
      ]),
    );
    expect(JSON.stringify(statements)).not.toContain('/index/*');
    const updates = statements
      .filter((s) => [s.Action].flat().includes('dynamodb:UpdateItem'))
      .map((s) => JSON.stringify(s.Resource));
    expect(updates).toHaveLength(2);
    expect(updates.some((r) => r.includes('Conversations'))).toBe(true);
    expect(updates.some((r) => r.includes('Contacts'))).toBe(true); // privacy and consent (T-48)
  });

  it('configures the tool from the environment config, not hard-coded values', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      FunctionName: 'suppliagent-dev-tool-customers',
      Handler: 'suppliagent_tool_customers.handler.lambda_handler',
      Environment: {
        Variables: Match.objectLike({
          TABLE_PREFIX: 'suppliagent-dev-',
          IDENTIFICATION_MAX_ATTEMPTS: '3',
          PRIVACY_NOTICE_VERSION: '2026-10-28',
          EVENT_BUS_NAME: Match.anyValue(),
        }),
      },
    });
  });

  it('gives the order intake tool media read, Transcribe and the Nova profile, nothing wider (T-43)', () => {
    const statements = statementsOf('OrderIntakeToolRole');
    expect(new Set(actions(statements))).toEqual(
      new Set([
        'logs:CreateLogStream',
        'logs:PutLogEvents',
        'xray:PutTraceSegments',
        'xray:PutTelemetryRecords',
        's3:GetObject',
        's3:PutObject',
        'transcribe:StartTranscriptionJob',
        'transcribe:GetTranscriptionJob',
        'bedrock:InvokeModel',
        'kms:Decrypt',
        'kms:Encrypt',
        'kms:GenerateDataKey',
        'events:PutEvents',
      ]),
    );
    const find = (action: string) => statements.find((s) => [s.Action].flat().includes(action));
    const reads = JSON.stringify(find('s3:GetObject')?.Resource);
    expect(reads).toContain('/media/*');
    expect(reads).toContain('/transcripts/*');
    expect(JSON.stringify(find('s3:PutObject')?.Resource)).not.toContain('/media/*');
    expect(JSON.stringify(find('transcribe:StartTranscriptionJob')?.Resource)).toContain(
      'transcription-job/ordint-*',
    );
    const model = JSON.stringify(find('bedrock:InvokeModel')?.Resource);
    expect(model).toContain('inference-profile/eu.amazon.nova-pro-v1:0');
    expect(model).not.toMatch(/foundation-model\/\*|"\*"/);
  });

  it('configures the order intake tool from the environment config', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      FunctionName: 'suppliagent-dev-tool-order-intake',
      Handler: 'suppliagent_tool_order_intake.handler.lambda_handler',
      Timeout: 120,
      Environment: {
        Variables: Match.objectLike({
          MODEL_ID: 'eu.amazon.nova-pro-v1:0',
          MEDIA_BUCKET: Match.anyValue(),
          KMS_KEY_ARN: Match.anyValue(),
          EVENT_BUS_NAME: Match.anyValue(),
        }),
      },
    });
  });

  it('publishes the runtime ARN for the dispatcher', () => {
    template.hasResourceProperties('AWS::SSM::Parameter', {
      Name: '/suppliagent/dev/agentRuntimeArn',
      Value: { 'Fn::GetAtt': [Match.stringLikeRegexp('^Runtime'), 'AgentRuntimeArn'] },
    });
  });

  it('creates gateway and runtime only after their role policies', () => {
    for (const type of ['AWS::BedrockAgentCore::Gateway', 'AWS::BedrockAgentCore::Runtime']) {
      const [resource] = Object.values(template.findResources(type));
      expect(resource.DependsOn).toEqual(
        expect.arrayContaining([expect.stringMatching(/RoleDefaultPolicy/)]),
      );
    }
  });

  it('gives the catalog tool read-only access to the product index, tables and the embedding model', () => {
    const statements = statementsOf('CatalogTool');
    const all = actions(statements);
    expect(all).toEqual(expect.arrayContaining(['s3vectors:QueryVectors', 'bedrock:InvokeModel']));
    // reads only: no table or index writes, no wildcard actions
    expect(all.filter((a) => /^(dynamodb|s3vectors):.*(Put|Update|Delete|Scan)/.test(a))).toEqual(
      [],
    );
    expect(all.some((a) => a.endsWith('*'))).toBe(false);
    template.hasResourceProperties('AWS::Lambda::Function', {
      FunctionName: 'suppliagent-dev-tool-catalog',
      Handler: 'suppliagent_tool_catalog.handler.lambda_handler',
      Environment: {
        Variables: Match.objectLike({ INDEX_NAME: 'products', MATCH_AUTO_THRESHOLD: '0.85' }),
      },
    });
  });

  it('gives the inventory/pricing tool read-only access and the delivery rules from config', () => {
    const all = actions(statementsOf('InventoryPricingTool'));
    expect(all.filter((a) => /^dynamodb:(Put|Update|Delete|Scan|Batch)/.test(a))).toEqual([]);
    expect(all.some((a) => a.endsWith('*'))).toBe(false);
    expect(all).not.toContain('events:PutEvents');
    template.hasResourceProperties('AWS::Lambda::Function', {
      FunctionName: 'suppliagent-dev-tool-inventory-pricing',
      Handler: 'suppliagent_tool_inventory_pricing.handler.lambda_handler',
      Environment: {
        Variables: Match.objectLike({ DELIVERY_CUTOFF: '18:00', MIN_ORDER_VALUE: '0' }),
      },
    });
  });

  it('lets the reco tool write only the suggestion on Orders and CustomerInsights (T-50)', () => {
    const statements = statementsOf('RecoTool');
    const all = actions(statements);
    expect(all.filter((a) => /^dynamodb:(Put|Delete|Batch)/.test(a))).toEqual([]);
    expect(all.some((a) => a.endsWith('*'))).toBe(false);
    expect(all).toContain('events:PutEvents');
    const writes = statements.filter((s) =>
      [s.Action].flat().some((a) => /^dynamodb:Update/.test(a)),
    );
    const written = JSON.stringify(writes.map((s) => s.Resource));
    expect(written).toMatch(/GetAttOrders/);
    expect(written).toMatch(/GetAttCustomerInsights/);
    expect(written).not.toMatch(/GetAtt(Customers|Contacts|Products|PriceLists|Promotions)/);
    template.hasResourceProperties('AWS::Lambda::Function', {
      FunctionName: 'suppliagent-dev-tool-reco',
      Handler: 'suppliagent_tool_reco.handler.lambda_handler',
    });
  });

  it('lets the orders tool write only Orders and Issues, never delete, and emit events', () => {
    const statements = statementsOf('OrdersTool');
    const all = actions(statements);
    expect(all.filter((a) => /^dynamodb:(Delete|Scan|Batch)/.test(a))).toEqual([]);
    expect(all.some((a) => a.endsWith('*'))).toBe(false);
    expect(all).toContain('events:PutEvents');
    const writes = statements.filter((s) =>
      [s.Action].flat().some((a) => /^dynamodb:(Put|Update)/.test(a)),
    );
    const written = JSON.stringify(writes.map((s) => s.Resource));
    expect(written).toMatch(/GetAttOrders/);
    expect(written).toMatch(/GetAttIssues/);
    expect(written).not.toMatch(/Customers|Contacts|Products|PriceLists|Promotions/);
    template.hasResourceProperties('AWS::Lambda::Function', {
      FunctionName: 'suppliagent-dev-tool-orders',
      Handler: 'suppliagent_tool_orders.handler.lambda_handler',
      Environment: {
        Variables: Match.objectLike({
          DELIVERY_CUTOFF: '18:00',
          MIN_ORDER_VALUE: '0',
          MEDIA_BUCKET: Match.anyValue(),
        }),
      },
    });
  });
});
