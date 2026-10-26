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
    const actions = statements().flatMap((s) => s.Action);
    expect(actions.filter((a) => a.includes('*') && !a.startsWith('xray:'))).toEqual([]);
    expect(actions).not.toContain('dynamodb:DeleteItem');
    const writes = statements().filter((s) =>
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
});
