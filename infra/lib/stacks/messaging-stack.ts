import * as path from 'node:path';
import { Duration, Stack, Validations, type StackProps } from 'aws-cdk-lib';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import type { ITableV2 } from 'aws-cdk-lib/aws-dynamodb';
import type { IEventBus } from 'aws-cdk-lib/aws-events';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as kms from 'aws-cdk-lib/aws-kms';
import type { IKey } from 'aws-cdk-lib/aws-kms';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { SqsEventSource } from 'aws-cdk-lib/aws-lambda-event-sources';
import type { IBucket } from 'aws-cdk-lib/aws-s3';
import type { ITopic } from 'aws-cdk-lib/aws-sns';
import { SqsSubscription } from 'aws-cdk-lib/aws-sns-subscriptions';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import type { Construct } from 'constructs';
import type { EnvConfig } from '../../config/environments.js';
import { PythonLambda } from '../constructs/python-lambda.js';
import { REPO_ROOT, uvBundling } from '../constructs/uv-bundling.js';

export interface MessagingStackProps extends StackProps {
  readonly config: EnvConfig;
  readonly key: IKey;
  readonly eventBus: IEventBus;
  readonly inboundMailBucket: IBucket;
  readonly mediaBucket: IBucket;
  readonly inboundTopics: readonly ITopic[];
  readonly tables: {
    readonly channelIdentities: ITableV2;
    readonly contacts: ITableV2;
    readonly salesReps: ITableV2;
    readonly customers: ITableV2;
    readonly conversations: ITableV2;
    readonly messages: ITableV2;
    readonly turnBuffer: ITableV2;
  };
}

/**
 * Ingestion (T-21, FN-01, INFRASTRUCTURE_DESIGN §5.2): channel topics -> SQS `inbound` -> Inbound
 * Router. A standard queue: SES and EUM Social publish to standard SNS topics, which cannot deliver
 * to FIFO queues; per-chat order comes from the AWS receipt timestamp and the debounce (T-22).
 */
export class MessagingStack extends Stack {
  readonly inboundQueue: sqs.Queue;

  constructor(scope: Construct, id: string, props: MessagingStackProps) {
    super(scope, id, props);
    const { config, key, tables } = props;
    const prefix = `suppliagent-${config.envName}`;
    // Imported: SqsSubscription would otherwise add a topic-scoped statement to the Foundation key
    // policy (a Foundation -> Channels cycle). Foundation already lets SNS use the key.
    const queueKey = kms.Key.fromKeyArn(this, 'QueueKey', key.keyArn);
    // Published by ChannelsStack; read at runtime so connecting the WABA needs no redeploy here.
    const phoneNumberParam = `/suppliagent/${config.envName}/waPhoneNumberId`;

    const queue = (name: string, extra: Partial<sqs.QueueProps> = {}) =>
      new sqs.Queue(this, name, {
        queueName: `${prefix}-${name.replace(/([a-z])([A-Z])/g, '$1-$2').toLowerCase()}`,
        encryption: sqs.QueueEncryption.KMS,
        encryptionMasterKey: queueKey,
        enforceSSL: true,
        ...extra,
      });
    const inboundDlq = queue('InboundDlq', { retentionPeriod: Duration.days(14) });
    Validations.of(inboundDlq).acknowledge({
      id: 'AwsSolutions-SQS3',
      reason: 'This is the dead-letter queue of the inbound queue (E-10).',
    });

    const router = new PythonLambda(this, 'InboundRouter', {
      config,
      key,
      name: 'inbound-router',
      code: lambda.Code.fromAsset(
        path.join(REPO_ROOT, 'services/inbound_router'),
        uvBundling({
          package: 'suppliagent-inbound-router',
          sources: {
            'services/shared/src/suppliagent_shared': 'suppliagent_shared',
            'services/inbound_router/src/inbound_router': 'inbound_router',
          },
          // boto3 is bundled on purpose: the runtime's may predate the `socialmessaging` client.
          omit: ['aws-lambda-powertools'],
        }),
      ),
      handler: 'inbound_router.handler.handler',
      timeout: Duration.seconds(60),
      environment: {
        TABLE_PREFIX: `${prefix}-`,
        EVENT_BUS_NAME: props.eventBus.eventBusName,
        INBOUND_MAIL_BUCKET: props.inboundMailBucket.bucketName,
        MEDIA_BUCKET: props.mediaBucket.bucketName,
        WA_PHONE_NUMBER_ID_PARAM: phoneNumberParam,
        // `ordine+<orderId>@` is trusted only on our own domain (same context as ChannelsStack).
        ORDER_DOMAIN: (this.node.tryGetContext('sesDomain') as string | undefined) ?? '',
      },
    });
    this.inboundQueue = queue('Inbound', {
      visibilityTimeout: Duration.seconds(6 * 60), // 6x the router timeout (Lambda guidance)
      deadLetterQueue: { queue: inboundDlq, maxReceiveCount: 3 },
    });
    for (const topic of props.inboundTopics) {
      topic.addSubscription(new SqsSubscription(this.inboundQueue)); // SNS envelope kept
    }
    // Capped: the public number and mailbox must not let spam take the account's concurrency.
    router.function.addEventSource(
      new SqsEventSource(this.inboundQueue, { batchSize: 1, maxConcurrency: 10 }),
    );
    // E-10: visible in CloudWatch; notification target arrives with the dashboards (T-09).
    inboundDlq.metricApproximateNumberOfMessagesVisible().createAlarm(this, 'InboundDlqAlarm', {
      alarmName: `${prefix}-inbound-dlq`,
      threshold: 0,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      evaluationPeriods: 1,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });

    // Explicit statements: only the calls the router makes.
    const allow = (actions: string[], resources: string[]) =>
      router.function.addToRolePolicy(new iam.PolicyStatement({ actions, resources }));
    allow(
      ['dynamodb:GetItem'],
      [tables.channelIdentities, tables.contacts, tables.salesReps].map((t) => t.tableArn),
    );
    allow(['dynamodb:Query'], [`${tables.customers.tableArn}/index/by-repId`]);
    allow(['dynamodb:UpdateItem'], [tables.conversations.tableArn]);
    // Messages + a TTL'd `dedup#<messageId>` guard in TurnBuffer, in one transaction (E-01).
    allow(['dynamodb:PutItem'], [tables.messages.tableArn, tables.turnBuffer.tableArn]);
    allow(['events:PutEvents'], [props.eventBus.eventBusArn]);
    allow(['s3:GetObject'], [props.inboundMailBucket.arnForObjects('mail/*')]);
    allow(['kms:Decrypt', 'kms:GenerateDataKey'], [key.keyArn]);
    // Media (T-23): EUM Social writes to S3 with the caller's permissions (forward access sessions).
    allow(['s3:PutObject'], [props.mediaBucket.arnForObjects('media/*')]);
    router.function.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['s3:ListBucket'],
        resources: [props.mediaBucket.bucketArn],
        conditions: { StringLike: { 's3:prefix': 'media/*' } },
      }),
    );
    allow(
      ['ssm:GetParameter'],
      [
        this.formatArn({
          service: 'ssm',
          resource: 'parameter',
          resourceName: phoneNumberParam.slice(1),
        }),
      ],
    );
    allow(
      ['social-messaging:GetWhatsAppMessageMedia'],
      [
        this.formatArn({
          service: 'social-messaging',
          resource: 'phone-number-id',
          resourceName: '*',
        }),
      ],
    );
    Validations.of(router).acknowledge({
      id: `AwsSolutions-IAM5[Resource::${prefix}-foundation:ExportsOutputFnGetAttInboundMailBucket420E1CDEArn451947A0/mail/*]`,
      reason: 'SES stores each inbound mail as mail/<messageId>; read-only.',
    });
    Validations.of(router).acknowledge({
      id: `AwsSolutions-IAM5[Resource::${prefix}-foundation:ExportsOutputFnGetAttMediaBucketBCBB02BAArnB94B784B/media/*]`,
      reason: 'One object per inbound media under media/<owner>/<messageId>/; write-only.',
    });
    Validations.of(router).acknowledge({
      id: `AwsSolutions-IAM5[Resource::arn:aws:social-messaging:${config.region}:<AWS::AccountId>:phone-number-id/*]`,
      reason:
        'The phone number id is set after deploy (SSM, manual WABA step); media download only, this account.',
    });
  }
}
