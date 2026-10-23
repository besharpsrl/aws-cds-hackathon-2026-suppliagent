import { Stack, Validations, type StackProps } from 'aws-cdk-lib';
import type { Construct } from 'constructs';
import type { EnvConfig } from '../../config/environments.js';

export interface AgentStackProps extends StackProps {
  readonly config: EnvConfig;
}

/** Placeholder wired in dependency order (INFRASTRUCTURE_DESIGN §4); resources arrive with T-40. */
export class AgentStack extends Stack {
  constructor(scope: Construct, id: string, props: AgentStackProps) {
    super(scope, id, props);
    Validations.of(this).acknowledge({
      id: 'CloudFormation-Validate::F0001',
      reason: 'Placeholder stack without resources yet; remove when the first resource is added.',
    });
  }
}
