import { readFileSync } from 'node:fs';

/**
 * Same feature flags as `cdk synth`, with asset bundling off: tests need neither `uv` nor network
 * (the real bundling runs in `cdk synth` / `cdk deploy`).
 */
export const context = {
  ...JSON.parse(readFileSync(new URL('../cdk.json', import.meta.url), 'utf8')).context,
  'aws:cdk:bundling-stacks': [],
};
