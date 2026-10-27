"""Scripted fakes for the embedding model and S3 Vectors."""

import json
from typing import Any


class FakeBedrock:
    def invoke_model(self, **_: Any) -> dict[str, Any]:
        class Body:
            def read(self) -> bytes:
                return json.dumps({"embedding": [0.0] * 1024}).encode()

        return {"body": Body()}


class FakeVectors:
    """Returns the scripted hits (sku, cosine similarity) for every query."""

    def __init__(self) -> None:
        self.hits: list[tuple[str, float]] = []
        self.calls: list[dict[str, Any]] = []

    def query_vectors(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"vectors": [{"key": k, "distance": 1 - sim} for k, sim in self.hits]}
