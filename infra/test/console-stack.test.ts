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

  it('lets console_api write only UpdateItem, and only on the Orders table (T-62)', () => {
    const statements = Object.values(template.findResources('AWS::IAM::Policy')).flatMap(
      (p) => p.Properties.PolicyDocument.Statement,
    ) as { Action: string | string[]; Resource: unknown }[];
    const actions = statements.flatMap((s) => s.Action);
    expect(actions).toContain('dynamodb:Query');
    expect(actions.filter((a) => /^dynamodb:(Put|Delete)/.test(a))).toEqual([]);
    const writers = statements.filter((s) => [s.Action].flat().includes('dynamodb:UpdateItem'));
    expect(writers).toHaveLength(1);
    expect([writers[0].Action].flat()).toEqual(['dynamodb:UpdateItem']);
    expect(JSON.stringify(writers[0].Resource)).not.toContain('/index/');
  });

  it('exposes the line correction as a validated PATCH behind the authorizer', () => {
    template.hasResourceProperties('AWS::ApiGateway::Method', {
      HttpMethod: 'PATCH',
      AuthorizationType: 'COGNITO_USER_POOLS',
      RequestModels: { 'application/json': Match.anyValue() },
      RequestParameters: {
        'method.request.path.orderId': true,
        'method.request.path.lineId': true,
      },
    });
    template.hasResourceProperties('AWS::ApiGateway::Model', {
      Schema: Match.objectLike({ required: ['sku'], additionalProperties: false }),
    });
  });

  it('allows PATCH in the CORS preflight', () => {
    template.hasResourceProperties('AWS::ApiGateway::Method', {
      HttpMethod: 'OPTIONS',
      Integration: Match.objectLike({
        IntegrationResponses: Match.arrayWith([
          Match.objectLike({
            ResponseParameters: Match.objectLike({
              'method.response.header.Access-Control-Allow-Methods': "'GET,PATCH,OPTIONS'",
            }),
          }),
        ]),
      }),
    });
  });
});
