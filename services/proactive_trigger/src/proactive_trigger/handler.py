"""Proactive Trigger (T-08, FN-19, F-13 step 2): every morning, who gets a reorder proposal.

A customer is proposed when, at the same time:
- a reorder is overdue: now >= last order + `REORDER_DUE_FACTOR` x average interval;
- it has no order in progress (C1);
- no proposal (or skip) in the last `REORDER_COOLDOWN_DAYS` days (C2): `lastProposalAt` on
  `CustomerInsights`, claimed with a conditional write before any event: two runs never emit twice;
- a verified contact of it gave the proactive consent (C4: otherwise only `reorder.skipped`, for the
  rep, under the same cooldown); pending contacts never count (no data before verification);
- not during the quiet hours (`QUIET_HOURS`, Europe/Rome).
For each one it emits `reorder.due` (customerId, contactIds, skus): the proactive turn with the
`reorder_suggestion` template is T-52. Nothing is sent from here.

Environment: `TABLE_PREFIX`, `EVENT_BUS_NAME`, `REORDER_DUE_FACTOR`, `REORDER_COOLDOWN_DAYS`,
`QUIET_HOURS` (`HH:MM-HH:MM`).
"""

import os
from collections import Counter
from datetime import UTC, datetime, time, timedelta
from typing import Any

from aws_lambda_powertools import Logger
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from suppliagent_shared.aws import put_event, table
from suppliagent_shared.delivery import parse_cutoff, rome

logger = Logger(service="proactive-trigger")
SOURCE = "suppliagent.proactive-trigger"
# an order in one of these is still "in progress" for the customer (F-13.C1)
CLOSED = frozenset({"DELIVERED", "DELIVERY_ISSUE", "CANCELLED", "EXPIRED"})


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _quiet(local: time) -> bool:
    start, end = (parse_cutoff(part) for part in os.environ["QUIET_HOURS"].split("-"))
    return local >= start or local < end  # the window crosses midnight


def _scan(name: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {}
    while True:
        page = table(name).scan(**kwargs)
        items += page["Items"]
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def overdue(insights: dict[str, Any], now: datetime, factor: float) -> list[str]:
    skus = []
    for reorder in insights.get("expectedReorders", []):
        last = datetime.fromisoformat(str(reorder["lastOrderedAt"]))
        if now >= last + timedelta(days=float(reorder["everyDays"]) * factor):
            skus.append(str(reorder["sku"]))
    return skus


def _order_in_progress(customer_id: str) -> bool:
    kwargs: dict[str, Any] = {
        "IndexName": "by-customerId",
        "KeyConditionExpression": Key("customerId").eq(customer_id),
        "ScanIndexForward": False,  # newest first: open orders are the recent ones
        "ProjectionExpression": "#s",
        "ExpressionAttributeNames": {"#s": "status"},
    }
    while True:
        page = table("orders").query(**kwargs)
        if any(item.get("status") not in CLOSED for item in page["Items"]):
            return True
        if "LastEvaluatedKey" not in page:
            return False
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _claim(customer_id: str, now: datetime, cooldown: timedelta) -> bool:
    try:
        table("customer-insights").update_item(
            Key={"customerId": customer_id},
            UpdateExpression="SET lastProposalAt = :now",
            ConditionExpression="attribute_not_exists(lastProposalAt) OR lastProposalAt <= :limit",
            ExpressionAttributeValues={
                ":now": _stamp(now),
                ":limit": _stamp(now - cooldown),
            },
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        return False
    return True


def handler(event: dict[str, Any], _context: Any) -> dict[str, int]:
    now = datetime.fromisoformat(str(event["now"])) if (event or {}).get("now") else None
    now = (now or datetime.now(UTC)).astimezone(UTC)
    if _quiet(rome(now).time()):
        return {}
    factor = float(os.environ["REORDER_DUE_FACTOR"])
    cooldown = timedelta(days=float(os.environ["REORDER_COOLDOWN_DAYS"]))
    consenting: dict[str, list[str]] = {}
    for contact in _scan("contacts"):
        if contact.get("status") == "VERIFIED" and contact.get("proactiveConsent") is True:
            for customer_id in contact.get("customerIds", []):
                consenting.setdefault(str(customer_id), []).append(str(contact["contactId"]))
    done: Counter[str] = Counter()
    for insights in sorted(_scan("customer-insights"), key=lambda i: str(i["customerId"])):
        customer_id = str(insights["customerId"])
        skus = overdue(insights, now, factor)
        if not skus:
            continue
        if _order_in_progress(customer_id):
            done["orderInProgress"] += 1
        elif not _claim(customer_id, now, cooldown):
            done["cooldown"] += 1
        elif customer_id not in consenting:
            put_event(
                SOURCE, "reorder.skipped", {"customerId": customer_id, "reason": "NO_CONSENT"}
            )
            done["noConsent"] += 1
        else:
            put_event(
                SOURCE,
                "reorder.due",
                {
                    "customerId": customer_id,
                    "contactIds": sorted(consenting[customer_id]),
                    "skus": skus,
                },
            )
            done["due"] += 1
    logger.info("proactive run done", extra=dict(done))
    return dict(done)
