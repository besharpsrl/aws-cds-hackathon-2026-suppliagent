import { App } from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { describe, expect, it } from 'vitest';
import { type EnvConfig, getConfig } from '../config/environments.js';
import { buildApp } from '../lib/app.js';
import { context } from './context.js';

const channels = (extraContext: Record<string, string> = {}, config: Partial<EnvConfig> = {}) => {
  const app = new App({ context: { ...context, ...extraContext } });
  const stacks = buildApp(app, { ...getConfig('dev'), ...config });
  return { app, stacks, template: Template.fromStack(stacks.channels) };
};

const ssm = (template: Template, name: string) =>
  Object.values(template.findResources('AWS::SSM::Parameter')).find(
    (r) => r.Properties.Name === `/suppliagent/dev/${name}`,
  )?.Properties.Value;
const noChannels = { sesDomain: undefined, waPhoneNumberId: undefined };

describe('ChannelsStack (T-20, FN-01)', () => {
  it('creates encrypted SNS topics for WhatsApp events, inbound mail and email events', () => {
    const { template } = channels();
    for (const name of ['wa-events', 'mail-inbound', 'email-events']) {
      template.hasResourceProperties('AWS::SNS::Topic', {
        TopicName: `suppliagent-dev-${name}`,
        KmsMasterKeyId: Match.anyValue(),
      });
    }
  });

  it('lets only EUM Social, from this account, publish on the WhatsApp topic', () => {
    const { template } = channels();
    template.hasResourceProperties('AWS::SNS::TopicPolicy', {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: 'sns:Publish',
            Effect: 'Allow',
            Principal: { Service: 'social-messaging.amazonaws.com' },
            Condition: { StringEquals: { 'aws:SourceAccount': Match.anyValue() } },
          }),
        ]),
      },
    });
  });

  it('creates the SES configuration set with TLS required and an SNS event destination', () => {
    const { template } = channels();
    template.hasResourceProperties('AWS::SES::ConfigurationSet', {
      Name: 'suppliagent-dev-cs',
      DeliveryOptions: { TlsPolicy: 'REQUIRE' },
    });
    template.hasResourceProperties('AWS::SES::ConfigurationSetEventDestination', {
      EventDestination: Match.objectLike({
        Enabled: true,
        MatchingEventTypes: Match.arrayWith(['send', 'delivery', 'bounce', 'complaint']),
        SnsDestination: Match.objectLike({}),
      }),
    });
  });

  it('without sesDomain creates no identity nor receipt rules, and publishes UNSET parameters', () => {
    const { template } = channels({}, noChannels);
    template.resourceCountIs('AWS::SES::EmailIdentity', 0);
    template.resourceCountIs('AWS::SES::ReceiptRuleSet', 0);
    template.resourceCountIs('AWS::SES::ReceiptRule', 0);
    for (const name of ['waPhoneNumberId', 'sesDomain', 'sesFromAddress']) {
      expect(ssm(template, name)).toBe('UNSET');
    }
  });

  describe('values from the environment config, without -c (T-15)', () => {
    const { template } = channels();

    it('keeps SES identity, receipt rules and SSM parameters on dev', () => {
      template.resourceCountIs('AWS::SES::EmailIdentity', 1);
      template.resourceCountIs('AWS::SES::ReceiptRuleSet', 1);
      template.resourceCountIs('AWS::SES::ReceiptRule', 1);
      expect(ssm(template, 'sesDomain')).toBe('suppliagent.stonecutters.besharp.net');
      expect(ssm(template, 'sesFromAddress')).toBe('ordine@suppliagent.stonecutters.besharp.net');
    });

    it('lets -c override the config', () => {
      const { template: overridden } = channels({ sesDomain: 'ordini.example.com' });
      expect(ssm(overridden, 'sesDomain')).toBe('ordini.example.com');
    });
  });

  it('publishes the WhatsApp phone number id from context, with no code change', () => {
    const { template } = channels({ waPhoneNumberId: 'phone-number-id-123' });
    expect(ssm(template, 'waPhoneNumberId')).toBe('phone-number-id-123');
  });

  describe('with sesDomain', () => {
    const domain = 'ordini.example.com';
    const { template } = channels({ sesDomain: domain });

    it('creates the Easy DKIM identity bound to the configuration set', () => {
      template.hasResourceProperties('AWS::SES::EmailIdentity', {
        EmailIdentity: domain,
        ConfigurationSetAttributes: { ConfigurationSetName: Match.anyValue() },
      });
    });

    it('stores inbound mail in S3 (bucket SSE-KMS, not SES client-side) and notifies SNS', () => {
      template.hasResourceProperties('AWS::SES::ReceiptRule', {
        Rule: Match.objectLike({
          Enabled: true,
          Recipients: [domain],
          ScanEnabled: true,
          Actions: [
            Match.objectLike({
              S3Action: Match.objectLike({
                ObjectKeyPrefix: 'mail/',
                KmsKeyArn: Match.absent(),
                TopicArn: Match.anyValue(),
              }),
            }),
          ],
        }),
      });
      const activate = Object.values(template.findResources('Custom::AWS')).find((r) =>
        JSON.stringify(r.Properties.Create).includes('setActiveReceiptRuleSet'),
      )!;
      for (const call of ['Create', 'Delete']) {
        expect(JSON.stringify(activate.Properties[call])).toContain('setActiveReceiptRuleSet');
      }
      expect(ssm(template, 'sesDomain')).toBe(domain);
      expect(ssm(template, 'sesFromAddress')).toBe(`ordine@${domain}`);
    });
  });

  it('synthesizes with no cdk-nag errors, with and without sesDomain', () => {
    expect(() => channels().app.synth()).not.toThrow();
    expect(() => channels({}, noChannels).app.synth()).not.toThrow();
    expect(() =>
      channels({ sesDomain: 'ordini.example.com' }, noChannels).app.synth(),
    ).not.toThrow();
  });
});

describe('FoundationStack grants for the channels (T-20)', () => {
  const foundation = () => {
    const app = new App({ context });
    return Template.fromStack(buildApp(app, getConfig('dev')).foundation);
  };

  it.each(['ses', 'social-messaging', 'sns'])(
    'lets %s.amazonaws.com use the CMK, from this account only',
    (service) => {
      foundation().hasResourceProperties('AWS::KMS::Key', {
        KeyPolicy: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Principal: { Service: Match.arrayWith([`${service}.amazonaws.com`]) },
              Action: Match.arrayWith(['kms:GenerateDataKey*']),
              Condition: { StringEquals: { 'aws:SourceAccount': Match.anyValue() } },
            }),
          ]),
        },
      });
    },
  );

  it('lets SES write inbound mail to the inbound-mail bucket, from this account only', () => {
    foundation().hasResourceProperties('AWS::S3::BucketPolicy', {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: 's3:PutObject',
            Principal: { Service: 'ses.amazonaws.com' },
            Condition: { StringEquals: { 'aws:SourceAccount': Match.anyValue() } },
          }),
        ]),
      },
    });
  });
});
