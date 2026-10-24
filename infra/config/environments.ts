import { RetentionDays } from 'aws-cdk-lib/aws-logs';

export type EnvName = 'dev' | 'demo';

/** Tags required on every resource of the account (AGENTS.md §7, decision of 24/10/2026). */
export const MANDATORY_TAGS = {
  Project: 'Hackathon AWS CDS',
  Owner: 'matteo.goretti@besharp.it',
} as const;

export interface EnvConfig {
  readonly envName: EnvName;
  readonly region: string;
  /** Version of the public Powertools for AWS Lambda (Python) v3 layer, python3.12 arm64. */
  readonly powertoolsLayerVersion: number;
  readonly logRetention: RetentionDays;
  /** Runtime parameters published to SSM under /suppliagent/<env>/<name> (02_TECHNICAL_FLOWS §7). */
  readonly parameters: Readonly<Record<string, string>>;
}

// Defaults from docs/02_TECHNICAL_FLOWS.md §7.
const runtimeParameters: Record<string, string> = {
  debounceTextMs: '3000',
  debounceMediaMs: '6000',
  debounceMaxMs: '15000',
  turnLockTtlMs: '120000',
  matchAutoThreshold: '0.85',
  matchAskThreshold: '0.5',
  maxClarificationsPerMessage: '5',
  unmatchedMaxAttempts: '2',
  maxSuggestionsPerOrder: '1',
  pendingReminderHours: '2',
  draftExpiry: 'END_OF_DAY',
  reorderDueFactor: '1.5',
  reorderCooldownDays: '7',
  quietHours: '21:00-07:00',
  deliveryAutoConfirm: 'true',
  identificationMaxAttempts: '3',
};

const environments: Record<EnvName, EnvConfig> = {
  dev: {
    envName: 'dev',
    region: 'eu-west-1',
    powertoolsLayerVersion: 40,
    logRetention: RetentionDays.TWO_WEEKS,
    parameters: runtimeParameters,
  },
  demo: {
    envName: 'demo',
    region: 'eu-west-1',
    powertoolsLayerVersion: 40,
    logRetention: RetentionDays.ONE_MONTH,
    parameters: runtimeParameters,
  },
};

export function getConfig(envName: string | undefined): EnvConfig {
  if (envName !== 'dev' && envName !== 'demo') {
    throw new Error(`Unknown env "${envName}": pass -c env=dev or -c env=demo`);
  }
  return environments[envName];
}
