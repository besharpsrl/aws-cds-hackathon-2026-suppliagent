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

describe('CatalogStack – technical sheets (T-06b, FN-21)', () => {
  it('creates the product-sheets index with the Bedrock keys not filterable', () => {
    template.hasResourceProperties('AWS::S3Vectors::Index', {
      IndexName: 'product-sheets',
      DataType: 'float32',
      Dimension: 1024,
      DistanceMetric: 'cosine',
      MetadataConfiguration: {
        NonFilterableMetadataKeys: ['AMAZON_BEDROCK_TEXT', 'AMAZON_BEDROCK_METADATA'],
      },
    });
  });

  it('creates a Knowledge Base on S3 Vectors with Titan V2 and the sheets/ data source', () => {
    template.hasResourceProperties('AWS::Bedrock::KnowledgeBase', {
      Name: 'suppliagent-dev-product-sheets',
      StorageConfiguration: {
        Type: 'S3_VECTORS',
        S3VectorsConfiguration: { IndexArn: Match.anyValue() },
      },
      KnowledgeBaseConfiguration: {
        Type: 'VECTOR',
        VectorKnowledgeBaseConfiguration: Match.objectLike({
          EmbeddingModelConfiguration: {
            BedrockEmbeddingModelConfiguration: { Dimensions: 1024, EmbeddingDataType: 'FLOAT32' },
          },
        }),
      },
    });
    template.hasResourceProperties('AWS::Bedrock::DataSource', {
      DataSourceConfiguration: {
        Type: 'S3',
        S3Configuration: Match.objectLike({ InclusionPrefixes: ['sheets/'] }),
      },
      DataDeletionPolicy: 'DELETE',
    });
  });

  it('lets the Knowledge Base role read sheets/ only and use the sheets index only', () => {
    const role = Object.entries(template.findResources('AWS::IAM::Role')).find(([id]) =>
      id.startsWith('ProductSheetsKbRole'),
    )!;
    const trust = JSON.stringify(role[1].Properties.AssumeRolePolicyDocument);
    expect(trust).toContain('aws:SourceAccount');
    expect(trust).toContain('knowledge-base/*');
    const policy = Object.entries(template.findResources('AWS::IAM::Policy')).find(([id]) =>
      id.startsWith('ProductSheetsKbRole'),
    )!;
    const json = JSON.stringify(policy[1].Properties.PolicyDocument);
    expect(json).toContain('/sheets/*');
    expect(json).not.toContain('s3:PutObject');
    expect(json).toContain('ProductSheetsIndex');
    expect(json).not.toContain('ProductsIndex');
  });

  it('publishes the Knowledge Base and data source ids to SSM', () => {
    for (const name of ['productSheetsKbId', 'productSheetsDataSourceId']) {
      template.hasResourceProperties('AWS::SSM::Parameter', { Name: `/suppliagent/dev/${name}` });
    }
  });
});
