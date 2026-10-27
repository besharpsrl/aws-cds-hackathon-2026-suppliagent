"""Restore the demo scenario of an environment (T-04): clear what the demo creates, reload the seed.

Usage: uv run python seed/reset.py --env dev [--profile NAME] [--skip-index]

Deletes every item of Orders, Deliveries and Issues (conversations and contacts are kept), runs the
seed and then rebuilds the product index (`catalog-indexer`, mode `full`). Synthetic data only.
"""

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

import boto3

# seed.py as a module, wherever the script is run from
_spec = importlib.util.spec_from_file_location("seed_script", Path(__file__).with_name("seed.py"))
if _spec is None or _spec.loader is None:
    raise SystemExit("seed/seed.py not found")
seed_script: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed_script)

CLEARED = {"orders": ("orderId",), "deliveries": ("orderId",), "issues": ("issueId",)}


def clear(dynamodb: Any, env: str) -> None:
    for stem, key in CLEARED.items():
        table = dynamodb.Table(f"suppliagent-{env}-{stem}")
        with table.batch_writer() as batch:
            for page in table.meta.client.get_paginator("scan").paginate(
                TableName=table.name, ProjectionExpression=", ".join(key)
            ):
                for item in page["Items"]:
                    batch.delete_item(Key={k: item[k] for k in key})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env", required=True, choices=["dev"])
    parser.add_argument("--profile")
    parser.add_argument("--region", default="eu-west-1")
    parser.add_argument("--skip-index", action="store_true")
    args = parser.parse_args()
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    dynamodb = session.resource("dynamodb")
    clear(dynamodb, args.env)
    data = seed_script.load()
    seed_script.write(dynamodb, args.env, data)
    print(f"{args.env}: orders cleared, {sum(map(len, data.values()))} seed items loaded")
    if not args.skip_index:
        out = session.client("lambda").invoke(
            FunctionName=f"suppliagent-{args.env}-catalog-indexer",
            Payload=json.dumps({"mode": "full"}).encode(),
        )
        print("catalog-indexer:", out["Payload"].read().decode())


if __name__ == "__main__":
    main()
