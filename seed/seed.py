"""Load the synthetic demo data in seed/data into the DynamoDB tables of an environment (T-04).

Usage: uv run python seed/seed.py --env dev [--profile NAME]

Items are validated against the shared models and written with PutItem, so re-running is safe.
Optional extra items (e.g. the real demo phone number) go in seed/private/<table>.json, git-ignored.
"""

import argparse
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import boto3
from suppliagent_shared.models import (
    ChannelIdentity,
    Contact,
    Customer,
    CustomerInsights,
    DeliveryCalendarEntry,
    Item,
    OrderHistoryEntry,
    PriceListEntry,
    Product,
    Promotion,
    SalesRep,
    StockItem,
)

HERE = Path(__file__).parent
# File stem = table name suffix: suppliagent-<env>-<stem>.
MODELS: dict[str, type[Item]] = {
    "customers": Customer,
    "contacts": Contact,
    "channel-identities": ChannelIdentity,
    "sales-reps": SalesRep,
    "order-history": OrderHistoryEntry,
    "customer-insights": CustomerInsights,
    "products": Product,
    "price-lists": PriceListEntry,
    "promotions": Promotion,
    "stock": StockItem,
    "delivery-calendar": DeliveryCalendarEntry,
}


def load() -> dict[str, list[dict[str, Any]]]:
    """Validated items per table, as DynamoDB-ready dicts (floats as Decimal, no nulls)."""
    data = {}
    for stem, model in MODELS.items():
        raw = json.loads((HERE / "data" / f"{stem}.json").read_text(encoding="utf-8"))
        private = HERE / "private" / f"{stem}.json"
        if private.exists():
            raw += json.loads(private.read_text(encoding="utf-8"))
        data[stem] = [
            json.loads(
                model.model_validate(item).model_dump_json(exclude_none=True), parse_float=Decimal
            )
            for item in raw
        ]
    return data


def write(dynamodb: Any, env: str, data: dict[str, list[dict[str, Any]]]) -> None:
    for stem, items in data.items():
        with dynamodb.Table(f"suppliagent-{env}-{stem}").batch_writer() as batch:
            for item in items:
                batch.put_item(Item=item)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env", required=True, choices=["dev", "demo"])
    parser.add_argument("--profile")
    parser.add_argument("--region", default="eu-west-1")
    args = parser.parse_args()
    data = load()
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    write(session.resource("dynamodb"), args.env, data)
    for stem, items in data.items():
        print(f"suppliagent-{args.env}-{stem}: {len(items)} items")


if __name__ == "__main__":
    main()
