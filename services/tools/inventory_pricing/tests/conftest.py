"""Moto tables loaded with the real seed data (customers, catalog, prices, stock, calendar)."""

import json
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import boto3
import pytest
import suppliagent_tool_inventory_pricing.inventory as inventory
from moto import mock_aws
from suppliagent_shared.aws import reset_clients

SEED = Path(__file__).parents[4] / "seed" / "data"
# table short name -> (key attributes, GSI partition keys); mirrors infra/lib/stacks/data-stack.ts
TABLES = {
    "customers": (("customerId",), ("repId",)),
    "contacts": (("contactId",), ("customerId",)),
    "products": (("sku",), ()),
    "stock": (("sku",), ()),
    "price-lists": (("priceListId", "sku"), ()),
    "promotions": (("promoId",), ("sku",)),
    "delivery-calendar": (("zone", "date"), ()),
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
    for name, value in {
        "AWS_DEFAULT_REGION": "eu-west-1",
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "TABLE_PREFIX": "suppliagent-test-",
        "DELIVERY_CUTOFF": "18:00",
        "MIN_ORDER_VALUE": "80",
    }.items():
        monkeypatch.setenv(name, value)
    with mock_aws():
        reset_clients()
        resource: Any = boto3.resource("dynamodb")
        for name, (key, gsis) in TABLES.items():
            table = _create(resource, name, key, gsis)
            items = json.loads((SEED / f"{name}.json").read_text(), parse_float=Decimal)
            with table.batch_writer() as batch:
                for item in items:
                    batch.put_item(Item=item)
        yield resource
        reset_clients()


@pytest.fixture(autouse=True)
def today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inventory, "_today", lambda: date(2026, 10, 28))
