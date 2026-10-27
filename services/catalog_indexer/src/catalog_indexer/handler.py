"""Lambda entry point: `{"mode": "full"}` reindexes all, `{"skus": [...]}` only those SKUs."""

from typing import Any

from catalog_indexer.indexer import index_products


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, int]:
    skus = event.get("skus")
    if skus is not None:
        if not isinstance(skus, list) or not all(isinstance(s, str) for s in skus):
            raise ValueError("skus must be a list of strings")
        return index_products(skus)
    if event.get("mode") != "full":
        raise ValueError('expected {"mode": "full"} or {"skus": [...]}')
    return index_products()
