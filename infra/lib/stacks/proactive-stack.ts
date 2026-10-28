import * as path from 'node:path';
import { Duration, Stack, type StackProps } from 'aws-cdk-lib';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import type { ITableV2 } from 'aws-cdk-lib/aws-dynamodb';
import * as events from 'aws-cdk-lib/aws-events';
import type { IEventBus } from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as iam from 'aws-cdk-lib/aws-iam';
import type { IKey } from 'aws-cdk-lib/aws-kms';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import type { Construct } from 'constructs';
import type { EnvConfig } from '../../config/environments.js';
import { PythonLambda } from '../constructs/python-lambda.js';
import { REPO_ROOT, uvBundling } from '../constructs/uv-bundling.js';

export interface ProactiveStackProps extends StackProps {
  readonly config: EnvConfig;
  readonly key: IKey;
  readonly eventBus: IEventBus;
  readonly tables: {
    readonly customers: ITableV2;
    readonly contacts: ITableV2;
    readonly orders: ITableV2;
    readonly orderHistory: ITableV2;
    readonly customerInsights: ITableV2;
    readonly promotions: ITableV2;
  };
}

/**
 * Proactivity (T-08, FN-19, FN-20, INFRASTRUCTURE_DESIGN §5.6, F-13):
 * nightly Insights & Reorder Analyzer -> `CustomerInsights` (read by `get_customer_profile`, `reco`,
 * briefings); morning Proactive Trigger -> `reorder.due` on the application bus for the proactive
 * turn (T-52). Neither sends messages. Both can be invoked on demand for the demo.
 */
export class ProactiveStack extends Stack {
  constructor(scope: Construct, id: string, props: ProactiveStackProps) {
    super(scope, id, props);
    const { config, key, tables, eventBus } = props;
    const prefix = `suppliagent-${config.envName}`;

    const fn = (name: string, module: string, environment: Record<string, string>) => {
      const folder = module.replace(/-/g, '_');
      const created = new PythonLambda(this, name, {
        config,
        key,
        name: module,
        code: lambda.Code.fromAsset(
          path.join(REPO_ROOT, `services/${folder}`),
          uvBundling({
            package: `suppliagent-${module}`,
            sources: {
              'services/shared/src/suppliagent_shared': 'suppliagent_shared',
              [`services/${folder}/src/${folder}`]: folder,
            },
            omit: ['boto3', 'botocore', 's3transfer', 'aws-lambda-powertools'],
          }),
        ),
        handler: `${folder}.handler.handler`,
        timeout: Duration.minutes(5),
        environment: { TABLE_PREFIX: `${prefix}-`, ...environment },
      });
      created.function.addToRolePolicy(
        new iam.PolicyStatement({
          actions: ['kms:Decrypt', 'kms:GenerateDataKey'],
          resources: [key.keyArn],
        }),
      );
      created.function.metricErrors().createAlarm(this, `${name}ErrorsAlarm`, {
        alarmName: `${prefix}-${module}-errors`,
        threshold: 0,
        comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        evaluationPeriods: 1,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      });
      return created.function;
    };
    const allow = (target: lambda.Function, actions: string[], resources: string[]) =>
      target.addToRolePolicy(new iam.PolicyStatement({ actions, resources }));

    const analyzer = fn('InsightsAnalyzer', 'insights-analyzer', {});
    allow(analyzer, ['dynamodb:Scan'], [tables.customers.tableArn, tables.promotions.tableArn]);
    allow(
      analyzer,
      ['dynamodb:Query'],
      [tables.orderHistory.tableArn, `${tables.orders.tableArn}/index/by-customerId`],
    );
    allow(analyzer, ['dynamodb:UpdateItem'], [tables.customerInsights.tableArn]);

    const trigger = fn('ProactiveTrigger', 'proactive-trigger', {
      EVENT_BUS_NAME: eventBus.eventBusName,
      REORDER_DUE_FACTOR: config.parameters.reorderDueFactor,
      REORDER_COOLDOWN_DAYS: config.parameters.reorderCooldownDays,
      QUIET_HOURS: config.parameters.quietHours,
    });
    allow(trigger, ['dynamodb:Scan'], [tables.contacts.tableArn, tables.customerInsights.tableArn]);
    allow(trigger, ['dynamodb:Query'], [`${tables.orders.tableArn}/index/by-customerId`]);
    allow(trigger, ['dynamodb:UpdateItem'], [tables.customerInsights.tableArn]);
    allow(trigger, ['events:PutEvents'], [eventBus.eventBusArn]);

    // Schedules run on the default bus, in UTC: 01:00 UTC is 02:00/03:00 in Rome; 08:00 UTC is
    // 09:00/10:00, inside the allowed hours (the trigger checks `quietHours` anyway).
    new events.Rule(this, 'InsightsAnalyzerSchedule', {
      ruleName: `${prefix}-insights-analyzer`,
      schedule: events.Schedule.cron({ minute: '0', hour: '1' }),
      targets: [new targets.LambdaFunction(analyzer)],
    });
    new events.Rule(this, 'ProactiveTriggerSchedule', {
      ruleName: `${prefix}-proactive-trigger`,
      schedule: events.Schedule.cron({ minute: '0', hour: '8' }),
      targets: [new targets.LambdaFunction(trigger)],
    });
  }
}
