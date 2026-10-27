import { App } from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { describe, expect, it } from 'vitest';
import { getConfig } from '../config/environments.js';
import { buildApp } from '../lib/app.js';
import { context } from './context.js';

const stacks = buildApp(new App({ context }), getConfig('dev'));
const template = Template.fromStack(stacks.catalog);

type Statement = { Action: string | string[]; Resource: unknown };
const actions = (): string[] =>
  Object.values(template.findResources('AWS::IAM::Policy'))
    .flatMap((p) => p.Properties.PolicyDocument.Statement as Statement[])
    .flatMap((s) => [s.Action].flat());

describe('CatalogStack (T-06, FN-07)', () => {
  it('creates a KMS-encrypted vector bucket', () => {
    template.hasResourceProperties('AWS::S3Vectors::VectorBucket', {
      EncryptionConfiguration: { SseType: 'aws:kms', KmsKeyArn: Match.anyValue() },
    });
  });

  it('creates the products index: 1024 float32 cosine, text not filterable', () => {
    template.hasResourceProperties('AWS::S3Vectors::Index', {
      IndexName: 'products',
      DataType: 'float32',
      Dimension: 1024,
      DistanceMetric: 'cosine',
      MetadataConfiguration: { NonFilterableMetadataKeys: ['text'] },
    });
  });

  it('gives the indexer read on Products, embeddings and write on the index only', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      FunctionName: 'suppliagent-dev-catalog-indexer',
      Architectures: ['arm64'],
      Environment: {
        Variables: Match.objectLike({ INDEX_NAME: 'products', TABLE_PREFIX: 'suppliagent-dev-' }),
      },
    });
    const all = actions();
    expect(all).toEqual(
      expect.arrayContaining([
        'bedrock:InvokeModel',
        's3vectors:PutVectors',
        's3vectors:DeleteVectors',
        'dynamodb:Scan',
      ]),
    );
    expect(all).not.toContain('dynamodb:PutItem');
    expect(all).not.toContain('s3vectors:*');
  });

  it('lets the S3 Vectors service principal decrypt with the CMK (Foundation key policy)', () => {
    Template.fromStack(stacks.foundation).hasResourceProperties('AWS::KMS::Key', {
      KeyPolicy: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Principal: { Service: 'indexing.s3vectors.amazonaws.com' },
            Action: 'kms:Decrypt',
          }),
        ]),
      },
    });
  });

  it('passes the bucket name, not its ARN, to the indexer and exposes it to the other stacks', () => {
    const [indexer] = Object.values(template.findResources('AWS::Lambda::Function')).filter(
      (f) => f.Properties.FunctionName === 'suppliagent-dev-catalog-indexer',
    );
    const name = JSON.stringify(indexer.Properties.Environment.Variables.VECTOR_BUCKET_NAME);
    expect(name).toContain('suppliagent-dev-vectors-');
    expect(name).not.toContain('Fn::GetAtt');
    expect(name).not.toContain('"Ref":"VectorBucket');
  });
});
