import { Stack, Validations, type StackProps } from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import type { IKey } from 'aws-cdk-lib/aws-kms';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as ses from 'aws-cdk-lib/aws-ses';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import * as cr from 'aws-cdk-lib/custom-resources';
import type { Construct } from 'constructs';
import type { EnvConfig } from '../../config/environments.js';

export interface ChannelsStackProps extends StackProps {
  readonly config: EnvConfig;
  readonly key: IKey;
  readonly inboundMailBucket: s3.IBucket;
}

/**
 * Channels (T-20, FN-01): SNS topics fed by AWS End User Messaging Social (WhatsApp) and SES, SES
 * configuration set, and, when `-c sesDomain=<domain>` is given, the SES identity and inbound rule set.
 * SMS/RCS (EUM SMS v2) arrive with T-27. Identifiers that only exist after manual steps (WhatsApp phone
 * number, domain) come from CDK context and are published to SSM, so connecting them needs no code change.
 */
export class ChannelsStack extends Stack {
  readonly waEventsTopic: sns.Topic;
  readonly mailInboundTopic: sns.Topic;
  readonly emailEventsTopic: sns.Topic;
  readonly configurationSet: ses.ConfigurationSet;

  constructor(scope: Construct, id: string, props: ChannelsStackProps) {
    super(scope, id, props);
    const { config, key, inboundMailBucket } = props;
    const prefix = `suppliagent-${config.envName}`;
    const context = (name: string) => this.node.tryGetContext(name) as string | undefined;

    const topic = (logicalId: string, name: string, publisher: string) => {
      const created = new sns.Topic(this, logicalId, {
        topicName: `${prefix}-${name}`,
        masterKey: key,
        enforceSSL: true,
      });
      created.addToResourcePolicy(
        new iam.PolicyStatement({
          principals: [new iam.ServicePrincipal(`${publisher}.amazonaws.com`)],
          actions: ['sns:Publish'],
          resources: [created.topicArn],
          conditions: { StringEquals: { 'aws:SourceAccount': this.account } },
        }),
      );
      return created;
    };
    // The WABA event destination (manual, see README) points at this topic.
    this.waEventsTopic = topic('WaEventsTopic', 'wa-events', 'social-messaging');
    this.mailInboundTopic = topic('MailInboundTopic', 'mail-inbound', 'ses');
    this.emailEventsTopic = topic('EmailEventsTopic', 'email-events', 'ses');

    this.configurationSet = new ses.ConfigurationSet(this, 'ConfigurationSet', {
      configurationSetName: `${prefix}-cs`,
      tlsPolicy: ses.ConfigurationSetTlsPolicy.REQUIRE,
      reputationMetrics: true,
    });
    this.configurationSet.addEventDestination('Events', {
      destination: ses.EventDestination.snsTopic(this.emailEventsTopic),
      events: [
        ses.EmailSendingEvent.SEND,
        ses.EmailSendingEvent.DELIVERY,
        ses.EmailSendingEvent.BOUNCE,
        ses.EmailSendingEvent.COMPLAINT,
        ses.EmailSendingEvent.OPEN,
        ses.EmailSendingEvent.CLICK,
      ],
    });

    const sesDomain = context('sesDomain');
    if (sesDomain) {
      new ses.EmailIdentity(this, 'Identity', {
        identity: ses.Identity.domain(sesDomain),
        configurationSet: this.configurationSet,
      });

      // Raw L1: the L2 S3 action would add grants on the Foundation bucket and key, which Foundation
      // already gives to SES, and make Foundation depend on this stack.
      const ruleSet = new ses.CfnReceiptRuleSet(this, 'ReceiptRuleSet', {
        ruleSetName: `${prefix}-inbound`,
      });
      const rule = new ses.CfnReceiptRule(this, 'InboundRule', {
        ruleSetName: ruleSet.ref,
        rule: {
          name: 'store-and-notify',
          enabled: true,
          scanEnabled: true,
          tlsPolicy: 'Require',
          recipients: [sesDomain],
          actions: [
            {
              s3Action: {
                bucketName: inboundMailBucket.bucketName,
                objectKeyPrefix: 'mail/',
                kmsKeyArn: key.keyArn,
                topicArn: this.mailInboundTopic.topicArn,
              },
            },
          ],
        },
      });
      // Only one rule set is active per region; this account had none on 26/10/2026. On delete the
      // active rule set is cleared (no RuleSetName) before the rule set itself is removed.
      const activation = (parameters: Record<string, string>) => ({
        service: 'SES',
        action: 'setActiveReceiptRuleSet',
        parameters,
        physicalResourceId: cr.PhysicalResourceId.of(`${prefix}-active-rule-set`),
      });
      const activate = new cr.AwsCustomResource(this, 'ActivateRuleSet', {
        onCreate: activation({ RuleSetName: ruleSet.ref }),
        onUpdate: activation({ RuleSetName: ruleSet.ref }),
        onDelete: activation({}),
        policy: cr.AwsCustomResourcePolicy.fromStatements([
          new iam.PolicyStatement({ actions: ['ses:SetActiveReceiptRuleSet'], resources: ['*'] }),
        ]),
        installLatestAwsSdk: false,
      });
      activate.node.addDependency(rule);
      Validations.of(activate).acknowledge({
        id: 'AwsSolutions-IAM5[Resource::*]',
        reason: 'ses:SetActiveReceiptRuleSet does not support resource-level permissions.',
      });
      // Singleton Lambda that CDK creates for AwsCustomResource.
      const provider = this.node.findChild('AWS679f53fac002430cb0da5b7982bd2287');
      Validations.of(provider).acknowledge({
        id: 'AwsSolutions-IAM4[Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole]',
        reason: 'CDK-managed AwsCustomResource provider uses the basic execution role.',
      });
      Validations.of(provider).acknowledge({
        id: 'AwsSolutions-L1',
        reason: 'CDK-managed AwsCustomResource provider runtime is controlled by aws-cdk-lib.',
      });
    }

    const parameter = (name: string, value: string | undefined) =>
      new ssm.StringParameter(this, `Param${name}`, {
        parameterName: `/suppliagent/${config.envName}/${name}`,
        stringValue: value ?? 'UNSET',
      });
    parameter('waPhoneNumberId', context('waPhoneNumberId'));
    parameter('sesDomain', sesDomain);
    parameter('sesFromAddress', sesDomain ? `ordine@${sesDomain}` : undefined);
    parameter('waEventsTopicArn', this.waEventsTopic.topicArn);
    parameter('sesConfigurationSet', this.configurationSet.configurationSetName);
  }
}
