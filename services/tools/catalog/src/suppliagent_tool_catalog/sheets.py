"""ask_product_sheets (T-44b, FN-21, F-10.B): passages of the technical sheets (Bedrock Knowledge
Base on S3 Vectors, T-06b) that answer a question about allergens, ingredients, storage, shelf
life or use, each with the sheet it comes from for the citation. `NOT_FOUND` when no sheet is close
enough: the agent then says the information is not in the sheets, never guesses.

Every known role (customers too, FN-21): the sheets hold no internal data (no prices, stock or
customers), and nothing else is read here.

Environment: `KNOWLEDGE_BASE_ID`, `EVENT_BUS_NAME`, `TABLE_PREFIX`.
"""

# ruff: noqa: N815 - field names are the camelCase wire names (02 §6).

import os
from functools import cache
from typing import Any

import boto3
from pydantic import Field
from suppliagent_shared.aws import put_event, table
from suppliagent_shared.models import Role

from suppliagent_tool_catalog.catalog import SOURCE, ToolInput, _require_customer_access

MAX_PASSAGES = 3
PASSAGE_CHARS = 2000
# ponytail: first guess from the demo sheets (a matching sheet scores ~0.7-0.8, an unrelated
# question ~0.4-0.5); calibrate with questions that have no answer in the sheets (FN-21).
MIN_SCORE = 0.55


class AskProductSheetsInput(ToolInput):
    question: str = Field(min_length=1, max_length=500)
    sku: str | None = Field(None, pattern=r"^[A-Z0-9][A-Z0-9-]{0,39}$")


@cache
def _kb() -> Any:
    return boto3.client("bedrock-agent-runtime")


def ask_product_sheets(args: AskProductSheetsInput) -> dict[str, Any]:
    _require_customer_access(args.caller)
    search: dict[str, Any] = {"numberOfResults": MAX_PASSAGES}
    if args.sku:
        search["filter"] = {"equals": {"key": "sku", "value": args.sku}}
    response = _kb().retrieve(
        knowledgeBaseId=os.environ["KNOWLEDGE_BASE_ID"],
        retrievalQuery={"text": args.question},
        retrievalConfiguration={"vectorSearchConfiguration": search},
    )
    passages = []
    for result in response.get("retrievalResults", []):
        score = float(result.get("score", 0))
        sku = str((result.get("metadata") or {}).get("sku", ""))
        if score < MIN_SCORE or not sku:
            continue
        product = table("products").get_item(Key={"sku": sku}).get("Item") or {}
        passages.append(
            {
                "sku": sku,
                "sheet": f"Scheda tecnica – {product.get('name', sku)}",
                "text": str(result.get("content", {}).get("text", ""))[:PASSAGE_CHARS],
                "score": round(score, 2),
            }
        )
    if args.caller.role is Role.SALES_REP:  # copilot usage (02 §6.4)
        put_event(SOURCE, "rep.query", {"repId": args.caller.contactId, "type": "sheets"})
    if not passages:
        return {"status": "NOT_FOUND", "passages": []}
    return {"status": "FOUND", "passages": passages}
