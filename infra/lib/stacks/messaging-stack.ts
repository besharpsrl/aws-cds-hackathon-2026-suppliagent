import * as path from 'node:path';
import { ArnFormat, Duration, Stack, Validations, type StackProps } from 'aws-cdk-lib';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import type { ITableV2 } from 'aws-cdk-lib/aws-dynamodb';
import * as events from 'aws-cdk-lib/aws-events';
import type { IEventBus } from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as kms from 'aws-cdk-lib/aws-kms';
import type { IKey } from 'aws-cdk-lib/aws-kms';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { SqsEventSource } from 'aws-cdk-lib/aws-lambda-event-sources';
import type { IBucket } from 'aws-cdk-lib/aws-s3';
import type { ITopic } from 'aws-cdk-lib/aws-sns';
import { LambdaSubscription, SqsSubscription } from 'aws-cdk-lib/aws-sns-subscriptions';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import type { Construct } from 'constructs';
import { channelValue, type EnvConfig } from '../../config/environments.js';
import { PythonLambda } from '../constructs/python-lambda.js';
import { REPO_ROOT, uvBundling } from '../constructs/uv-bundling.js';

export interface MessagingStackProps extends StackProps {
  readonly config: EnvConfig;
  readonly key: IKey;
  readonly eventBus: IEventBus;
  readonly inboundMailBucket: IBucket;
  readonly mediaBucket: IBucket;
  /** Order PDFs go to `orders/` here (T-07). */
  readonly documentsBucket: IBucket;
  readonly inboundTopics: readonly ITopic[];
  /** SES configuration set events: the Notifier handles bounces of confirmation emails (T-26). */
  readonly emailEventsTopic: ITopic;
  /** The agent Runtime the Dispatcher invokes (AgentStack). */
  readonly agentRuntimeArn: string;
  readonly tables: {
    readonly channelIdentities: ITableV2;
    readonly contacts: ITableV2;
    readonly salesReps: ITableV2;
    readonly customers: ITableV2;
    readonly conversations: ITableV2;
    readonly messages: ITableV2;
    readonly turnBuffer: ITableV2;
    readonly orders: ITableV2;
    readonly deliveries: ITableV2;
  };
}

/**
 * Ingestion (T-21, FN-01, INFRASTRUCTURE_DESIGN §5.2): channel topics -> SQS `inbound` -> Inbound
 * Router. A standard queue: SES and EUM Social publish to standard SNS topics, which cannot deliver
 * to FIFO queues; per-chat order comes from the AWS receipt timestamp and the debounce.
 * Debounce (T-22, FN-26): Router -> TurnBuffer + SQS `turn-flush` (delay) -> Turn Dispatcher
 * (lock, one agent turn per burst) -> Notifier (T-24 base, the only sender).
 * Orders (T-07, FN-13/14): EventBridge `order.confirmed` -> ERP adapter (mock) and Order PDF;
 * `order.pdf_ready` -> Notifier, the confirmation email with the PDF (T-26).
 */
export class MessagingStack extends Stack {
  readonly inboundQueue: sqs.Queue;
  readonly turnFlushQueue: sqs.Queue;

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

    const turnFlushDlq = queue('TurnFlushDlq', { retentionPeriod: Duration.days(14) });
    Validations.of(turnFlushDlq).acknowledge({
      id: 'AwsSolutions-SQS3',
      reason: 'This is the dead-letter queue of the turn-flush queue (E-10).',
    });
    // The flush carries only a conversation id; it is a nudge, never the data of the turn.
    this.turnFlushQueue = queue('TurnFlush', {
      // The Dispatcher runs a whole agent turn (<= 115 s): a failed flush is retried after this.
      visibilityTimeout: Duration.seconds(120),
      deadLetterQueue: { queue: turnFlushDlq, maxReceiveCount: 3 },
    });
    const notifierName = `${prefix}-notifier`;
    const debounce = {
      DEBOUNCE_TEXT_MS: config.parameters.debounceTextMs,
      DEBOUNCE_MEDIA_MS: config.parameters.debounceMediaMs,
    };

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
        SANDBOX_PARAM: `/suppliagent/${config.envName}/notifierSandbox`,
        // `ordine+<orderId>@` is trusted only on our own domain (same value as ChannelsStack).
        ORDER_DOMAIN: channelValue(this.node, props.config, 'sesDomain') ?? '',
        TURN_FLUSH_QUEUE_URL: this.turnFlushQueue.queueUrl,
        NOTIFIER_FUNCTION_NAME: notifierName,
        ...debounce,
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

    turnFlushDlq.metricApproximateNumberOfMessagesVisible().createAlarm(this, 'TurnFlushDlqAlarm', {
      alarmName: `${prefix}-turn-flush-dlq`,
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
    // The TurnBuffer update is part of the message transaction (T-22).
    allow(['dynamodb:UpdateItem'], [tables.conversations.tableArn, tables.turnBuffer.tableArn]);
    // Messages + a TTL'd `dedup#<messageId>` guard in TurnBuffer, in one transaction (E-01).
    allow(['dynamodb:PutItem'], [tables.messages.tableArn, tables.turnBuffer.tableArn]);
    allow(['sqs:SendMessage'], [this.turnFlushQueue.queueArn]);
    allow(
      ['lambda:InvokeFunction'],
      [
        this.formatArn({
          service: 'lambda',
          resource: 'function',
          resourceName: notifierName,
          arnFormat: ArnFormat.COLON_RESOURCE_NAME,
        }),
      ],
    );
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
    // Simulated media (T-14): copied from `sim/` to `media/`, only while `notifierSandbox` is true.
    allow(['s3:GetObject'], [props.mediaBucket.arnForObjects('sim/*')]);
    router.function.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['s3:ListBucket'],
        resources: [props.mediaBucket.bucketArn],
        conditions: { StringLike: { 's3:prefix': 'sim/*' } },
      }),
    );
    allow(
      ['ssm:GetParameter'],
      [phoneNumberParam, `/suppliagent/${config.envName}/notifierSandbox`].map((name) =>
        this.formatArn({ service: 'ssm', resource: 'parameter', resourceName: name.slice(1) }),
      ),
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
    const notifier = this.addNotifier(props, phoneNumberParam);
    this.addDispatcher(props, notifierName, debounce);
    this.addOrderPipeline(props, notifier);
    this.addOrderSweeper(props, notifierName);

    Validations.of(router).acknowledge({
      id: `AwsSolutions-IAM5[Resource::${prefix}-foundation:ExportsOutputFnGetAttInboundMailBucket420E1CDEArn451947A0/mail/*]`,
      reason: 'SES stores each inbound mail as mail/<messageId>; read-only.',
    });
    Validations.of(router).acknowledge({
      id: `AwsSolutions-IAM5[Resource::${prefix}-foundation:ExportsOutputFnGetAttMediaBucketBCBB02BAArnB94B784B/media/*]`,
      reason: 'One object per inbound media under media/<owner>/<messageId>/; write-only.',
    });
    Validations.of(router).acknowledge({
      id: `AwsSolutions-IAM5[Resource::${prefix}-foundation:ExportsOutputFnGetAttMediaBucketBCBB02BAArnB94B784B/sim/*]`,
      reason:
        'Files uploaded by scripts/simulate_channel.py under sim/<mediaId>/; read-only, and used only while notifierSandbox is true (T-14).',
    });
    Validations.of(router).acknowledge({
      id: `AwsSolutions-IAM5[Resource::arn:aws:social-messaging:${config.region}:<AWS::AccountId>:phone-number-id/*]`,
      reason:
        'The phone number id is set after deploy (SSM, manual WABA step); media download only, this account.',
    });
  }

  /** Notifier (T-24 base): the only function allowed to call the CDS send APIs (AGENTS §8.7). */
  private addNotifier(props: MessagingStackProps, phoneNumberParam: string): lambda.IFunction {
    const { config, key, tables } = props;
    const prefix = `suppliagent-${config.envName}`;
    const param = (n: string) => `/suppliagent/${config.envName}/${n}`;
    const paramArn = (parameter: string) =>
      this.formatArn({ service: 'ssm', resource: 'parameter', resourceName: parameter.slice(1) });
    const sesDomain = channelValue(this.node, config, 'sesDomain') ?? '*';
    const notifier = new PythonLambda(this, 'Notifier', {
      config,
      key,
      name: 'notifier',
      code: lambda.Code.fromAsset(
        path.join(REPO_ROOT, 'services/notifier'),
        uvBundling({
          package: 'suppliagent-notifier',
          sources: {
            'services/shared/src/suppliagent_shared': 'suppliagent_shared',
            'services/notifier/src/notifier': 'notifier',
          },
          // boto3 is bundled on purpose: the runtime's may predate the `socialmessaging` client.
          omit: ['aws-lambda-powertools'],
        }),
      ),
      handler: 'notifier.handler.handler',
      timeout: Duration.seconds(30),
      environment: {
        TABLE_PREFIX: `${prefix}-`,
        EVENT_BUS_NAME: props.eventBus.eventBusName,
        WA_PHONE_NUMBER_ID_PARAM: phoneNumberParam,
        SES_FROM_PARAM: param('sesFromAddress'),
        SES_CONFIGURATION_SET_PARAM: param('sesConfigurationSet'),
        SANDBOX_PARAM: param('notifierSandbox'),
        DOCUMENTS_BUCKET: props.documentsBucket.bucketName,
      },
    });
    const allow = (actions: string[], resources: string[]) =>
      notifier.function.addToRolePolicy(new iam.PolicyStatement({ actions, resources }));
    allow(['dynamodb:GetItem'], [tables.conversations.tableArn]);
    // Order confirmation email (T-26): the order, its venue, the recipient's address and language.
    allow(
      ['dynamodb:GetItem'],
      [tables.orders, tables.customers, tables.contacts, tables.salesReps].map((t) => t.tableArn),
    );
    allow(['dynamodb:Query'], [`${tables.channelIdentities.tableArn}/index/by-contactId`]);
    // A hard bounce clears the contact's orderEmail (F-11.C7).
    allow(['dynamodb:UpdateItem'], [tables.contacts.tableArn]);
    allow(['s3:GetObject'], [props.documentsBucket.arnForObjects('orders/*')]);
    // Only bounces: deliveries, opens and clicks stay metrics on the topic.
    props.emailEventsTopic.addSubscription(
      new LambdaSubscription(notifier.function, {
        filterPolicyWithMessageBody: {
          eventType: sns.FilterOrPolicy.filter(
            sns.SubscriptionFilter.stringFilter({ allowlist: ['Bounce'] }),
          ),
        },
      }),
    );
    allow(['dynamodb:Query'], [`${tables.messages.tableArn}/index/by-providerMessageId`]);
    allow(['dynamodb:PutItem'], [tables.messages.tableArn]);
    // T-25: `summaryMessageId` of the order whose summary went out with the Confirm button.
    allow(['dynamodb:UpdateItem'], [tables.orders.tableArn]);
    // Idempotency claims live in the TurnBuffer table, under `dedup#out#<key>`.
    allow(
      ['dynamodb:PutItem', 'dynamodb:UpdateItem', 'dynamodb:DeleteItem'],
      [tables.turnBuffer.tableArn],
    );
    allow(['events:PutEvents'], [props.eventBus.eventBusArn]);
    allow(
      ['ssm:GetParameter'],
      [
        phoneNumberParam,
        param('sesFromAddress'),
        param('sesConfigurationSet'),
        param('notifierSandbox'),
      ].map(paramArn),
    );
    allow(['kms:Decrypt', 'kms:GenerateDataKey'], [key.keyArn]);
    // Sending: the only place with these permissions.
    allow(
      ['social-messaging:SendWhatsAppMessage'],
      [
        this.formatArn({
          service: 'social-messaging',
          resource: 'phone-number-id',
          resourceName: '*',
        }),
      ],
    );
    allow(
      ['ses:SendEmail'],
      [
        this.formatArn({ service: 'ses', resource: 'identity', resourceName: sesDomain }),
        this.formatArn({
          service: 'ses',
          resource: 'configuration-set',
          resourceName: `${prefix}-cs`,
        }),
      ],
    );
    Validations.of(notifier).acknowledge({
      id: `AwsSolutions-IAM5[Resource::arn:aws:ses:${config.region}:<AWS::AccountId>:identity/*]`,
      reason:
        'Without a configured sesDomain the identity is not known; with the domain it is exact.',
    });
    Validations.of(notifier).acknowledge({
      id: `AwsSolutions-IAM5[Resource::arn:aws:social-messaging:${config.region}:<AWS::AccountId>:phone-number-id/*]`,
      reason:
        'The phone number id is set after deploy (SSM, manual WABA step); send only, this account.',
    });
    Validations.of(notifier).acknowledge({
      id: `AwsSolutions-IAM5[Resource::${prefix}-foundation:ExportsOutputFnGetAttDocumentsBucket9EC9DEB9ArnEA5095A7/orders/*]`,
      reason: 'Reads the order PDF documents/orders/<orderId>.pdf to attach it; read-only.',
    });
    return notifier.function;
  }

  /** ERP adapter (mock) and Order PDF, both fed by `order.confirmed` (T-07, FN-13, FN-14). */
  private addOrderPipeline(props: MessagingStackProps, notifier: lambda.IFunction): void {
    const { config, key, tables } = props;
    const prefix = `suppliagent-${config.envName}`;
    const failureParam = `/suppliagent/${config.envName}/erpMockFailure`;
    const common = { TABLE_PREFIX: `${prefix}-`, EVENT_BUS_NAME: props.eventBus.eventBusName };

    const erp = new PythonLambda(this, 'ErpAdapter', {
      config,
      key,
      name: 'erp-adapter',
      code: lambda.Code.fromAsset(
        path.join(REPO_ROOT, 'services/erp_adapter'),
        uvBundling({
          package: 'suppliagent-erp-adapter',
          sources: {
            'services/shared/src/suppliagent_shared': 'suppliagent_shared',
            'services/erp_adapter/src/erp_adapter': 'erp_adapter',
          },
          omit: ['boto3', 'botocore', 's3transfer', 'aws-lambda-powertools'],
        }),
      ),
      handler: 'erp_adapter.handler.handler',
      environment: { ...common, ERP_FAILURE_PARAM: failureParam },
      withDlq: true, // E-08: after the retries below the event waits here for a redrive
    });
    // ponytail: Lambda's own async retries (about 3 min in all); a longer ERP outage ends in the
    // DLQ and the alarm, to be redriven by hand. A scheduled sweep of CONFIRMED orders if needed.
    erp.function.configureAsyncInvoke({ retryAttempts: 2, maxEventAge: Duration.hours(1) });
    const allowErp = (actions: string[], resources: string[]) =>
      erp.function.addToRolePolicy(new iam.PolicyStatement({ actions, resources }));
    allowErp(['dynamodb:GetItem', 'dynamodb:UpdateItem'], [tables.orders.tableArn]);
    allowErp(['dynamodb:PutItem'], [tables.deliveries.tableArn]);
    allowErp(['events:PutEvents'], [props.eventBus.eventBusArn]);
    allowErp(
      ['ssm:GetParameter'],
      [
        this.formatArn({
          service: 'ssm',
          resource: 'parameter',
          resourceName: failureParam.slice(1),
        }),
      ],
    );
    allowErp(['kms:Decrypt', 'kms:GenerateDataKey'], [key.keyArn]);

    const pdf = new PythonLambda(this, 'OrderPdf', {
      config,
      key,
      name: 'order-pdf',
      code: lambda.Code.fromAsset(
        path.join(REPO_ROOT, 'services/order_pdf'),
        uvBundling({
          package: 'suppliagent-order-pdf',
          sources: {
            'services/shared/src/suppliagent_shared': 'suppliagent_shared',
            'services/order_pdf/src/order_pdf': 'order_pdf',
          },
          omit: ['boto3', 'botocore', 's3transfer', 'aws-lambda-powertools'],
        }),
      ),
      handler: 'order_pdf.handler.handler',
      environment: { ...common, DOCUMENTS_BUCKET: props.documentsBucket.bucketName },
      withDlq: true,
    });
    const allowPdf = (actions: string[], resources: string[]) =>
      pdf.function.addToRolePolicy(new iam.PolicyStatement({ actions, resources }));
    allowPdf(['dynamodb:GetItem'], [tables.orders.tableArn]);
    allowPdf(['s3:PutObject'], [props.documentsBucket.arnForObjects('orders/*')]);
    allowPdf(['kms:Decrypt', 'kms:GenerateDataKey'], [key.keyArn]);
    allowPdf(['events:PutEvents'], [props.eventBus.eventBusArn]);

    new events.Rule(this, 'OrderConfirmedRule', {
      ruleName: `${prefix}-order-confirmed`,
      eventBus: props.eventBus,
      eventPattern: { detailType: ['order.confirmed'] },
      targets: [new targets.LambdaFunction(erp.function), new targets.LambdaFunction(pdf.function)],
    });
    // F-08.C2: a confirmed order changed before the cut-off is resubmitted and its PDF rewritten.
    new events.Rule(this, 'OrderUpdatedRule', {
      ruleName: `${prefix}-order-updated`,
      eventBus: props.eventBus,
      eventPattern: { detailType: ['order.updated'] },
      targets: [new targets.LambdaFunction(erp.function), new targets.LambdaFunction(pdf.function)],
    });

    // T-26: the confirmation email waits for the PDF it attaches (also after a change, F-08.C2).
    new events.Rule(this, 'OrderPdfReadyRule', {
      ruleName: `${prefix}-order-pdf-ready`,
      eventBus: props.eventBus,
      eventPattern: { source: ['suppliagent.order-pdf'], detailType: ['order.pdf_ready'] },
      targets: [new targets.LambdaFunction(notifier)],
    });

    // E-08: errors and parked events are visible; the notification target arrives with T-09.
    const alarm = (id: string, name: string, metric: cloudwatch.Metric) =>
      metric.createAlarm(this, id, {
        alarmName: `${prefix}-${name}`,
        threshold: 0,
        comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        evaluationPeriods: 1,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      });
    alarm('ErpErrorsAlarm', 'erp-adapter-errors', erp.function.metricErrors());
    alarm(
      'ErpDlqAlarm',
      'erp-adapter-dlq',
      erp.deadLetterQueue!.metricApproximateNumberOfMessagesVisible(),
    );
    alarm(
      'OrderPdfDlqAlarm',
      'order-pdf-dlq',
      pdf.deadLetterQueue!.metricApproximateNumberOfMessagesVisible(),
    );
    Validations.of(pdf).acknowledge({
      id: `AwsSolutions-IAM5[Resource::${prefix}-foundation:ExportsOutputFnGetAttDocumentsBucket9EC9DEB9ArnEA5095A7/orders/*]`,
      reason: 'One PDF per order under documents/orders/<orderId>.pdf; write-only.',
    });
  }

  /**
   * Order sweeper (T-47, FN-12): reminder after `pendingReminderHours` and expiry at the end of the
   * day for summaries nobody confirmed. Every 15 minutes; silent during the quiet hours.
   */
  private addOrderSweeper(props: MessagingStackProps, notifierName: string): void {
    const { config, key, tables } = props;
    const prefix = `suppliagent-${config.envName}`;
    const sweeper = new PythonLambda(this, 'OrderSweeper', {
      config,
      key,
      name: 'order-sweeper',
      code: lambda.Code.fromAsset(
        path.join(REPO_ROOT, 'services/order_sweeper'),
        uvBundling({
          package: 'suppliagent-order-sweeper',
          sources: {
            'services/shared/src/suppliagent_shared': 'suppliagent_shared',
            'services/order_sweeper/src/order_sweeper': 'order_sweeper',
          },
          omit: ['boto3', 'botocore', 's3transfer', 'aws-lambda-powertools'],
        }),
      ),
      handler: 'order_sweeper.handler.handler',
      timeout: Duration.minutes(2),
      environment: {
        TABLE_PREFIX: `${prefix}-`,
        EVENT_BUS_NAME: props.eventBus.eventBusName,
        NOTIFIER_FUNCTION_NAME: notifierName,
        PENDING_REMINDER_HOURS: config.parameters.pendingReminderHours,
        QUIET_HOURS: config.parameters.quietHours,
      },
    });
    const allow = (actions: string[], resources: string[]) =>
      sweeper.function.addToRolePolicy(new iam.PolicyStatement({ actions, resources }));
    allow(['dynamodb:Query'], [`${tables.orders.tableArn}/index/by-status`]);
    allow(['dynamodb:UpdateItem'], [tables.orders.tableArn]);
    allow(['dynamodb:GetItem'], [tables.conversations.tableArn]);
    allow(['events:PutEvents'], [props.eventBus.eventBusArn]);
    allow(['kms:Decrypt', 'kms:GenerateDataKey'], [key.keyArn]);
    allow(
      ['lambda:InvokeFunction'],
      [
        this.formatArn({
          service: 'lambda',
          resource: 'function',
          resourceName: notifierName,
          arnFormat: ArnFormat.COLON_RESOURCE_NAME,
        }),
      ],
    );
    // Schedules run on the default bus, not on the application bus.
    new events.Rule(this, 'OrderSweeperSchedule', {
      ruleName: `${prefix}-order-sweeper`,
      schedule: events.Schedule.rate(Duration.minutes(15)),
      targets: [new targets.LambdaFunction(sweeper.function)],
    });
    sweeper.function.metricErrors().createAlarm(this, 'OrderSweeperErrorsAlarm', {
      alarmName: `${prefix}-order-sweeper-errors`,
      threshold: 0,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      evaluationPeriods: 1,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });
  }

  /** Turn Dispatcher (T-22, FN-26): debounce, lock per conversation, one agent turn per burst. */
  private addDispatcher(
    props: MessagingStackProps,
    notifierName: string,
    debounce: Record<string, string>,
  ): void {
    const { config, key, tables } = props;
    const prefix = `suppliagent-${config.envName}`;
    const dispatcher = new PythonLambda(this, 'TurnDispatcher', {
      config,
      key,
      name: 'turn-dispatcher',
      code: lambda.Code.fromAsset(
        path.join(REPO_ROOT, 'services/turn_dispatcher'),
        uvBundling({
          package: 'suppliagent-turn-dispatcher',
          sources: {
            'services/shared/src/suppliagent_shared': 'suppliagent_shared',
            'services/turn_dispatcher/src/turn_dispatcher': 'turn_dispatcher',
          },
          // boto3 is bundled on purpose: the runtime's may predate the `bedrock-agentcore` client.
          omit: ['aws-lambda-powertools'],
        }),
      ),
      handler: 'turn_dispatcher.handler.handler',
      // Below `turnLockTtlMs` (120 s): a turn must end before another one can take the lock.
      timeout: Duration.seconds(115),
      environment: {
        TABLE_PREFIX: `${prefix}-`,
        EVENT_BUS_NAME: props.eventBus.eventBusName,
        TURN_FLUSH_QUEUE_URL: this.turnFlushQueue.queueUrl,
        AGENT_RUNTIME_ARN: props.agentRuntimeArn,
        NOTIFIER_FUNCTION_NAME: notifierName,
        DEBOUNCE_MAX_MS: config.parameters.debounceMaxMs,
        TURN_LOCK_TTL_MS: config.parameters.turnLockTtlMs,
        TURN_MAX_MESSAGES: config.parameters.turnMaxMessages,
        ...debounce,
      },
    });
    dispatcher.function.addEventSource(
      new SqsEventSource(this.turnFlushQueue, { batchSize: 1, maxConcurrency: 10 }),
    );
    const allow = (actions: string[], resources: string[]) =>
      dispatcher.function.addToRolePolicy(new iam.PolicyStatement({ actions, resources }));
    allow(['dynamodb:GetItem', 'dynamodb:UpdateItem'], [tables.turnBuffer.tableArn]);
    // GetItem: the mode; UpdateItem: the handoff after a second failed turn (T-67, E-12).
    allow(['dynamodb:GetItem', 'dynamodb:UpdateItem'], [tables.conversations.tableArn]);
    allow(['sqs:SendMessage'], [this.turnFlushQueue.queueArn]);
    allow(['events:PutEvents'], [props.eventBus.eventBusArn]);
    allow(['kms:Decrypt', 'kms:GenerateDataKey'], [key.keyArn]);
    // Only the agent of this environment, nothing else of AgentCore (INFRASTRUCTURE_DESIGN §5.3.2).
    allow(
      ['bedrock-agentcore:InvokeAgentRuntime'],
      [props.agentRuntimeArn, `${props.agentRuntimeArn}/runtime-endpoint/*`],
    );
    allow(
      ['lambda:InvokeFunction'],
      [
        this.formatArn({
          service: 'lambda',
          resource: 'function',
          resourceName: notifierName,
          arnFormat: ArnFormat.COLON_RESOURCE_NAME,
        }),
      ],
    );
    Validations.of(dispatcher).acknowledge({
      id: `AwsSolutions-IAM5[Resource::${prefix}-agent:ExportsOutputFnGetAttRuntime99E3DDFAAgentRuntimeArn83DF9A4C/runtime-endpoint/*]`,
      reason: 'The endpoints of this one Runtime (DEFAULT today); invoke only.',
    });
  }
}
