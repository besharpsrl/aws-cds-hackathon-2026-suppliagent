import { App } from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { describe, expect, it } from 'vitest';
import { getConfig } from '../config/environments.js';
import { buildApp } from '../lib/app.js';
import { context } from './context.js';
const template = Template.fromStack(buildApp(new App({ context }), getConfig('dev')).console);

describe('ConsoleStack (T-60, FN-28, FN-32)', () => {
  it('creates the three Cognito groups', () => {
    for (const name of ['backoffice', 'sales_rep', 'judge']) {
      template.hasResourceProperties('AWS::Cognito::UserPoolGroup', { GroupName: name });
    }
    template.resourceCountIs('AWS::Cognito::UserPoolGroup', 3);
  });

  it('disables self sign-up and uses a public SPA client without secret', () => {
    template.hasResourceProperties('AWS::Cognito::UserPool', {
      AdminCreateUserConfig: { AllowAdminCreateUserOnly: true },
    });
    template.hasResourceProperties('AWS::Cognito::UserPoolClient', { GenerateSecret: false });
  });

  it('does not let the client write custom:repId (sales_rep authorization claim)', () => {
    const [client] = Object.values(template.findResources('AWS::Cognito::UserPoolClient'));
    expect(client.Properties.WriteAttributes).toEqual(['email']);
    expect(client.Properties.ReadAttributes).toContain('custom:repId');
  });

  it('serves the SPA from a private bucket behind CloudFront with OAC', () => {
    template.resourceCountIs('AWS::CloudFront::OriginAccessControl', 1);
    template.hasResourceProperties('AWS::CloudFront::Distribution', {
      DistributionConfig: Match.objectLike({
        DefaultRootObject: 'index.html',
        DefaultCacheBehavior: Match.objectLike({ ViewerProtocolPolicy: 'redirect-to-https' }),
      }),
    });
    template.hasResourceProperties('AWS::S3::Bucket', {
      PublicAccessBlockConfiguration: Match.objectLike({ BlockPublicAcls: true }),
    });
  });

  it('keeps ACLs enabled on the log bucket, required by CloudFront standard logging', () => {
    template.hasResourceProperties('AWS::S3::Bucket', {
      OwnershipControls: { Rules: [{ ObjectOwnership: 'BucketOwnerPreferred' }] },
    });
  });

  it('does not enable stage logging (needs the shared account-level CloudWatch role)', () => {
    const [stage] = Object.values(template.findResources('AWS::ApiGateway::Stage'));
    expect(stage.Properties.AccessLogSetting).toBeUndefined();
    expect(JSON.stringify(stage.Properties.MethodSettings)).not.toContain('LoggingLevel');
  });

  it('protects every API method with the Cognito authorizer', () => {
    const methods = Object.values(template.findResources('AWS::ApiGateway::Method'));
    const nonPreflight = methods.filter((m) => m.Properties.HttpMethod !== 'OPTIONS');
    expect(nonPreflight.length).toBeGreaterThanOrEqual(2);
    for (const method of nonPreflight) {
      expect(method.Properties.AuthorizationType).toBe('COGNITO_USER_POOLS');
    }
  });

  it('gives console_api read-only access to Orders (no write actions)', () => {
    const statements = Object.values(template.findResources('AWS::IAM::Policy')).flatMap(
      (p) => p.Properties.PolicyDocument.Statement,
    );
    const actions = statements.flatMap((s: { Action: string | string[] }) => s.Action);
    expect(actions).toContain('dynamodb:Query');
    expect(actions.filter((a: string) => /^dynamodb:(Put|Update|Delete|Batch)/.test(a))).toEqual(
      [],
    );
  });
});
