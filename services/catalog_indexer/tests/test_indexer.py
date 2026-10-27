from typing import Any

import pytest
from catalog_indexer import indexer
from catalog_indexer.handler import lambda_handler

pytestmark = pytest.mark.usefixtures("products_table")


def test_document_has_name_brand_category_format_unit_synonyms_description() -> None:
    doc = indexer.product_document(
        {
            "sku": "MOZ-FDL-1KG",
            "name": "Fior di latte julienne 1 kg",
            "brand": "Casa Rossi",
            "category": "latticini",
            "format": "1 kg",
            "unit": "KG",
            "synonyms": ["fdl", "fior di latte"],
            "description": "Per pizza",
        }
    )
    for part in (
        "Fior di latte julienne 1 kg",
        "Casa Rossi",
        "latticini",
        "KG",
        "fdl",
        "Per pizza",
    ):
        assert part in doc


def test_document_tolerates_missing_optional_fields() -> None:
    assert indexer.product_document({"sku": "X", "name": "Solo nome"}) == "Solo nome"


def test_full_run_indexes_active_and_deletes_inactive(bedrock: Any, vectors: Any) -> None:
    result = indexer.index_products()

    assert result == {"indexed": 2, "deleted": 1}
    assert len(bedrock.inputs) == 2
    (put,) = vectors.puts
    assert put["vectorBucketName"] == "suppliagent-test-vectors"
    assert put["indexName"] == "products"
    by_key = {v["key"]: v for v in put["vectors"]}
    assert set(by_key) == {"MOZ-FDL-1KG", "POM-PEL-2500"}
    fdl = by_key["MOZ-FDL-1KG"]
    assert len(fdl["data"]["float32"]) == 1024
    assert fdl["metadata"]["category"] == "latticini"
    assert fdl["metadata"]["active"] is True
    assert "fdl" in fdl["metadata"]["text"]
    assert vectors.deletes[0]["keys"] == ["OLD-001"]


def test_put_vectors_batches_of_500(bedrock: Any, vectors: Any) -> None:
    items = [{"sku": f"S{i}", "name": f"Prodotto {i}", "active": True} for i in range(501)]
    indexer.index_items(items)
    assert [len(p["vectors"]) for p in vectors.puts] == [500, 1]


def test_skus_reindexes_only_those_and_deletes_missing(bedrock: Any, vectors: Any) -> None:
    result = indexer.index_products(["POM-PEL-2500", "GONE-1"])

    assert result == {"indexed": 1, "deleted": 1}
    assert [v["key"] for v in vectors.puts[0]["vectors"]] == ["POM-PEL-2500"]
    assert vectors.deletes[0]["keys"] == ["GONE-1"]


def test_handler_modes(bedrock: Any, vectors: Any) -> None:
    assert lambda_handler({"mode": "full"}, None) == {"indexed": 2, "deleted": 1}
    assert lambda_handler({"skus": ["POM-PEL-2500"]}, None) == {"indexed": 1, "deleted": 0}


def test_handler_rejects_invalid_event(bedrock: Any, vectors: Any) -> None:
    with pytest.raises(ValueError):
        lambda_handler({"mode": "nope"}, None)
    with pytest.raises(ValueError):
        lambda_handler({}, None)
    assert not vectors.puts
