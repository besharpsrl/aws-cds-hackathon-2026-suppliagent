"""Moto tables with a small catalog and history; Bedrock embeddings and S3 Vectors are fakes."""

import json
import sys
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import boto3
import pytest
import suppliagent_tool_catalog.catalog as catalog
from moto import mock_aws
from suppliagent_shared.aws import reset_clients

# --import-mode=importlib does not put this directory on the path: the helpers are in support/
sys.path.insert(0, str(Path(__file__).parent / "support"))
from catalog_helpers import FakeBedrock, FakeVectors  # noqa: E402

SEED = Path(__file__).parents[4] / "seed" / "data"
# table short name -> (key attributes, GSI partition keys); mirrors infra/lib/stacks/data-stack.ts
TABLES = {
    "customers": (("customerId",), ("repId",)),
    "contacts": (("contactId",), ("customerId",)),
    "order-history": (("customerId", "dateOrderId"), ()),
    "products": (("sku",), ()),
    "stock": (("sku",), ()),
}

PRODUCTS = [
    {"sku": "FDL-PIZZA-1KG", "name": "Fior di latte per pizza 1 kg", "brand": "Caseificio Sole",
     "unit": "pz", "synonyms": ["mozzarella", "mozz fdl", "fior di latte"]},
    {"sku": "FDL-PIZZA-2KG", "name": "Fior di latte per pizza 2 kg", "brand": "Caseificio Sole",
     "unit": "pz", "synonyms": ["mozzarella grande"]},
    {"sku": "BUFALA-250", "name": "Mozzarella di bufala 250 g", "brand": "Bufalina",
     "unit": "pz", "synonyms": ["bufala"]},
    {"sku": "FARINA-00-25KG", "name": "Farina tipo 00 sacco 25 kg", "unit": "pz",
     "synonyms": ["farina 00"]},
    {"sku": "OLD-BURRO", "name": "Burro panetto 1 kg", "unit": "pz", "active": False},
]  # fmt: skip


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
        "EVENT_BUS_NAME": "suppliagent-test-events",
        "VECTOR_BUCKET_NAME": "vectors",
        "INDEX_NAME": "products",
        "MATCH_AUTO_THRESHOLD": "0.85",
        "MATCH_ASK_THRESHOLD": "0.5",
    }.items():
        monkeypatch.setenv(name, value)
    with mock_aws():
        reset_clients()
        resource: Any = boto3.resource("dynamodb")
        for name, (key, gsis) in TABLES.items():
            table = _create(resource, name, key, gsis)
            seed = SEED / f"{name}.json"
            items = json.loads(seed.read_text(), parse_float=Decimal) if seed.exists() else []
            if name == "products":
                items = PRODUCTS
            with table.batch_writer() as batch:
                for item in items:
                    batch.put_item(Item=item)
        yield resource
        reset_clients()


@pytest.fixture(autouse=True)
def bedrock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(catalog, "_bedrock", lambda: FakeBedrock())


@pytest.fixture(autouse=True)
def vectors(monkeypatch: pytest.MonkeyPatch) -> FakeVectors:
    fake = FakeVectors()
    monkeypatch.setattr(catalog, "_vectors", lambda: fake)
    return fake


@pytest.fixture(autouse=True)  # no test may reach EventBridge
def events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    sent: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        catalog, "put_event", lambda _src, kind, detail: sent.append((kind, detail))
    )
    return sent


@pytest.fixture
def history(aws: Any) -> Any:
    """Orders of `cus_t1`: fior di latte 1 kg in 3 orders, farina in 1; con_t1 owns cus_t1."""

    def add(customer: str, orders: list[list[str]]) -> None:
        table = aws.Table("suppliagent-test-order-history")
        for i, skus in enumerate(orders):
            table.put_item(
                Item={
                    "customerId": customer,
                    "dateOrderId": f"2026-09-{10 + i}#ord_{i}",
                    "lines": [
                        {"sku": s, "description": s, "quantity": 1, "unit": "pz"} for s in skus
                    ],
                }
            )

    aws.Table("suppliagent-test-contacts").put_item(
        Item={"contactId": "con_t1", "customerIds": ["cus_t1"], "status": "VERIFIED"}
    )
    return add
