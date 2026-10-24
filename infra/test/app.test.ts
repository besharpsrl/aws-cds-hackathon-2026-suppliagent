import { readFileSync } from 'node:fs';
import { App, CfnResource, type ITaggable, Stack, TagManager, Validations } from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import * as kms from 'aws-cdk-lib/aws-kms';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { AwsSolutionsChecks } from 'cdk-nag';
import { describe, expect, it } from 'vitest';
import { getConfig } from '../config/environments.js';
import { buildApp } from '../lib/app.js';
import { PythonLambda } from '../lib/constructs/python-lambda.js';
import { TABLES } from '../lib/stacks/data-stack.js';

// Same feature flags as `cdk synth`.
const { context } = JSON.parse(readFileSync(new URL('../cdk.json', import.meta.url), 'utf8'));

const build = (env = 'dev') => {
  const app = new App({ context });
  return { app, stacks: buildApp(app, getConfig(env)) };
};

describe('app', () => {
  it.each(['dev', 'demo'])('synthesizes %s with no cdk-nag errors', (env) => {
    // cdk-nag v3 runs as a policy validation plugin and throws on unacknowledged errors.
    expect(() => build(env).app.synth()).not.toThrow();
  });

  it('fails synth when cdk-nag finds a violation', () => {
    const { app } = build();
    new s3.Bucket(new Stack(app, 'Probe'), 'Unlogged');
    expect(() => app.synth()).toThrow(/AwsSolutions-S1/);
  });

  it('wires stacks in the INFRASTRUCTURE_DESIGN §4 dependency order', () => {
    const { app, stacks } = build();
    app.synth(); // resolves implicit dependencies from cross-stack references
    const deps = (stack: Stack) => stack.dependencies.map((d) => d.stackName).sort();
    expect(deps(stacks.data)).toEqual(['suppliagent-dev-foundation']);
    expect(deps(stacks.messaging)).toEqual([
      'suppliagent-dev-agent',
      'suppliagent-dev-channels',
      'suppliagent-dev-data',
    ]);
    expect(deps(stacks.analytics)).toEqual([
      'suppliagent-dev-channels',
      'suppliagent-dev-foundation',
    ]);
  });

  it('rejects unknown environments', () => {
    expect(() => getConfig('prod')).toThrow(/Unknown env/);
  });
});

describe('mandatory tags (AGENTS.md §7)', () => {
  const required = { Project: 'Hackathon AWS CDS', Owner: 'matteo.goretti@besharp.it', Env: 'dev' };
  const { app } = build('dev');
  const assembly = app.synth();

  it('sets them as explicit stack tags, so CloudFormation propagates them to every resource', () => {
    expect(assembly.stacks).toHaveLength(9);
    for (const stack of assembly.stacks) {
      expect(stack.tags, stack.stackName).toMatchObject(required);
    }
  });

  it('renders them on every taggable resource', () => {
    const taggable = app.node
      .findAll()
      .filter(
        (c): c is CfnResource & ITaggable =>
          CfnResource.isCfnResource(c) && TagManager.isTaggable(c),
      );
    expect(taggable.length).toBeGreaterThan(20);
    for (const resource of taggable) {
      expect(resource.tags.tagValues(), resource.node.path).toMatchObject({
        Project: required.Project,
        Owner: required.Owner,
      });
    }
  });
});

describe('FoundationStack', () => {
  const template = Template.fromStack(build().stacks.foundation);

  it('creates a rotating CMK', () => {
    template.hasResourceProperties('AWS::KMS::Key', { EnableKeyRotation: true });
  });

  it('encrypts data buckets with the CMK and blocks public access', () => {
    const buckets = template.findResources('AWS::S3::Bucket', {
      Properties: {
        BucketEncryption: {
          ServerSideEncryptionConfiguration: [
            Match.objectLike({
              ServerSideEncryptionByDefault: Match.objectLike({ SSEAlgorithm: 'aws:kms' }),
            }),
          ],
        },
        PublicAccessBlockConfiguration: Match.objectLike({ BlockPublicAcls: true }),
      },
    });
    expect(Object.keys(buckets)).toHaveLength(5);
  });

  it('keeps access logs on SSE-S3 with 30-day expiration', () => {
    template.hasResourceProperties('AWS::S3::Bucket', {
      BucketEncryption: {
        ServerSideEncryptionConfiguration: [
          { ServerSideEncryptionByDefault: { SSEAlgorithm: 'AES256' } },
        ],
      },
      LifecycleConfiguration: { Rules: [Match.objectLike({ ExpirationInDays: 30 })] },
    });
  });

  it('pre-creates the tagged, encrypted log group of the autoDeleteObjects provider', () => {
    // Otherwise Lambda creates it at runtime, outside CloudFormation and without tags.
    const handler = Object.keys(template.findResources('AWS::Lambda::Function')).find((id) =>
      id.startsWith('CustomS3AutoDeleteObjectsCustomResourceProviderHandler'),
    );
    template.hasResourceProperties('AWS::Logs::LogGroup', {
      LogGroupName: { 'Fn::Join': ['', ['/aws/lambda/', { Ref: handler }]] },
      KmsKeyId: Match.anyValue(),
      RetentionInDays: 14,
    });
    const logGroup = Object.keys(
      template.findResources('AWS::Logs::LogGroup', {
        Properties: { LogGroupName: { 'Fn::Join': ['', ['/aws/lambda/', { Ref: handler }]] } },
      }),
    )[0];
    const autoDeletes = Object.values(template.findResources('Custom::S3AutoDeleteObjects'));
    expect(autoDeletes).toHaveLength(6);
    for (const resource of autoDeletes) {
      expect(resource.DependsOn).toContain(logGroup);
    }
  });

  it('publishes runtime parameters to SSM', () => {
    template.hasResourceProperties('AWS::SSM::Parameter', {
      Name: '/suppliagent/dev/matchAutoThreshold',
      Value: '0.85',
    });
  });

  it('creates no AWS Budget (shared account)', () => {
    template.resourceCountIs('AWS::Budgets::Budget', 0);
  });
});

describe('DataStack', () => {
  const template = Template.fromStack(build().stacks.data);
  const tables = template.findResources('AWS::DynamoDB::GlobalTable');
  const byName = (name: string) =>
    Object.values(tables).find((t) => t.Properties.TableName === `suppliagent-dev-${name}`)!
      .Properties;

  it('creates every §5.7 table on-demand with PITR and the CMK', () => {
    expect(Object.keys(tables)).toHaveLength(TABLES.length);
    for (const table of Object.values(tables)) {
      expect(table.Properties.BillingMode).toBe('PAY_PER_REQUEST');
      expect(table.Properties.SSESpecification).toMatchObject({ SSEEnabled: true, SSEType: 'KMS' });
      expect(table.Properties.Replicas[0]).toMatchObject({
        PointInTimeRecoverySpecification: { PointInTimeRecoveryEnabled: true },
        SSESpecification: { KMSMasterKeyId: expect.anything() },
      });
    }
  });

  it('enables streams only on Orders and Messages', () => {
    const streamed = Object.values(tables)
      .filter((t) => t.Properties.StreamSpecification)
      .map((t) => t.Properties.TableName)
      .sort();
    expect(streamed).toEqual(['suppliagent-dev-messages', 'suppliagent-dev-orders']);
  });

  it('defines the Orders GSIs', () => {
    expect(
      byName('orders').GlobalSecondaryIndexes.map((i: { IndexName: string }) => i.IndexName),
    ).toEqual(['by-customerId', 'by-status', 'by-repId']);
  });

  const keySchema = (key: string | readonly string[]) => {
    const [pk, sk] = typeof key === 'string' ? [key] : key;
    return [
      { AttributeName: pk, KeyType: 'HASH' },
      ...(sk ? [{ AttributeName: sk, KeyType: 'RANGE' }] : []),
    ];
  };

  it.each(TABLES.map((t) => [t.name, t] as const))('%s matches §5.7 keys and GSIs', (_, spec) => {
    const kebab = spec.name.replace(/([a-z])([A-Z])/g, '$1-$2').toLowerCase();
    const table = byName(kebab);
    expect(table.KeySchema).toEqual(keySchema(spec.key));
    const indexes: readonly (string | readonly string[])[] = 'indexes' in spec ? spec.indexes : [];
    expect(
      (table.GlobalSecondaryIndexes ?? []).map((i: { KeySchema: unknown }) => i.KeySchema),
    ).toEqual(indexes.map(keySchema));
  });

  it('enables TTL on TurnBuffer and WsConnections', () => {
    for (const name of ['turn-buffer', 'ws-connections']) {
      expect(byName(name).TimeToLiveSpecification).toEqual({
        AttributeName: 'expiresAt',
        Enabled: true,
      });
    }
  });
});

describe('PythonLambda', () => {
  const app = new App({ context });
  Validations.of(app).addPlugins(new AwsSolutionsChecks(app));
  const stack = new Stack(app, 'LambdaProbe', { env: { region: 'eu-west-1' } });
  new PythonLambda(stack, 'Fn', {
    config: getConfig('dev'),
    key: new kms.Key(stack, 'Key', { enableKeyRotation: true }),
    name: 'probe',
    code: lambda.Code.fromInline('def handler(event, context): return None'),
    handler: 'index.handler',
    withDlq: true,
  });
  const template = Template.fromStack(stack);

  it('passes cdk-nag', () => {
    expect(() => app.synth()).not.toThrow();
  });

  it('applies SuppliAgent Lambda defaults', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      FunctionName: 'suppliagent-dev-probe',
      Runtime: 'python3.12',
      Architectures: ['arm64'],
      TracingConfig: { Mode: 'Active' },
      KmsKeyArn: Match.anyValue(),
      DeadLetterConfig: Match.anyValue(),
      Layers: [
        'arn:aws:lambda:eu-west-1:017000801446:layer:AWSLambdaPowertoolsPythonV3-python312-arm64:40',
      ],
    });
    template.hasResourceProperties('AWS::Logs::LogGroup', {
      LogGroupName: '/aws/lambda/suppliagent-dev-probe',
      RetentionInDays: 14,
      KmsKeyId: Match.anyValue(),
    });
    template.hasResourceProperties('AWS::SQS::Queue', { KmsMasterKeyId: Match.anyValue() });
  });
});
