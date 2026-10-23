import { Duration, Stack } from 'aws-cdk-lib';
import type { IKey } from 'aws-cdk-lib/aws-kms';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import { Construct } from 'constructs';
import type { EnvConfig } from '../../config/environments.js';

export interface PythonLambdaProps {
  readonly config: EnvConfig;
  readonly key: IKey;
  /** Short component name, e.g. `inbound-router`; the function is named `suppliagent-<env>-<name>`. */
  readonly name: string;
  // ponytail: plain asset for now; bundling with dependencies and suppliagent_shared is decided with the first real Lambda (T-21).
  readonly code: lambda.Code;
  readonly handler: string;
  readonly environment?: Record<string, string>;
  readonly timeout?: Duration;
  readonly memorySize?: number;
  /** Adds a KMS-encrypted SQS dead-letter queue for async invocations. */
  readonly withDlq?: boolean;
}

/** Lambda defaults for SuppliAgent: ARM64, Python 3.12, Powertools layer, X-Ray, KMS, log retention. */
export class PythonLambda extends Construct {
  readonly function: lambda.Function;
  readonly deadLetterQueue?: sqs.Queue;

  constructor(scope: Construct, id: string, props: PythonLambdaProps) {
    super(scope, id);
    const { config, key } = props;
    const functionName = `suppliagent-${config.envName}-${props.name}`;
    const region = Stack.of(this).region;

    const logGroup = new logs.LogGroup(this, 'LogGroup', {
      logGroupName: `/aws/lambda/${functionName}`,
      retention: config.logRetention,
      encryptionKey: key,
    });

    if (props.withDlq) {
      this.deadLetterQueue = new sqs.Queue(this, 'Dlq', {
        queueName: `${functionName}-dlq`,
        encryption: sqs.QueueEncryption.KMS,
        encryptionMasterKey: key,
        enforceSSL: true,
        retentionPeriod: Duration.days(14),
      });
    }

    this.function = new lambda.Function(this, 'Function', {
      functionName,
      runtime: lambda.Runtime.PYTHON_3_12,
      architecture: lambda.Architecture.ARM_64,
      code: props.code,
      handler: props.handler,
      timeout: props.timeout ?? Duration.seconds(30),
      memorySize: props.memorySize ?? 512,
      tracing: lambda.Tracing.ACTIVE,
      environmentEncryption: key,
      logGroup,
      loggingFormat: lambda.LoggingFormat.JSON,
      deadLetterQueue: this.deadLetterQueue,
      layers: [
        lambda.LayerVersion.fromLayerVersionArn(
          this,
          'Powertools',
          `arn:aws:lambda:${region}:017000801446:layer:AWSLambdaPowertoolsPythonV3-python312-arm64:${config.powertoolsLayerVersion}`,
        ),
      ],
      environment: {
        POWERTOOLS_SERVICE_NAME: props.name,
        SUPPLIAGENT_ENV: config.envName,
        ...props.environment,
      },
    });
  }
}
