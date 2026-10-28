"""Load the synthetic demo data in seed/data into the DynamoDB tables of an environment (T-04).

Usage: uv run python seed/seed.py --env dev [--profile NAME] [--skip-sheets]

Items are validated against the shared models and written with PutItem, so re-running is safe.
Optional extra items (e.g. the real demo phone number) go in seed/private/<table>.json, git-ignored.
The synthetic technical sheets (seed/data/sheets, T-06b) go to `catalog-assets/sheets/` and the
Knowledge Base ingestion is started (ids from SSM); it runs for a minute or two in the background.
A sheet removed from the repo stays in the bucket: delete it there too. `reset.py` leaves the
sheets alone (they are not demo state).
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
SHEETS = HERE / "data" / "sheets"
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


def sheet_files() -> list[Path]:
    """The sheets and their `.metadata.json` sidecars (sku, category: filters of the KB)."""
    return sorted(p for p in SHEETS.iterdir() if p.suffix in {".md", ".json"})


def upload_sheets(session: Any, env: str) -> str:
    """Sheets to the catalog-assets bucket, then a Knowledge Base ingestion job; its id."""
    account = session.client("sts").get_caller_identity()["Account"]
    bucket = f"suppliagent-{env}-catalog-assets-{account}"
    s3 = session.client("s3")
    for path in sheet_files():
        kind = "application/json" if path.suffix == ".json" else "text/markdown; charset=utf-8"
        s3.put_object(
            Bucket=bucket, Key=f"sheets/{path.name}", Body=path.read_bytes(), ContentType=kind
        )
    ssm = session.client("ssm")
    kb_id, source_id = (
        ssm.get_parameter(Name=f"/suppliagent/{env}/{name}")["Parameter"]["Value"]
        for name in ("productSheetsKbId", "productSheetsDataSourceId")
    )
    agent = session.client("bedrock-agent")
    try:
        job = agent.start_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=source_id)
    except agent.exceptions.ConflictException:
        return "already running (run seed.py again later to pick up changed sheets)"
    return str(job["ingestionJob"]["ingestionJobId"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env", required=True, choices=["dev"])
    parser.add_argument("--profile")
    parser.add_argument("--region", default="eu-west-1")
    parser.add_argument("--skip-sheets", action="store_true")
    args = parser.parse_args()
    data = load()
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    write(session.resource("dynamodb"), args.env, data)
    for stem, items in data.items():
        print(f"suppliagent-{args.env}-{stem}: {len(items)} items")
    if not args.skip_sheets:
        job = upload_sheets(session, args.env)
        print(f"sheets: {len(sheet_files()) // 2} uploaded, ingestion job {job}")


if __name__ == "__main__":
    main()
