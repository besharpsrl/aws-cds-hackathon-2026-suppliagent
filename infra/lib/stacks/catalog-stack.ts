import * as path from 'node:path';
import { CfnOutput, Duration, Stack, Validations, type StackProps } from 'aws-cdk-lib';
import * as bedrock from 'aws-cdk-lib/aws-bedrock';
import type * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as iam from 'aws-cdk-lib/aws-iam';
import type { IKey } from 'aws-cdk-lib/aws-kms';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import type { IBucket } from 'aws-cdk-lib/aws-s3';
import * as s3vectors from 'aws-cdk-lib/aws-s3vectors';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import type { Construct } from 'constructs';
import type { EnvConfig } from '../../config/environments.js';
import { PythonLambda } from '../constructs/python-lambda.js';
import { REPO_ROOT, uvBundling } from '../constructs/uv-bundling.js';

export interface CatalogStackProps extends StackProps {
  readonly config: EnvConfig;
  readonly key: IKey;
  readonly productsTable: dynamodb.ITableV2;
  /** Technical sheets under `sheets/` (T-06b), uploaded by `seed/seed.py`. */
  readonly catalogAssetsBucket: IBucket;
}

/** Embedding model of the product index (Titan Text Embeddings V2, 1024 dimensions). */
export const EMBEDDING_MODEL_ID = 'amazon.titan-embed-text-v2:0';
export const EMBEDDING_DIMENSIONS = 1024;

/** Prefix of the technical sheets in the catalog-assets bucket (`<sku>.md` + `.metadata.json`). */
export const SHEETS_PREFIX = 'sheets/';

/**
 * Product index (T-06, FN-07; INFRASTRUCTURE_DESIGN §5.4): S3 Vectors bucket + index `products` and
 * the `catalog-indexer` Lambda. Technical sheets (T-06b, FN-21): Bedrock Knowledge Base on the same
 * vector bucket (index `product-sheets`), data source `catalog-assets/sheets/`; its ids go to SSM
 * for `ask_product_sheets` (T-44b) and for the ingestion started by `seed/seed.py`.
 */
export class CatalogStack extends Stack {
  readonly vectorBucketName: string;
  readonly productsIndexArn: string;
  readonly indexer: lambda.IFunction;
  readonly knowledgeBaseId: string;
  readonly knowledgeBaseArn: string;

  constructor(scope: Construct, id: string, props: CatalogStackProps) {
    super(scope, id, props);
    const { config, key, productsTable, catalogAssetsBucket } = props;
    const prefix = `suppliagent-${config.envName}`;

    // The name, not `bucket.ref`: for S3 Vectors the Ref is the bucket ARN, and the S3 Vectors API
    // calls of the indexer and of the catalog tool take the name.
    const vectorBucketName = `${prefix}-vectors-${this.account}`;
    const bucket = new s3vectors.CfnVectorBucket(this, 'VectorBucket', {
      vectorBucketName,
      encryptionConfiguration: { sseType: 'aws:kms', kmsKeyArn: key.keyArn },
    });
    const index = new s3vectors.CfnIndex(this, 'ProductsIndex', {
      vectorBucketArn: bucket.attrVectorBucketArn,
      indexName: 'products',
      dataType: 'float32',
      dimension: EMBEDDING_DIMENSIONS,
      distanceMetric: 'cosine',
      // The document text is only returned with the hit, never filtered on (2 KB filterable limit).
      metadataConfiguration: { nonFilterableMetadataKeys: ['text'] },
    });
    this.vectorBucketName = vectorBucketName;
    this.productsIndexArn = index.attrIndexArn;

    const indexer = new PythonLambda(this, 'CatalogIndexer', {
      config,
      key,
      name: 'catalog-indexer',
      code: lambda.Code.fromAsset(
        path.join(REPO_ROOT, 'services/catalog_indexer'),
        uvBundling({
          package: 'suppliagent-catalog-indexer',
          sources: {
            'services/shared/src/suppliagent_shared': 'suppliagent_shared',
            'services/catalog_indexer/src/catalog_indexer': 'catalog_indexer',
          },
          omit: ['boto3', 'botocore', 's3transfer', 'aws-lambda-powertools'],
        }),
      ),
      handler: 'catalog_indexer.handler.lambda_handler',
      // Embeddings are one Bedrock call per SKU.
      timeout: Duration.minutes(10),
      environment: {
        TABLE_PREFIX: `${prefix}-`,
        VECTOR_BUCKET_NAME: this.vectorBucketName,
        INDEX_NAME: 'products',
      },
    });
    this.indexer = indexer.function;
    // Table only, no `index/*` wildcard of grantReadData: the indexer reads by key and scans.
    indexer.function.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['dynamodb:Scan', 'dynamodb:GetItem'],
        resources: [productsTable.tableArn],
      }),
    );
    indexer.function.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['bedrock:InvokeModel'],
        resources: [`arn:aws:bedrock:${this.region}::foundation-model/${EMBEDDING_MODEL_ID}`],
      }),
    );
    indexer.function.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['s3vectors:PutVectors', 's3vectors:DeleteVectors'],
        resources: [this.productsIndexArn],
      }),
    );
    key.grant(indexer.function, 'kms:Decrypt', 'kms:GenerateDataKey');

    // --- Knowledge Base of the technical sheets (T-06b, FN-21) ------------------------------------
    const sheetsIndex = new s3vectors.CfnIndex(this, 'ProductSheetsIndex', {
      vectorBucketArn: bucket.attrVectorBucketArn,
      indexName: 'product-sheets',
      dataType: 'float32',
      dimension: EMBEDDING_DIMENSIONS,
      distanceMetric: 'cosine',
      // Bedrock keeps the chunk text and its own metadata here; only `sku` / `category` filter.
      metadataConfiguration: {
        nonFilterableMetadataKeys: ['AMAZON_BEDROCK_TEXT', 'AMAZON_BEDROCK_METADATA'],
      },
    });
    const kbName = `${prefix}-product-sheets`;
    const kbArn = this.formatArn({
      service: 'bedrock',
      resource: 'knowledge-base',
      resourceName: '*',
    });
    const kbRole = new iam.Role(this, 'ProductSheetsKbRole', {
      assumedBy: new iam.ServicePrincipal('bedrock.amazonaws.com', {
        conditions: {
          StringEquals: { 'aws:SourceAccount': this.account },
          ArnLike: { 'aws:SourceArn': kbArn },
        },
      }),
      description: 'Bedrock Knowledge Base of the technical sheets (T-06b)',
    });
    kbRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ['bedrock:InvokeModel'],
        resources: [`arn:aws:bedrock:${this.region}::foundation-model/${EMBEDDING_MODEL_ID}`],
      }),
    );
    kbRole.addToPolicy(
      new iam.PolicyStatement({
        actions: [
          's3vectors:PutVectors',
          's3vectors:GetVectors',
          's3vectors:DeleteVectors',
          's3vectors:QueryVectors',
          's3vectors:GetIndex',
        ],
        resources: [sheetsIndex.attrIndexArn],
      }),
    );
    kbRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ['s3:ListBucket'],
        resources: [catalogAssetsBucket.bucketArn],
        conditions: { StringLike: { 's3:prefix': `${SHEETS_PREFIX}*` } },
      }),
    );
    kbRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ['s3:GetObject'],
        resources: [catalogAssetsBucket.arnForObjects(`${SHEETS_PREFIX}*`)],
      }),
    );
    key.grant(kbRole, 'kms:Decrypt', 'kms:GenerateDataKey', 'kms:DescribeKey');
    Validations.of(kbRole).acknowledge({
      id: `AwsSolutions-IAM5[Resource::${prefix}-foundation:ExportsOutputFnGetAttCatalogAssetsBucket7B5F8F10ArnD47BEC48/${SHEETS_PREFIX}*]`,
      reason: 'The Knowledge Base reads every technical sheet under sheets/ (read-only).',
    });
    const kb = new bedrock.CfnKnowledgeBase(this, 'ProductSheetsKb', {
      name: kbName,
      description: 'Synthetic technical sheets of the demo catalog: allergens, storage, use.',
      roleArn: kbRole.roleArn,
      knowledgeBaseConfiguration: {
        type: 'VECTOR',
        vectorKnowledgeBaseConfiguration: {
          embeddingModelArn: `arn:aws:bedrock:${this.region}::foundation-model/${EMBEDDING_MODEL_ID}`,
          embeddingModelConfiguration: {
            bedrockEmbeddingModelConfiguration: {
              dimensions: EMBEDDING_DIMENSIONS,
              embeddingDataType: 'FLOAT32',
            },
          },
        },
      },
      storageConfiguration: {
        type: 'S3_VECTORS',
        s3VectorsConfiguration: { indexArn: sheetsIndex.attrIndexArn },
      },
    });
    kb.node.addDependency(kbRole);
    const dataSource = new bedrock.CfnDataSource(this, 'ProductSheetsSource', {
      knowledgeBaseId: kb.attrKnowledgeBaseId,
      name: 'sheets',
      dataSourceConfiguration: {
        type: 'S3',
        s3Configuration: {
          bucketArn: catalogAssetsBucket.bucketArn,
          inclusionPrefixes: [SHEETS_PREFIX],
        },
      },
      // A sheet is short (~300 tokens): one chunk per sheet, so a hit cites the whole sheet.
      vectorIngestionConfiguration: { chunkingConfiguration: { chunkingStrategy: 'NONE' } },
      dataDeletionPolicy: 'DELETE',
    });
    this.knowledgeBaseId = kb.attrKnowledgeBaseId;
    this.knowledgeBaseArn = kb.attrKnowledgeBaseArn;
    const parameter = (name: string, value: string) =>
      new ssm.StringParameter(this, `Param${name}`, {
        parameterName: `/suppliagent/${config.envName}/${name}`,
        stringValue: value,
      });
    parameter('productSheetsKbId', kb.attrKnowledgeBaseId);
    parameter('productSheetsDataSourceId', dataSource.attrDataSourceId);

    new CfnOutput(this, 'ProductSheetsKbId', { value: kb.attrKnowledgeBaseId });
    new CfnOutput(this, 'VectorBucketName', { value: this.vectorBucketName });
    new CfnOutput(this, 'IndexerFunctionName', { value: indexer.function.functionName });
  }
}
