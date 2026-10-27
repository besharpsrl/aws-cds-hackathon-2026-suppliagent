"""Product index (T-06, FN-07, INFRASTRUCTURE_DESIGN §5.4): one S3 Vectors vector per active SKU.

Environment: `TABLE_PREFIX`, `VECTOR_BUCKET_NAME`, `INDEX_NAME`.
"""

import json
import os
from collections.abc import Iterable, Iterator
from functools import cache
from typing import Any

import boto3
from aws_lambda_powertools import Logger
from suppliagent_shared.aws import table

logger = Logger(service="catalog-indexer")

EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
DIMENSIONS = 1024
PUT_BATCH = 500  # S3 Vectors PutVectors/DeleteVectors limit
DELETE_BATCH = 500


@cache
def _bedrock() -> Any:
    return boto3.client("bedrock-runtime")


@cache
def _vectors() -> Any:
    return boto3.client("s3vectors")


def product_document(item: dict[str, Any]) -> str:
    """Text that gets embedded: name, brand, category, format, unit, synonyms, description."""
    parts = [
        item.get("name"),
        item.get("brand"),
        item.get("category"),
        item.get("format"),
        f"venduto a {item['unit']}" if item.get("unit") else None,
        ", ".join(item.get("synonyms") or []) or None,
        item.get("description"),
    ]
    return ". ".join(str(p) for p in parts if p)


def _embed(text: str) -> list[float]:
    response = _bedrock().invoke_model(
        modelId=EMBEDDING_MODEL_ID,
        body=json.dumps({"inputText": text, "dimensions": DIMENSIONS, "normalize": True}),
    )
    embedding: list[float] = json.loads(response["body"].read())["embedding"]
    return embedding


def _vector(item: dict[str, Any]) -> dict[str, Any]:
    text = product_document(item)
    metadata = {"text": text, "active": True}  # `text` is non-filterable (CatalogStack)
    for field in ("category", "unit"):
        if item.get(field):
            metadata[field] = str(item[field])
    return {"key": item["sku"], "data": {"float32": _embed(text)}, "metadata": metadata}


def _chunks(items: list[Any], size: int) -> Iterator[list[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def index_items(items: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Upserts active items and deletes the inactive ones. Boto retries transient errors."""
    active = [item for item in items if item.get("active", True)]
    inactive = [item["sku"] for item in items if not item.get("active", True)]
    return _write(active, inactive)


def _write(active: list[dict[str, Any]], remove: list[str]) -> dict[str, int]:
    bucket, index = os.environ["VECTOR_BUCKET_NAME"], os.environ["INDEX_NAME"]
    for batch in _chunks(active, PUT_BATCH):
        _vectors().put_vectors(
            vectorBucketName=bucket, indexName=index, vectors=[_vector(i) for i in batch]
        )
    for batch in _chunks(remove, DELETE_BATCH):
        _vectors().delete_vectors(vectorBucketName=bucket, indexName=index, keys=batch)
    return {"indexed": len(active), "deleted": len(remove)}


def index_products(skus: list[str] | None = None) -> dict[str, int]:
    """Full run (scan of Products) or only `skus`. SKUs missing from the table are deleted from the
    index; a full run cannot see them (ponytail: no list_vectors sweep, `reset.py` recreates the
    index data when the catalog is reseeded)."""
    products = table("products")
    if skus is None:
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {}
        while True:
            page = products.scan(**kwargs)
            items += page["Items"]
            if "LastEvaluatedKey" not in page:
                break
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        result = index_items(items)
    else:
        found = {}
        for sku in skus:
            item = products.get_item(Key={"sku": sku}).get("Item")
            if item:
                found[sku] = item
        gone = [sku for sku in skus if sku not in found]
        active = [i for i in found.values() if i.get("active", True)]
        inactive = [i["sku"] for i in found.values() if not i.get("active", True)]
        result = _write(active, inactive + gone)
    logger.info("catalog indexed", extra=result)
    return result
