"""Fake Bedrock Runtime and S3 Vectors clients, and a Products table in moto."""

import json
from collections.abc import Iterator
from io import BytesIO
from typing import Any

import boto3
import pytest
from catalog_indexer import indexer
from moto import mock_aws
from suppliagent_shared.aws import reset_clients

PRODUCTS: list[dict[str, Any]] = [
    {
        "sku": "MOZ-FDL-1KG",
        "name": "Fior di latte julienne 1 kg",
        "brand": "Casa Rossi",
        "category": "latticini",
        "format": "1 kg",
        "unit": "KG",
        "synonyms": ["fdl", "fior di latte"],
        "description": "Per pizza",
        "active": True,
    },
    {
        "sku": "POM-PEL-2500",
        "name": "Pomodori pelati 2,5 kg",
        "category": "conserve",
        "unit": "CT",
        "synonyms": ["pelati"],
        "active": True,
    },
    {"sku": "OLD-001", "name": "Vecchio", "category": "conserve", "unit": "PZ", "active": False},
]


class FakeBedrock:
    def __init__(self) -> None:
        self.inputs: list[str] = []

    def invoke_model(self, **kwargs: Any) -> dict[str, Any]:
        body = json.loads(kwargs["body"])
        self.inputs.append(body["inputText"])
        assert kwargs["modelId"] == "amazon.titan-embed-text-v2:0"
        assert body["dimensions"] == 1024
        return {"body": BytesIO(json.dumps({"embedding": [0.5] * 1024}).encode())}


class FakeVectors:
    def __init__(self) -> None:
        self.puts: list[dict[str, Any]] = []
        self.deletes: list[dict[str, Any]] = []

    def put_vectors(self, **kwargs: Any) -> dict[str, Any]:
        self.puts.append(kwargs)
        return {}

    def delete_vectors(self, **kwargs: Any) -> dict[str, Any]:
        self.deletes.append(kwargs)
        return {}


@pytest.fixture
def bedrock(monkeypatch: pytest.MonkeyPatch) -> FakeBedrock:
    fake = FakeBedrock()
    monkeypatch.setattr(indexer, "_bedrock", lambda: fake)
    return fake


@pytest.fixture
def vectors(monkeypatch: pytest.MonkeyPatch) -> FakeVectors:
    fake = FakeVectors()
    monkeypatch.setattr(indexer, "_vectors", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TABLE_PREFIX", "suppliagent-test-")
    monkeypatch.setenv("VECTOR_BUCKET_NAME", "suppliagent-test-vectors")
    monkeypatch.setenv("INDEX_NAME", "products")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")


@pytest.fixture
def products_table() -> Iterator[None]:
    with mock_aws():
        reset_clients()
        boto3.resource("dynamodb").create_table(
            TableName="suppliagent-test-products",
            KeySchema=[{"AttributeName": "sku", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "sku", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        table = boto3.resource("dynamodb").Table("suppliagent-test-products")
        for item in PRODUCTS:
            table.put_item(Item=item)
        yield
    reset_clients()
