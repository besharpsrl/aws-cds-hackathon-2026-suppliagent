import { RemovalPolicy, Stack, type StackProps } from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import type { IKey } from 'aws-cdk-lib/aws-kms';
import type { Construct } from 'constructs';
import type { EnvConfig } from '../../config/environments.js';

export interface DataStackProps extends StackProps {
  readonly config: EnvConfig;
  readonly key: IKey;
}

type Key = string | [partitionKey: string, sortKey: string];

interface TableSpec {
  readonly name: string;
  readonly key: Key;
  readonly indexes?: readonly Key[];
  readonly stream?: boolean;
  readonly ttl?: boolean;
}

// docs/INFRASTRUCTURE_DESIGN.md §5.7. All attributes are strings.
export const TABLES = [
  { name: 'Customers', key: 'customerId', indexes: ['repId', 'zone'] },
  { name: 'Contacts', key: 'contactId', indexes: ['customerId'] },
  { name: 'ChannelIdentities', key: 'channelAddress', indexes: ['contactId'] },
  { name: 'SalesReps', key: 'repId' },
  { name: 'Products', key: 'sku', indexes: ['category'] },
  { name: 'PriceLists', key: ['priceListId', 'sku'] },
  { name: 'Promotions', key: 'promoId', indexes: ['sku'] },
  { name: 'Stock', key: 'sku' },
  { name: 'DeliveryCalendar', key: ['zone', 'date'] },
  {
    name: 'Orders',
    key: 'orderId',
    indexes: [['customerId', 'createdAt'], ['status', 'updatedAt'], 'repId'],
    stream: true,
  },
  { name: 'OrderHistory', key: ['customerId', 'dateOrderId'] },
  { name: 'CustomerInsights', key: 'customerId' },
  { name: 'Deliveries', key: 'orderId', indexes: ['date'] },
  { name: 'Issues', key: 'issueId', indexes: ['orderId'] },
  { name: 'Conversations', key: 'conversationId', indexes: ['contactId'] },
  {
    name: 'Messages',
    key: ['conversationId', 'tsMessageId'],
    indexes: ['providerMessageId'],
    stream: true,
  },
  { name: 'TurnBuffer', key: 'conversationId', ttl: true },
  { name: 'WsConnections', key: 'connectionId', indexes: ['userId'], ttl: true },
] as const satisfies readonly TableSpec[];

export type TableName = (typeof TABLES)[number]['name'];

const attr = (name: string): dynamodb.Attribute => ({
  name,
  type: dynamodb.AttributeType.STRING,
});

const keySchema = (key: Key) => {
  const [pk, sk] = typeof key === 'string' ? [key] : key;
  return { partitionKey: attr(pk), sortKey: sk ? attr(sk) : undefined };
};

const kebab = (name: string): string => name.replace(/([a-z])([A-Z])/g, '$1-$2').toLowerCase();

export class DataStack extends Stack {
  readonly tables: Record<TableName, dynamodb.TableV2>;

  constructor(scope: Construct, id: string, props: DataStackProps) {
    super(scope, id, props);
    const { config, key } = props;

    this.tables = Object.fromEntries(
      (TABLES as readonly TableSpec[]).map((spec) => [
        spec.name,
        new dynamodb.TableV2(this, spec.name, {
          tableName: `suppliagent-${config.envName}-${kebab(spec.name)}`,
          ...keySchema(spec.key),
          billing: dynamodb.Billing.onDemand(),
          pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
          encryption: dynamodb.TableEncryptionV2.customerManagedKey(key),
          dynamoStream: spec.stream ? dynamodb.StreamViewType.NEW_AND_OLD_IMAGES : undefined,
          timeToLiveAttribute: spec.ttl ? 'expiresAt' : undefined,
          globalSecondaryIndexes: spec.indexes?.map((index) => ({
            indexName: `by-${typeof index === 'string' ? index : index[0]}`,
            ...keySchema(index),
          })),
          // Data is recreated by seed/seed.py and seed/reset.py (T-04).
          removalPolicy: RemovalPolicy.DESTROY,
        }),
      ]),
    ) as Record<TableName, dynamodb.TableV2>;
  }
}
