"""Moto tables loaded with the committed seed data (seed/data)."""

import json
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import boto3
import pytest
from moto import mock_aws
from suppliagent_shared.aws import reset_clients

SEED = Path(__file__).parents[4] / "seed" / "data"
# table short name -> (key attributes, GSI partition keys); mirrors infra/lib/stacks/data-stack.ts
TABLES = {
    "customers": (("customerId",), ("repId",)),
    "contacts": (("contactId",), ("customerId",)),
    "channel-identities": (("channelAddress",), ("contactId",)),
    "order-history": (("customerId", "dateOrderId"), ()),
    "customer-insights": (("customerId",), ()),
    "conversations": (("conversationId",), ("contactId",)),
}


def _create(resource: Any, name: str, key: tuple[str, ...], gsis: tuple[str, ...]) -> Any:
    extra: dict[str, Any] = {}
    if gsis:
        extra["GlobalSecondaryIndexes"] = [
            {
                "IndexName": f"by-{g}",
                "KeySchema": [{"AttributeName": g, "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }
            for g in gsis
        ]
    return resource.create_table(
        TableName=f"suppliagent-test-{name}",
        KeySchema=[{"AttributeName": key[0], "KeyType": "HASH"}]
        + [{"AttributeName": k, "KeyType": "RANGE"} for k in key[1:]],
        AttributeDefinitions=[
            {"AttributeName": a, "AttributeType": "S"} for a in sorted(set(key) | set(gsis))
        ],
        BillingMode="PAY_PER_REQUEST",
        **extra,
    )


@pytest.fixture(autouse=True)
def aws(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("TABLE_PREFIX", "suppliagent-test-")
    monkeypatch.setenv("EVENT_BUS_NAME", "suppliagent-test-events")
    with mock_aws():
        reset_clients()
        resource: Any = boto3.resource("dynamodb")
        for name, (key, gsis) in TABLES.items():
            table = _create(resource, name, key, gsis)
            seed = SEED / f"{name}.json"
            items = json.loads(seed.read_text(), parse_float=Decimal) if seed.exists() else []
            with table.batch_writer() as batch:
                for item in items:
                    batch.put_item(Item=item)
        boto3.client("events").create_event_bus(Name="suppliagent-test-events")
        yield resource
        reset_clients()
