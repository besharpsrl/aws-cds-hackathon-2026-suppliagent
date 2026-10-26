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
  it('exposes the customers tools on an MCP gateway with IAM auth and no semantic search', () => {
    template.hasResourceProperties('AWS::BedrockAgentCore::Gateway', {
      AuthorizerType: 'AWS_IAM',
      ProtocolType: 'MCP',
      ProtocolConfiguration: { Mcp: Match.objectEquals({ SupportedVersions: Match.anyValue() }) },
      KmsKeyArn: Match.anyValue(),
    });
    const [target] = Object.values(template.findResources('AWS::BedrockAgentCore::GatewayTarget'));
    const tools = target.Properties.TargetConfiguration.Mcp.Lambda.ToolSchema.InlinePayload;
    expect(tools.map((t: { Name: string }) => t.Name)).toEqual([
      'identify_contact',
      'get_customer_profile',
    ]);
    for (const tool of tools) {
      expect(tool.InputSchema.Properties.caller.Type).toBe('object'); // forwarded to the Lambda
    }
  });

  it('runs the agent from a zip on Python 3.12 with the eu. model from config', () => {
    template.hasResourceProperties('AWS::BedrockAgentCore::Runtime', {
      AgentRuntimeName: 'suppliagent_dev_agent',
      AgentRuntimeArtifact: {
        CodeConfiguration: {
          EntryPoint: ['main.py'],
          Runtime: 'PYTHON_3_12',
          Code: Match.anyValue(),
        },
      },
      EnvironmentVariables: {
        MODEL_ID: 'eu.amazon.nova-pro-v1:0',
        GATEWAY_URL: { 'Fn::GetAtt': [Match.stringLikeRegexp('^Gateway'), 'GatewayUrl'] },
        AWS_REGION: 'eu-west-1',
      },
    });
  });

  it('lets the runtime invoke only the Nova Pro profile and its EU foundation models', () => {
    const bedrock = statementsOf('RuntimeExecutionRole').filter((s) =>
      [s.Action].flat().some((a) => a.startsWith('bedrock:')),
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
    const update = statements.find((s) => [s.Action].flat().includes('dynamodb:UpdateItem'));
    expect(JSON.stringify(update?.Resource)).toContain('Conversations');
  });

  it('configures the tool from the environment config, not hard-coded values', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      FunctionName: 'suppliagent-dev-tool-customers',
      Handler: 'suppliagent_tool_customers.handler.lambda_handler',
      Environment: {
        Variables: Match.objectLike({
          TABLE_PREFIX: 'suppliagent-dev-',
          IDENTIFICATION_MAX_ATTEMPTS: '3',
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
});
