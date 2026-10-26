import { fileURLToPath } from 'node:url';
import { Duration, Stack, Validations, type StackProps } from 'aws-cdk-lib';
import type { ITableV2 } from 'aws-cdk-lib/aws-dynamodb';
import type { IEventBus } from 'aws-cdk-lib/aws-events';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as kms from 'aws-cdk-lib/aws-kms';
import type { IKey } from 'aws-cdk-lib/aws-kms';
import { SqsEventSource } from 'aws-cdk-lib/aws-lambda-event-sources';
import type { IBucket } from 'aws-cdk-lib/aws-s3';
import type { ITopic } from 'aws-cdk-lib/aws-sns';
import { SqsSubscription } from 'aws-cdk-lib/aws-sns-subscriptions';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import type { Construct } from 'constructs';
import type { EnvConfig } from '../../config/environments.js';
import { PythonLambda, pythonCode } from '../constructs/python-lambda.js';

export interface MessagingStackProps extends StackProps {
  readonly config: EnvConfig;
  readonly key: IKey;
  readonly eventBus: IEventBus;
  readonly inboundMailBucket: IBucket;
  readonly inboundTopics: readonly ITopic[];
  readonly tables: {
    readonly channelIdentities: ITableV2;
    readonly contacts: ITableV2;
    readonly salesReps: ITableV2;
    readonly customers: ITableV2;
    readonly conversations: ITableV2;
    readonly messages: ITableV2;
  };
}

const routerCode = fileURLToPath(new URL('../../../services/inbound_router/src', import.meta.url));

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
      code: pythonCode(routerCode),
      handler: 'inbound_router.handler.handler',
      timeout: Duration.seconds(60),
      environment: {
        TABLE_PREFIX: `${prefix}-`,
        EVENT_BUS_NAME: props.eventBus.eventBusName,
        INBOUND_MAIL_BUCKET: props.inboundMailBucket.bucketName,
      },
    });
    this.inboundQueue = queue('Inbound', {
      visibilityTimeout: Duration.seconds(6 * 60), // 6x the router timeout (Lambda guidance)
      deadLetterQueue: { queue: inboundDlq, maxReceiveCount: 3 },
    });
    for (const topic of props.inboundTopics) {
      topic.addSubscription(new SqsSubscription(this.inboundQueue)); // SNS envelope kept
    }
    router.function.addEventSource(new SqsEventSource(this.inboundQueue, { batchSize: 1 }));

    // Explicit statements: only the calls the router makes.
    const allow = (actions: string[], resources: string[]) =>
      router.function.addToRolePolicy(new iam.PolicyStatement({ actions, resources }));
    allow(
      ['dynamodb:GetItem'],
      [tables.channelIdentities, tables.contacts, tables.salesReps].map((t) => t.tableArn),
    );
    allow(['dynamodb:Query'], [`${tables.customers.tableArn}/index/by-repId`]);
    allow(['dynamodb:UpdateItem'], [tables.conversations.tableArn]);
    allow(['dynamodb:PutItem'], [tables.messages.tableArn]);
    allow(['events:PutEvents'], [props.eventBus.eventBusArn]);
    allow(['s3:GetObject'], [props.inboundMailBucket.arnForObjects('mail/*')]);
    allow(['kms:Decrypt', 'kms:GenerateDataKey'], [key.keyArn]);
    Validations.of(router).acknowledge({
      id: `AwsSolutions-IAM5[Resource::${prefix}-foundation:ExportsOutputFnGetAttInboundMailBucket420E1CDEArn451947A0/mail/*]`,
      reason: 'SES stores each inbound mail as mail/<messageId>; read-only.',
    });
  }
}
