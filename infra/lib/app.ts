import { App, Tags, Validations, type Stack } from 'aws-cdk-lib';
import { AwsSolutionsChecks } from 'cdk-nag';
import { MANDATORY_TAGS, type EnvConfig } from '../config/environments.js';
import { AgentStack } from './stacks/agent-stack.js';
import { AnalyticsStack } from './stacks/analytics-stack.js';
import { CatalogStack } from './stacks/catalog-stack.js';
import { ChannelsStack } from './stacks/channels-stack.js';
import { ConsoleStack } from './stacks/console-stack.js';
import { DataStack } from './stacks/data-stack.js';
import { FoundationStack } from './stacks/foundation-stack.js';
import { MessagingStack } from './stacks/messaging-stack.js';
import { ProactiveStack } from './stacks/proactive-stack.js';

/** Builds the 9 SuppliAgent stacks in dependency order (INFRASTRUCTURE_DESIGN §4). */
export function buildApp(app: App, config: EnvConfig) {
  // Account stays env-agnostic so `cdk synth` runs in CI without AWS credentials.
  // Stack tags are explicit (flag @aws-cdk/core:explicitStackTags): CloudFormation propagates them to
  // every resource that supports tags, including raw CfnResources that Tags.of() cannot reach
  // (e.g. CDK-managed custom resource provider functions and roles).
  const tags = { ...MANDATORY_TAGS, Env: config.envName };
  const common = { config, env: { region: config.region }, tags };
  const name = (stack: string) => `suppliagent-${config.envName}-${stack}`;
  const after = (stack: Stack, ...deps: Stack[]) => {
    deps.forEach((dep) => stack.addStackDependency(dep));
    return stack;
  };

  const foundation = new FoundationStack(app, name('foundation'), common);
  const data = new DataStack(app, name('data'), { ...common, key: foundation.key });
  const catalog = after(new CatalogStack(app, name('catalog'), common), foundation, data);
  const channels = after(
    new ChannelsStack(app, name('channels'), {
      ...common,
      key: foundation.key,
      inboundMailBucket: foundation.inboundMailBucket,
    }),
    foundation,
  );
  const agent = after(
    new AgentStack(app, name('agent'), {
      ...common,
      key: foundation.key,
      tables: data.tables,
      eventBus: foundation.eventBus,
    }),
    foundation,
    data,
    catalog,
  );
  const messaging = after(
    new MessagingStack(app, name('messaging'), common),
    channels,
    agent,
    data,
  );
  const proactive = after(new ProactiveStack(app, name('proactive'), common), data, messaging);
  const consoleStack = after(
    new ConsoleStack(app, name('console'), {
      ...common,
      key: foundation.key,
      ordersTable: data.tables.Orders,
      mediaBucket: foundation.mediaBucket,
    }),
    data,
    messaging,
    agent,
  );
  const analytics = after(new AnalyticsStack(app, name('analytics'), common), channels, foundation);

  Object.entries(tags).forEach(([key, value]) => Tags.of(app).add(key, value));
  // cdk-nag v3 is a policy validation plugin: any unacknowledged error fails `cdk synth`.
  Validations.of(app).addPlugins(new AwsSolutionsChecks(app, { verbose: true }));

  return {
    foundation,
    data,
    catalog,
    channels,
    agent,
    messaging,
    proactive,
    console: consoleStack,
    analytics,
  };
}
