"""Insights & Reorder Analyzer (T-08, FN-19, FN-20, F-13 step 1): nightly, one item per customer.

Reads `Customers`, `OrderHistory` and `Promotions`, writes `CustomerInsights` (logic in `analysis`).
Only the computed attributes are set, so what the Proactive Trigger keeps on the item
(`lastProposalAt`, the 7-day cooldown) survives the nightly run.
Run on demand for the demo with `{"asOf": "2026-10-28T02:00:00Z"}` (deterministic on the seed).

Environment: `TABLE_PREFIX`.
"""

from datetime import UTC, datetime
from typing import Any

from aws_lambda_powertools import Logger
from boto3.dynamodb.conditions import Key
from suppliagent_shared.aws import table

from insights_analyzer.analysis import analyze

logger = Logger(service="insights-analyzer")


def _scan(name: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {}
    while True:
        page = table(name).scan(**kwargs)
        items += page["Items"]
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _history(customer_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {"KeyConditionExpression": Key("customerId").eq(customer_id)}
    while True:
        page = table("order-history").query(**kwargs)
        items += page["Items"]
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _as_of(event: dict[str, Any]) -> datetime:
    if event.get("asOf"):
        return datetime.fromisoformat(str(event["asOf"])).astimezone(UTC)
    return datetime.now(UTC)


def handler(event: dict[str, Any], _context: Any) -> dict[str, int]:
    as_of = _as_of(event or {})
    customers = sorted(_scan("customers"), key=lambda c: str(c["customerId"]))
    history = {c["customerId"]: _history(c["customerId"]) for c in customers}
    insights = analyze(customers, history, _scan("promotions"), as_of)
    for item in insights:
        table("customer-insights").update_item(
            Key={"customerId": item["customerId"]},
            UpdateExpression="SET expectedReorders = :e, droppedProducts = :d, "
            "suggestions = :s, updatedAt = :u",
            ExpressionAttributeValues={
                ":e": item["expectedReorders"],
                ":d": item["droppedProducts"],
                ":s": item["suggestions"],
                ":u": item["updatedAt"],
            },
        )
    result = {
        "customers": len(insights),
        "expectedReorders": sum(len(i["expectedReorders"]) for i in insights),
        "droppedProducts": sum(len(i["droppedProducts"]) for i in insights),
    }
    logger.info("insights updated", extra=result)
    return result
