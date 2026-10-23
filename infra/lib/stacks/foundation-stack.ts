import { Duration, RemovalPolicy, Stack, Validations, type StackProps } from 'aws-cdk-lib';
import * as budgets from 'aws-cdk-lib/aws-budgets';
import * as events from 'aws-cdk-lib/aws-events';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as kms from 'aws-cdk-lib/aws-kms';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import type { Construct } from 'constructs';
import type { EnvConfig } from '../../config/environments.js';

export interface FoundationStackProps extends StackProps {
  readonly config: EnvConfig;
}

export class FoundationStack extends Stack {
  readonly key: kms.Key;
  readonly eventBus: events.EventBus;
  readonly mediaBucket: s3.Bucket;
  readonly inboundMailBucket: s3.Bucket;
  readonly documentsBucket: s3.Bucket;
  readonly catalogAssetsBucket: s3.Bucket;
  readonly analyticsBucket: s3.Bucket;

  constructor(scope: Construct, id: string, props: FoundationStackProps) {
    super(scope, id, props);
    const { config } = props;
    const prefix = `suppliagent-${config.envName}`;

    this.key = new kms.Key(this, 'Key', {
      alias: `alias/${prefix}`,
      description: 'SuppliAgent CMK for data at rest',
      enableKeyRotation: true,
      removalPolicy: RemovalPolicy.DESTROY,
      pendingWindow: Duration.days(7),
    });
    // CloudWatch Logs needs explicit key policy access to encrypt log groups.
    this.key.addToResourcePolicy(
      new iam.PolicyStatement({
        principals: [new iam.ServicePrincipal(`logs.${this.region}.amazonaws.com`)],
        actions: [
          'kms:Encrypt*',
          'kms:Decrypt*',
          'kms:ReEncrypt*',
          'kms:GenerateDataKey*',
          'kms:Describe*',
        ],
        resources: ['*'],
        conditions: {
          ArnLike: {
            'kms:EncryptionContext:aws:logs:arn': `arn:aws:logs:${this.region}:${this.account}:*`,
          },
        },
      }),
    );

    // S3 server access logs do not support SSE-KMS on the target bucket: SSE-S3 is the only exception to the CMK.
    const accessLogsBucket = new s3.Bucket(this, 'AccessLogsBucket', {
      bucketName: `${prefix}-access-logs-${this.account}`,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
      lifecycleRules: [{ expiration: Duration.days(30) }],
      removalPolicy: RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });
    Validations.of(accessLogsBucket).acknowledge({
      id: 'AwsSolutions-S1',
      reason: 'This is the server access logs target bucket.',
    });

    const bucket = (id: string, name: string, expirationDays?: number): s3.Bucket =>
      new s3.Bucket(this, id, {
        bucketName: `${prefix}-${name}-${this.account}`,
        encryption: s3.BucketEncryption.KMS,
        encryptionKey: this.key,
        bucketKeyEnabled: true,
        blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
        enforceSSL: true,
        objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
        serverAccessLogsBucket: accessLogsBucket,
        serverAccessLogsPrefix: `${name}/`,
        lifecycleRules: expirationDays
          ? [{ expiration: Duration.days(expirationDays) }]
          : undefined,
        // Data is recreated by seed/seed.py and seed/reset.py (T-04).
        removalPolicy: RemovalPolicy.DESTROY,
        autoDeleteObjects: true,
      });

    this.mediaBucket = bucket('MediaBucket', 'media', 90);
    this.inboundMailBucket = bucket('InboundMailBucket', 'inbound-mail', 90);
    this.documentsBucket = bucket('DocumentsBucket', 'documents', 365);
    this.catalogAssetsBucket = bucket('CatalogAssetsBucket', 'catalog-assets');
    this.analyticsBucket = bucket('AnalyticsBucket', 'analytics', 365);

    this.eventBus = new events.EventBus(this, 'EventBus', {
      eventBusName: `${prefix}-events`,
      kmsKey: this.key,
    });

    for (const [name, value] of Object.entries(config.parameters)) {
      new ssm.StringParameter(this, `Param${name}`, {
        parameterName: `/suppliagent/${config.envName}/${name}`,
        stringValue: value,
      });
    }

    if (config.budgetAlertEmail) {
      new budgets.CfnBudget(this, 'Budget', {
        budget: {
          budgetName: prefix,
          budgetType: 'COST',
          timeUnit: 'MONTHLY',
          budgetLimit: { amount: config.budgetLimitUsd, unit: 'USD' },
        },
        notificationsWithSubscribers: [25, 50, 80].map((threshold) => ({
          notification: {
            notificationType: 'ACTUAL',
            comparisonOperator: 'GREATER_THAN',
            threshold,
            thresholdType: 'PERCENTAGE',
          },
          subscribers: [{ subscriptionType: 'EMAIL', address: config.budgetAlertEmail! }],
        })),
      });
    }

    // Scoped to the CDK-managed provider behind `autoDeleteObjects` (DESTROY removal policy).
    const autoDeleteProvider = this.node.findChild(
      'Custom::S3AutoDeleteObjectsCustomResourceProvider',
    );
    Validations.of(autoDeleteProvider).acknowledge({
      id: 'AwsSolutions-IAM4[Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole]',
      reason:
        'CDK-managed autoDeleteObjects custom resource provider uses the basic execution role.',
    });
    Validations.of(autoDeleteProvider).acknowledge({
      id: 'AwsSolutions-L1',
      reason:
        'CDK-managed autoDeleteObjects custom resource provider runtime is controlled by aws-cdk-lib.',
    });
  }
}
