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
  /** Custom domain of the console (CNAME to CloudFront, docs/INFRASTRUCTURE_DESIGN.md §8). Needs `consoleCertificateArn`. */
  readonly consoleDomain?: string;
  /** ACM certificate of `consoleDomain`, in us-east-1 (CloudFront requirement). */
  readonly consoleCertificateArn?: string;
  /** WhatsApp phone number ID on EUM Social (T-15). Unset → SSM parameter `UNSET`. */
  readonly waPhoneNumberId?: string;
  /** RCS agent of EUM SMS v2 (M-11, docs/RCS_SMS_SETUP.md). Unset → SSM `UNSET`, no RCS/SMS. */
  readonly rcsAgentId?: string;
  /** SMS sender ID used as the RCS fallback, as `<SenderId>/<ISO country>` (M-11). */
  readonly smsSenderId?: string;
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

// Amazon Nova 2 Lite via the EU cross-region profile (decision of 28/10, was Nova Pro since 25/10;
// Claude not enabled on the account). Destination regions from GetInferenceProfile in eu-west-1.
const nova2Lite: BedrockModelConfig = {
  profileId: 'eu.amazon.nova-2-lite-v1:0',
  destinationRegions: [
    'eu-central-1',
    'eu-north-1',
    'eu-south-1',
    'eu-south-2',
    'eu-west-1',
    'eu-west-3',
  ],
};

// Defaults from docs/02_TECHNICAL_FLOWS.md §7.
const runtimeParameters: Record<string, string> = {
  debounceTextMs: '3000',
  debounceMediaMs: '6000',
  debounceMaxMs: '15000',
  turnLockTtlMs: '120000',
  // Messages one agent turn takes at most (oldest first); the rest get the next turn (T-67).
  turnMaxMessages: '20',
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
  minOrderValue: '0', // hackathon demo: no minimum order (was 80)
  identificationMaxAttempts: '3',
  // Privacy notice of the first contact (F-01, FN-02): the distributor publishes the page and sets its URL here (`UNSET` = the agent says the notice is available from the office); the version is stored with each consent.
  privacyNoticeUrl: 'UNSET',
  privacyNoticeVersion: '2026-10-28',
  // The Notifier records outgoing messages instead of sending them (T-24, T-14); read at runtime.
  // `false` since T-68: replies really go out (also for the judges). The simulator
  // (`scripts/simulate_channel.py`) needs `true`: set it in SSM for a test, then back to `false`.
  notifierSandbox: 'false',
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
    consoleDomain: 'app.suppliagent.stonecutters.besharp.net',
    consoleCertificateArn:
      'arn:aws:acm:us-east-1:471112860008:certificate/0a49dbe3-377f-43cc-a6a9-9fde325938b8',
    waPhoneNumberId: 'phone-number-id-79f96a1ea97d47aabfce52eb7b8cf23c', // set once the WABA is linked (docs/WABA_SETUP.md)
    rcsAgentId: 'rcs-83650561df2543e1942ccb9a500fa736', // test agent, testers only (M-11)
    smsSenderId: 'SUPPLIAGENT/IT', // one-way alphanumeric sender ID (M-11)
    parameters: runtimeParameters,
    model: nova2Lite,
  },
};

/** Channel value of the environment; `-c <name>=…` stays as an override of the config. */
export function channelValue(
  node: { tryGetContext(key: string): unknown },
  config: EnvConfig,
  name: 'sesDomain' | 'waPhoneNumberId' | 'rcsAgentId' | 'smsSenderId',
): string | undefined {
  return (node.tryGetContext(name) as string | undefined) || config[name];
}

export function getConfig(envName: string | undefined): EnvConfig {
  if (envName !== 'dev') {
    throw new Error(`Unknown env "${envName}": pass -c env=dev`);
  }
  return environments[envName];
}
