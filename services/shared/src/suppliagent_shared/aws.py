"""AWS access shared by Lambdas: DynamoDB tables by short name, application events (02 §6.4).

Environment: `TABLE_PREFIX` (e.g. `suppliagent-dev-`), `EVENT_BUS_NAME`.
"""

import json
import os
from functools import cache
from typing import Any

import boto3


@cache
def _dynamodb() -> Any:
    return boto3.resource("dynamodb")


@cache
def _events() -> Any:
    return boto3.client("events")


def table(name: str) -> Any:
    """Table by its kebab-case short name, e.g. `table("customers")`."""
    return _dynamodb().Table(os.environ["TABLE_PREFIX"] + name)


def put_event(source: str, detail_type: str, detail: dict[str, Any]) -> None:
    """Application event; `source` is `suppliagent.<component>`, detail holds IDs only (no PII)."""
    _events().put_events(
        Entries=[
            {
                "Source": source,
                "DetailType": detail_type,
                "Detail": json.dumps(detail),
                "EventBusName": os.environ["EVENT_BUS_NAME"],
            }
        ]
    )


def reset_clients() -> None:
    """For tests: drop cached clients so they bind to the current mock."""
    _dynamodb.cache_clear()
    _events.cache_clear()
