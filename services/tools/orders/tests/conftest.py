"""Moto tables with the real seed data; events captured; the clock fixed (Wed 28/10 10:00 Rome)."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import boto3
import pytest
import suppliagent_tool_orders.orders as orders
from moto import mock_aws
from suppliagent_shared.aws import reset_clients

SEED = Path(__file__).parents[4] / "seed" / "data"
NOW = datetime(2026, 10, 28, 9, 0, tzinfo=UTC)
# table -> (key attributes, GSIs as (partition key, optional sort key)); mirrors data-stack.ts
TABLES: dict[str, tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]] = {
    "customers": (("customerId",), (("repId",),)),
    "contacts": (("contactId",), (("customerId",),)),
    "products": (("sku",), ()),
    "price-lists": (("priceListId", "sku"), ()),
    "promotions": (("promoId",), (("sku",),)),
    "delivery-calendar": (("zone", "date"), ()),
    "orders": (
        ("orderId",),
        (("customerId", "createdAt"), ("status", "updatedAt"), ("repId",)),
    ),
    "deliveries": (("orderId",), ()),
    "messages": (("conversationId", "tsMessageId"), ()),
    "issues": (("issueId",), (("orderId",),)),
}


def _create(
    resource: Any, name: str, key: tuple[str, ...], gsis: tuple[tuple[str, ...], ...]
) -> Any:
    attributes = set(key) | {a for g in gsis for a in g}
    extra: dict[str, Any] = {}
    if gsis:
        extra["GlobalSecondaryIndexes"] = [
            {
                "IndexName": f"by-{g[0]}",
                "KeySchema": [
                    {"AttributeName": a, "KeyType": "HASH" if i == 0 else "RANGE"}
                    for i, a in enumerate(g)
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
            for g in gsis
        ]
    return resource.create_table(
        TableName=f"suppliagent-test-{name}",
        KeySchema=[{"AttributeName": key[0], "KeyType": "HASH"}]
        + [{"AttributeName": k, "KeyType": "RANGE"} for k in key[1:]],
        AttributeDefinitions=[
            {"AttributeName": a, "AttributeType": "S"} for a in sorted(attributes)
        ],
        BillingMode="PAY_PER_REQUEST",
        **extra,
    )


@pytest.fixture(autouse=True)
def aws(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    for name, value in {
        "AWS_DEFAULT_REGION": "eu-west-1",
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "TABLE_PREFIX": "suppliagent-test-",
        "EVENT_BUS_NAME": "suppliagent-test-events",
        "DELIVERY_CUTOFF": "18:00",
        "MIN_ORDER_VALUE": "80",
        "MEDIA_BUCKET": "media-bucket",
    }.items():
        monkeypatch.setenv(name, value)
    with mock_aws():
        reset_clients()
        resource: Any = boto3.resource("dynamodb")
        for name, (key, gsis) in TABLES.items():
            table = _create(resource, name, key, gsis)
            seed = SEED / f"{name}.json"
            if seed.exists():
                with table.batch_writer() as batch:
                    for item in json.loads(seed.read_text(), parse_float=Decimal):
                        batch.put_item(Item=item)
        yield resource
        reset_clients()


class Clock:
    now = NOW


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> type[Clock]:
    Clock.now = NOW
    monkeypatch.setattr(orders, "_now", lambda: Clock.now)
    return Clock


@pytest.fixture(autouse=True)  # no test may reach EventBridge
def events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    sent: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(orders, "put_event", lambda _src, kind, detail: sent.append((kind, detail)))
    return sent
