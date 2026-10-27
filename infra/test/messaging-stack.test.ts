import { readFileSync } from 'node:fs';
import { App } from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { describe, expect, it } from 'vitest';
import { getConfig } from '../config/environments.js';
import { buildApp } from '../lib/app.js';

const { context } = JSON.parse(readFileSync(new URL('../cdk.json', import.meta.url), 'utf8'));
const stacks = buildApp(new App({ context }), getConfig('dev'));
const template = Template.fromStack(stacks.messaging);

type Statement = { Action: string | string[]; Resource: unknown };
const statements = (): Statement[] =>
  Object.values(template.findResources('AWS::IAM::Policy')).flatMap(
    (p) => p.Properties.PolicyDocument.Statement,
  );

const routerStatements = (): Statement[] => {
  const role = Object.values(template.findResources('AWS::Lambda::Function')).find(
    (f) => f.Properties.FunctionName === 'suppliagent-dev-inbound-router',
  )?.Properties.Role['Fn::GetAtt'][0];
  return Object.values(template.findResources('AWS::IAM::Policy'))
    .filter((p) => JSON.stringify(p.Properties.Roles).includes(role))
    .flatMap((p) => p.Properties.PolicyDocument.Statement);
};

describe('MessagingStack – ingestion (T-21, FN-01)', () => {
  it('creates a KMS-encrypted inbound queue with a DLQ after 3 receives', () => {
    template.hasResourceProperties('AWS::SQS::Queue', {
      QueueName: 'suppliagent-dev-inbound',
      KmsMasterKeyId: Match.anyValue(),
      VisibilityTimeout: 360,
      RedrivePolicy: { deadLetterTargetArn: Match.anyValue(), maxReceiveCount: 3 },
    });
    template.hasResourceProperties('AWS::SQS::Queue', {
      QueueName: 'suppliagent-dev-inbound-dlq',
      KmsMasterKeyId: Match.anyValue(),
    });
  });

  it('subscribes the queue to the WhatsApp and inbound-mail topics, keeping the SNS envelope', () => {
    const subscriptions = Object.values(template.findResources('AWS::SNS::Subscription'));
    expect(subscriptions).toHaveLength(2);
    for (const s of subscriptions) {
      expect(s.Properties.Protocol).toBe('sqs');
      expect(s.Properties.RawMessageDelivery).toBeUndefined();
    }
  });

  it('feeds the router one message at a time, with capped concurrency and a DLQ alarm', () => {
    template.hasResourceProperties('AWS::Lambda::EventSourceMapping', {
      BatchSize: 1,
      ScalingConfig: { MaximumConcurrency: 10 },
    });
    template.hasResourceProperties('AWS::CloudWatch::Alarm', {
      AlarmName: 'suppliagent-dev-inbound-dlq',
      MetricName: 'ApproximateNumberOfMessagesVisible',
    });
    template.hasResourceProperties('AWS::Lambda::Function', {
      FunctionName: 'suppliagent-dev-inbound-router',
      Handler: 'inbound_router.handler.handler',
      Architectures: ['arm64'],
      Environment: {
        Variables: Match.objectLike({ TABLE_PREFIX: 'suppliagent-dev-' }),
      },
    });
  });

  it('gives the router no wildcard actions and no write access to identity tables', () => {
    const actions = routerStatements().flatMap((s) => s.Action);
    expect(actions.filter((a) => a.includes('*') && !a.startsWith('xray:'))).toEqual([]);
    expect(actions).not.toContain('dynamodb:DeleteItem');
    const writes = routerStatements().filter((s) =>
      [s.Action].flat().some((a) => /^dynamodb:(Put|Update)Item$/.test(a)),
    );
    expect(JSON.stringify(writes)).not.toMatch(/ChannelIdentities|Contacts|SalesReps|Customers/);
  });

  it('does not touch the Foundation key policy (no Foundation -> Channels cycle)', () => {
    const foundation = Template.fromStack(stacks.foundation).toJSON();
    expect(JSON.stringify(foundation)).not.toMatch(/channels/i);
  });
});

describe('MessagingStack – media (T-23, FN-05, FN-06)', () => {
  it('lets the router download WhatsApp media and write it under media/ only', () => {
    const json = JSON.stringify(statements());
    expect(json).toContain('social-messaging:GetWhatsAppMessageMedia');
    expect(json).toContain('/media/*');
    template.hasResourceProperties('AWS::IAM::Policy', {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: 's3:ListBucket',
            Condition: { StringLike: { 's3:prefix': 'media/*' } },
          }),
        ]),
      },
    });
  });

  it('reads the phone number id from SSM at runtime, never from code', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      Environment: {
        Variables: Match.objectLike({
          WA_PHONE_NUMBER_ID_PARAM: '/suppliagent/dev/waPhoneNumberId',
        }),
      },
    });
    expect(JSON.stringify(statements())).toContain('parameter/suppliagent/dev/waPhoneNumberId');
  });

  it('lets the router copy simulated media from sim/ only, gated by the sandbox parameter (T-14)', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      Environment: {
        Variables: Match.objectLike({ SANDBOX_PARAM: '/suppliagent/dev/notifierSandbox' }),
      },
    });
    template.hasResourceProperties('AWS::IAM::Policy', {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: 's3:ListBucket',
            Condition: { StringLike: { 's3:prefix': 'sim/*' } },
          }),
        ]),
      },
    });
    const json = JSON.stringify(statements());
    expect(json).toContain('/sim/*');
    expect(json).toContain('parameter/suppliagent/dev/notifierSandbox');
  });

  it('takes the order domain and the SES identity from the environment config, without -c (T-15)', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      Environment: {
        Variables: Match.objectLike({ ORDER_DOMAIN: 'suppliagent.stonecutters.besharp.net' }),
      },
    });
    expect(JSON.stringify(statements())).toContain('identity/suppliagent.stonecutters.besharp.net');
  });
});

describe('MessagingStack – debounce and Notifier (T-22, T-24 base, FN-26, FN-01)', () => {
  const functionProps = (name: string) =>
    Object.values(template.findResources('AWS::Lambda::Function')).find(
      (f) => f.Properties.FunctionName === `suppliagent-dev-${name}`,
    )?.Properties;
  const rolePolicy = (name: string): string => {
    const role = functionProps(name)?.Role['Fn::GetAtt'][0];
    return JSON.stringify(
      Object.values(template.findResources('AWS::IAM::Policy')).filter((p) =>
        JSON.stringify(p.Properties.Roles).includes(role),
      ),
    );
  };

  it('creates a KMS-encrypted turn-flush queue with a DLQ, alarmed, retried after a whole turn', () => {
    template.hasResourceProperties('AWS::SQS::Queue', {
      QueueName: 'suppliagent-dev-turn-flush',
      KmsMasterKeyId: Match.anyValue(),
      VisibilityTimeout: 120,
      RedrivePolicy: { deadLetterTargetArn: Match.anyValue(), maxReceiveCount: 3 },
    });
    template.hasResourceProperties('AWS::CloudWatch::Alarm', {
      AlarmName: 'suppliagent-dev-turn-flush-dlq',
    });
  });

  it('feeds the dispatcher one flush at a time and ends a turn before the lock expires', () => {
    expect(functionProps('turn-dispatcher')?.Timeout).toBeLessThan(120); // turnLockTtlMs
    template.hasResourceProperties('AWS::Lambda::EventSourceMapping', {
      BatchSize: 1,
      ScalingConfig: { MaximumConcurrency: 10 },
      FunctionName: Match.objectLike({ Ref: Match.stringLikeRegexp('TurnDispatcher') }),
    });
    expect(functionProps('turn-dispatcher')?.Environment.Variables).toMatchObject({
      DEBOUNCE_TEXT_MS: '3000',
      DEBOUNCE_MEDIA_MS: '6000',
      DEBOUNCE_MAX_MS: '15000',
      TURN_LOCK_TTL_MS: '120000',
    });
  });

  it('lets the dispatcher invoke only this environment’s agent and the notifier', () => {
    const policy = rolePolicy('turn-dispatcher');
    expect(policy).toContain('bedrock-agentcore:InvokeAgentRuntime');
    expect(policy).toContain('lambda:InvokeFunction');
    expect(policy).not.toMatch(/social-messaging|ses:SendEmail|sns:Publish/);
  });

  it('gives only the notifier the CDS send permissions (AGENTS §8.7)', () => {
    expect(rolePolicy('notifier')).toContain('social-messaging:SendWhatsAppMessage');
    expect(rolePolicy('notifier')).toContain('ses:SendEmail');
    for (const other of ['inbound-router', 'turn-dispatcher']) {
      expect(rolePolicy(other)).not.toMatch(/social-messaging:Send|ses:Send|sms-voice|sns:Publish/);
    }
  });

  it('reads the sandbox switch and the sender settings from SSM at runtime', () => {
    expect(functionProps('notifier')?.Environment.Variables).toMatchObject({
      SANDBOX_PARAM: '/suppliagent/dev/notifierSandbox',
      SES_FROM_PARAM: '/suppliagent/dev/sesFromAddress',
    });
    expect(rolePolicy('notifier')).toContain('parameter/suppliagent/dev/notifierSandbox');
  });

  it('lets the router queue a flush and request a read receipt, nothing more', () => {
    const policy = rolePolicy('inbound-router');
    expect(policy).toContain('sqs:SendMessage');
    expect(policy).toContain('lambda:InvokeFunction');
    expect(policy).toContain('suppliagent-dev-notifier');
  });
});
