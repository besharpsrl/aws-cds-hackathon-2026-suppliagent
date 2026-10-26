import { fileURLToPath } from 'node:url';
import {
  CfnOutput,
  Duration,
  RemovalPolicy,
  Stack,
  Validations,
  type StackProps,
} from 'aws-cdk-lib';
import * as apigw from 'aws-cdk-lib/aws-apigateway';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import type { ITableV2 } from 'aws-cdk-lib/aws-dynamodb';
import * as iam from 'aws-cdk-lib/aws-iam';
import type { IKey } from 'aws-cdk-lib/aws-kms';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as s3 from 'aws-cdk-lib/aws-s3';
import type { Construct } from 'constructs';
import type { EnvConfig } from '../../config/environments.js';
import { PythonLambda } from '../constructs/python-lambda.js';

export interface ConsoleStackProps extends StackProps {
  readonly config: EnvConfig;
  readonly key: IKey;
  readonly ordersTable: ITableV2;
  readonly mediaBucket: s3.IBucket;
}

/** Console roles (FN-28, FN-32): `judge` is read-only. */
export const CONSOLE_GROUPS = ['backoffice', 'sales_rep', 'judge'] as const;

const consoleApiCode = fileURLToPath(new URL('../../../services/console_api/src', import.meta.url));

/**
 * Back-office console: Cognito, S3 + CloudFront (OAC) for the SPA, REST API with `console_api`.
 * WebSocket/broadcaster (T-63), rep chat (T-64) and WAF are not part of T-60.
 */
export class ConsoleStack extends Stack {
  readonly userPool: cognito.UserPool;
  readonly userPoolClient: cognito.UserPoolClient;
  readonly api: apigw.RestApi;
  readonly distribution: cloudfront.Distribution;

  constructor(scope: Construct, id: string, props: ConsoleStackProps) {
    super(scope, id, props);
    const { config, key } = props;
    const prefix = `suppliagent-${config.envName}`;

    // --- Auth ---------------------------------------------------------------------------------
    this.userPool = new cognito.UserPool(this, 'UserPool', {
      userPoolName: `${prefix}-console`,
      selfSignUpEnabled: false, // users are created by an admin (judges, back office)
      signInAliases: { email: true },
      standardAttributes: { email: { required: true, mutable: true } },
      // `repId` links a sales_rep login to the SalesReps table; set by the admin, not by the user.
      customAttributes: { repId: new cognito.StringAttribute({ mutable: true }) },
      passwordPolicy: {
        minLength: 12,
        requireLowercase: true,
        requireUppercase: true,
        requireDigits: true,
        requireSymbols: true,
      },
      accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      removalPolicy: RemovalPolicy.DESTROY,
    });
    Validations.of(this.userPool).acknowledge({
      id: 'AwsSolutions-COG2',
      reason: 'Demo console with admin-created synthetic users; MFA would block the judges.',
    });
    Validations.of(this.userPool).acknowledge({
      id: 'AwsSolutions-COG8',
      reason: 'Plus tier is a paid feature; not in the hackathon budget (AGENTS §11).',
    });
    for (const groupName of CONSOLE_GROUPS) {
      new cognito.CfnUserPoolGroup(this, `Group-${groupName}`, {
        userPoolId: this.userPool.userPoolId,
        groupName,
      });
    }
    this.userPoolClient = this.userPool.addClient('SpaClient', {
      userPoolClientName: `${prefix}-console-spa`,
      generateSecret: false, // browser client (Amplify, SRP); no secret can be kept
      authFlows: { userSrp: true },
      // `custom:repId` drives sales_rep authorization: readable, but only an admin may write it.
      readAttributes: new cognito.ClientAttributes()
        .withStandardAttributes({ email: true })
        .withCustomAttributes('repId'),
      writeAttributes: new cognito.ClientAttributes().withStandardAttributes({ email: true }),
      preventUserExistenceErrors: true,
      accessTokenValidity: Duration.hours(1),
      idTokenValidity: Duration.hours(1),
      refreshTokenValidity: Duration.days(1),
    });

    // --- SPA hosting --------------------------------------------------------------------------
    const logsBucket = new s3.Bucket(this, 'LogsBucket', {
      encryption: s3.BucketEncryption.S3_MANAGED, // server access logs do not support SSE-KMS
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      // CloudFront standard logging delivers with ACLs: BUCKET_OWNER_ENFORCED makes the distribution fail.
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_PREFERRED,
      lifecycleRules: [{ expiration: Duration.days(30) }],
      // ponytail: no autoDeleteObjects (its provider log group would be created untagged at runtime).
      removalPolicy: RemovalPolicy.RETAIN,
    });
    Validations.of(logsBucket).acknowledge({
      id: 'AwsSolutions-S1',
      reason: 'This is the server access logs target bucket.',
    });
    const siteBucket = new s3.Bucket(this, 'SiteBucket', {
      // Public static assets only (the built SPA): SSE-S3 keeps the CMK key policy untouched
      // (CloudFront OAC cannot use a CMK without a key policy change in FoundationStack).
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
      serverAccessLogsBucket: logsBucket,
      serverAccessLogsPrefix: 'site/',
      removalPolicy: RemovalPolicy.RETAIN,
    });
    this.distribution = new cloudfront.Distribution(this, 'Distribution', {
      comment: `${prefix} console`,
      defaultRootObject: 'index.html',
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(siteBucket),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
      },
      // SPA routing: unknown paths fall back to the app shell.
      errorResponses: [403, 404].map((httpStatus) => ({
        httpStatus,
        responseHttpStatus: 200,
        responsePagePath: '/index.html',
        ttl: Duration.seconds(10),
      })),
      logBucket: logsBucket,
      logFilePrefix: 'cloudfront/',
    });
    Validations.of(this.distribution).acknowledge({
      id: 'AwsSolutions-CFR1',
      reason: 'Judges connect from any country; no geo restriction.',
    });
    Validations.of(this.distribution).acknowledge({
      id: 'AwsSolutions-CFR2',
      reason:
        'WAF has a fixed monthly cost (AGENTS §11); API is protected by Cognito. Revisit before demo.',
    });
    Validations.of(this.distribution).acknowledge({
      id: 'AwsSolutions-CFR4',
      reason:
        'Default *.cloudfront.net certificate: TLS policy cannot be enforced without a custom domain.',
    });

    // --- API ----------------------------------------------------------------------------------
    const consoleApi = new PythonLambda(this, 'ConsoleApi', {
      config,
      key,
      name: 'console-api',
      code: lambda.Code.fromAsset(consoleApiCode),
      handler: 'console_api.handler.handler',
      environment: { ORDERS_TABLE: props.ordersTable.tableName },
    });
    // Read-only by design: the console API never writes orders (corrections arrive with T-46).
    // Explicit statements instead of grantRead*: no Action wildcards, only the ones below.
    consoleApi.function.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['dynamodb:GetItem', 'dynamodb:Query', 'dynamodb:Scan'],
        resources: [props.ordersTable.tableArn, `${props.ordersTable.tableArn}/index/*`],
      }),
    );
    // ponytail: bucket-wide read (presigned image URLs); narrow to the media key prefix once T-22 fixes the layout.
    consoleApi.function.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['s3:GetObject'],
        resources: [props.mediaBucket.arnForObjects('*')],
      }),
    );
    consoleApi.function.addToRolePolicy(
      new iam.PolicyStatement({ actions: ['kms:Decrypt'], resources: [key.keyArn] }),
    );
    // The `Resource::*` findings carry the cross-stack export token, so the ids depend on the env.
    const exported = (stack: string, logicalId: string) =>
      `Resource::${prefix}-${stack}:ExportsOutputFnGetAtt${logicalId}`;
    Validations.of(consoleApi).acknowledge({
      id: `AwsSolutions-IAM5[${exported('data', 'OrdersA9B65338Arn17F87B9C')}/index/*]`,
      reason: 'Orders GSIs (by-status, by-repId) have no fixed ARN list; read-only actions.',
    });
    Validations.of(consoleApi).acknowledge({
      id: `AwsSolutions-IAM5[${exported('foundation', 'MediaBucketBCBB02BAArnB94B784B')}/*]`,
      reason: 'Presigned URLs for any photo in the media bucket; read-only (s3:GetObject).',
    });

    this.api = new apigw.RestApi(this, 'Api', {
      restApiName: `${prefix}-console`,
      deployOptions: {
        stageName: 'v1',
        throttlingBurstLimit: 50,
        throttlingRateLimit: 25,
      },
      defaultCorsPreflightOptions: {
        // Bearer-token API, no cookies: any origin is safe, and the CloudFront domain is not known here.
        allowOrigins: apigw.Cors.ALL_ORIGINS,
        allowMethods: ['GET', 'OPTIONS'],
        allowHeaders: ['Authorization', 'Content-Type'],
      },
    });
    const authorizer = new apigw.CognitoUserPoolsAuthorizer(this, 'Authorizer', {
      cognitoUserPools: [this.userPool],
    });
    const integration = new apigw.LambdaIntegration(consoleApi.function);
    const methodOptions = {
      authorizer,
      authorizationType: apigw.AuthorizationType.COGNITO,
      requestParameters: { 'method.request.querystring.status': false },
    };
    const orders = this.api.root.addResource('orders');
    orders.addMethod('GET', integration, methodOptions);
    orders.addResource('{orderId}').addMethod('GET', integration, {
      ...methodOptions,
      requestParameters: { 'method.request.path.orderId': true },
    });
    const validator = this.api.addRequestValidator('Validator', {
      validateRequestParameters: true,
      validateRequestBody: true,
    });
    // Stage logging needs the account-wide API Gateway CloudWatch role (apigateway UpdateAccount):
    // unset here and shared with other projects, so it is not ours to change. Lambda logs cover the API.
    for (const id of ['AwsSolutions-APIG1', 'AwsSolutions-APIG6']) {
      Validations.of(this.api).acknowledge({
        id,
        reason:
          'API Gateway account has no CloudWatch Logs role; account setting shared with other projects.',
      });
    }
    for (const method of this.api.methods) {
      if (method.httpMethod !== 'OPTIONS') {
        (method.node.defaultChild as apigw.CfnMethod).requestValidatorId =
          validator.requestValidatorId;
      }
    }
    Validations.of(this.api).acknowledge({
      id: 'AwsSolutions-APIG3',
      reason:
        'WAF has a fixed monthly cost (AGENTS §11); every method requires a Cognito token. Revisit before demo.',
    });
    Validations.of(this.api).acknowledge({
      id: 'AwsSolutions-APIG4[Method::OPTIONS]',
      reason: 'CORS preflight cannot carry credentials.',
    });
    Validations.of(this.api).acknowledge({
      id: 'AwsSolutions-COG4[Method::OPTIONS]',
      reason: 'CORS preflight cannot carry credentials.',
    });

    new CfnOutput(this, 'UserPoolId', { value: this.userPool.userPoolId });
    new CfnOutput(this, 'UserPoolClientId', { value: this.userPoolClient.userPoolClientId });
    new CfnOutput(this, 'ApiUrl', { value: this.api.url });
    new CfnOutput(this, 'ConsoleUrl', {
      value: `https://${this.distribution.distributionDomainName}`,
    });
    new CfnOutput(this, 'SiteBucketName', { value: siteBucket.bucketName });
  }
}
