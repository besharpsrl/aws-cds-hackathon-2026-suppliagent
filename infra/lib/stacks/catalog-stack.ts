import * as path from 'node:path';
import { CfnOutput, Duration, Stack, type StackProps } from 'aws-cdk-lib';
import type * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as iam from 'aws-cdk-lib/aws-iam';
import type { IKey } from 'aws-cdk-lib/aws-kms';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as s3vectors from 'aws-cdk-lib/aws-s3vectors';
import type { Construct } from 'constructs';
import type { EnvConfig } from '../../config/environments.js';
import { PythonLambda } from '../constructs/python-lambda.js';
import { REPO_ROOT, uvBundling } from '../constructs/uv-bundling.js';

export interface CatalogStackProps extends StackProps {
  readonly config: EnvConfig;
  readonly key: IKey;
  readonly productsTable: dynamodb.ITableV2;
}

/** Embedding model of the product index (Titan Text Embeddings V2, 1024 dimensions). */
export const EMBEDDING_MODEL_ID = 'amazon.titan-embed-text-v2:0';
export const EMBEDDING_DIMENSIONS = 1024;

/**
 * Product index (T-06, FN-07; INFRASTRUCTURE_DESIGN §5.4): S3 Vectors bucket + index `products` and
 * the `catalog-indexer` Lambda. The Knowledge Base on the technical sheets is a later task.
 */
export class CatalogStack extends Stack {
  readonly vectorBucketName: string;
  readonly productsIndexArn: string;
  readonly indexer: lambda.IFunction;

  constructor(scope: Construct, id: string, props: CatalogStackProps) {
    super(scope, id, props);
    const { config, key, productsTable } = props;
    const prefix = `suppliagent-${config.envName}`;

    const bucket = new s3vectors.CfnVectorBucket(this, 'VectorBucket', {
      vectorBucketName: `${prefix}-vectors-${this.account}`,
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
    this.vectorBucketName = bucket.ref;
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

    new CfnOutput(this, 'VectorBucketName', { value: this.vectorBucketName });
    new CfnOutput(this, 'IndexerFunctionName', { value: indexer.function.functionName });
  }
}
