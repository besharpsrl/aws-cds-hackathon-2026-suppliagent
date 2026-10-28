import { App } from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import { describe, expect, it } from 'vitest';
import { getConfig } from '../config/environments.js';
import { buildApp } from '../lib/app.js';
import { context } from './context.js';

const stacks = buildApp(new App({ context }), getConfig('dev'));
const template = Template.fromStack(stacks.proactive);

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
const schedule = (name: string) =>
  Object.values(template.findResources('AWS::Events::Rule')).find(
    (r) => r.Properties.Name === `suppliagent-dev-${name}`,
  )?.Properties;

describe('ProactiveStack (T-08, FN-19, FN-20)', () => {
  it('runs the analyzer at night and the trigger in the morning, on the default bus', () => {
    expect(schedule('insights-analyzer')?.ScheduleExpression).toBe('cron(0 1 * * ? *)');
    expect(schedule('proactive-trigger')?.ScheduleExpression).toBe('cron(0 8 * * ? *)');
    expect(schedule('proactive-trigger')?.EventBusName).toBeUndefined();
    expect(functionProps('proactive-trigger')?.Environment.Variables).toMatchObject({
      REORDER_DUE_FACTOR: '1.5',
      REORDER_COOLDOWN_DAYS: '7',
      QUIET_HOURS: '21:00-07:00',
    });
    for (const name of ['insights-analyzer', 'proactive-trigger']) {
      template.hasResourceProperties('AWS::CloudWatch::Alarm', {
        AlarmName: `suppliagent-dev-${name}-errors`,
      });
    }
  });

  it('lets the analyzer only update insights and the trigger only claim the cooldown and emit', () => {
    const analyzer = rolePolicy('insights-analyzer');
    expect(analyzer).toContain('dynamodb:UpdateItem');
    expect(analyzer).toContain('index/by-customerId'); // orders placed through SuppliAgent
    expect(analyzer).not.toMatch(/dynamodb:(PutItem|DeleteItem)|events:PutEvents/);
    const trigger = rolePolicy('proactive-trigger');
    expect(trigger).toContain('index/by-customerId');
    expect(trigger).toContain('events:PutEvents');
    expect(trigger).not.toMatch(/dynamodb:(PutItem|DeleteItem)|lambda:InvokeFunction/);
    for (const policy of [analyzer, trigger]) {
      expect(policy).not.toMatch(/social-messaging|ses:Send|sms-voice|sns:Publish/);
      expect(policy).not.toMatch(/"(dynamodb|events|kms|lambda):\*"/);
    }
  });
});
