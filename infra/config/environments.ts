import { RetentionDays } from 'aws-cdk-lib/aws-logs';

// Single environment: development, demo and judging all run on `dev` (decision of 27/10/2026).
export type EnvName = 'dev';

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
  /** SES domain for orders: creates identity and inbound rule set (T-15). Unset → no SES resources. */
  readonly sesDomain?: string;
  /** WhatsApp phone number ID on EUM Social (T-15). Unset → SSM parameter `UNSET`. */
  readonly waPhoneNumberId?: string;
  /** Runtime parameters published to SSM under /suppliagent/<env>/<name> (02_TECHNICAL_FLOWS §7). */
  readonly parameters: Readonly<Record<string, string>>;
  /** Bedrock inference profile of the agent (always `eu.`, INFRASTRUCTURE_DESIGN §2). */
  readonly model: BedrockModelConfig;
}

export interface BedrockModelConfig {
  /** Inference profile ID, e.g. `eu.amazon.nova-pro-v1:0`. */
  readonly profileId: string;
  /** Regions the `eu.` profile routes to: IAM needs the foundation model in each of them. */
  readonly destinationRegions: readonly string[];
}

// Amazon Nova Pro via the EU cross-region profile (decision of 25/10: Claude not enabled on the account).
// Destination regions from the Nova Pro model card for source region eu-west-1.
const novaPro: BedrockModelConfig = {
  profileId: 'eu.amazon.nova-pro-v1:0',
  destinationRegions: ['eu-central-1', 'eu-north-1', 'eu-west-1', 'eu-west-3'],
};

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
  // Orders placed after the cut-off (Europe/Rome) are delivered one day later; below the minimum value (EUR) an order is not confirmed (FN-09, FN-10).
  deliveryCutoff: '18:00',
  minOrderValue: '80',
  identificationMaxAttempts: '3',
  // The Notifier records outgoing messages instead of sending them (T-24, T-14); read at runtime.
  notifierSandbox: 'true',
  // The ERP mock answers as unavailable while `true` (to show E-08); read at runtime, default `false` (T-07).
  erpMockFailure: 'false',
};

const environments: Record<EnvName, EnvConfig> = {
  dev: {
    envName: 'dev',
    region: 'eu-west-1',
    powertoolsLayerVersion: 40,
    logRetention: RetentionDays.TWO_WEEKS,
    sesDomain: 'suppliagent.stonecutters.besharp.net',
    waPhoneNumberId: 'phone-number-id-79f96a1ea97d47aabfce52eb7b8cf23c', // set once the WABA is linked (docs/WABA_SETUP.md)
    parameters: runtimeParameters,
    model: novaPro,
  },
};

/** Channel value of the environment; `-c <name>=…` stays as an override of the config. */
export function channelValue(
  node: { tryGetContext(key: string): unknown },
  config: EnvConfig,
  name: 'sesDomain' | 'waPhoneNumberId',
): string | undefined {
  return (node.tryGetContext(name) as string | undefined) || config[name];
}

export function getConfig(envName: string | undefined): EnvConfig {
  if (envName !== 'dev') {
    throw new Error(`Unknown env "${envName}": pass -c env=dev`);
  }
  return environments[envName];
}
