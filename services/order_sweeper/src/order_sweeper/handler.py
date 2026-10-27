"""Order sweeper (T-47, FN-12, F-07.C4): a summary waiting for the customer's "Confermo".

Run by a schedule every few minutes over the orders in `PENDING_CONFIRMATION`:
- `PENDING_REMINDER_HOURS` after the summary was shown: one reminder (once per summary);
- at the end of that day (local midnight): the order becomes `EXPIRED` and the customer is told
  that nothing was sent. Nothing is ever confirmed here.
Nothing is written to the customer during the quiet hours (`QUIET_HOURS`, F-11.C6): the sweep that
follows at the end of them does both, expiry first. Messages go through the Notifier, in the
customer's conversation: outside the WhatsApp 24 h window they are not delivered (templates:
T-29), the order still expires.

Environment: `TABLE_PREFIX`, `EVENT_BUS_NAME`, `NOTIFIER_FUNCTION_NAME`, `PENDING_REMINDER_HOURS`,
`QUIET_HOURS` (`HH:MM-HH:MM`, Europe/Rome).
"""

import json
import os
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from functools import cache
from typing import Any

import boto3
from aws_lambda_powertools import Logger
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from suppliagent_shared.aws import put_event, table
from suppliagent_shared.delivery import ROME, parse_cutoff, rome
from suppliagent_shared.orders import check_transition

logger = Logger(service="order-sweeper")
SOURCE = "suppliagent.order-sweeper"
# errors after which sending again is pointless (the Notifier recorded why)
PERMANENT_NOTIFIER_ERRORS = {"AccessDeniedError", "ChannelUnavailableError", "InvalidInputError"}
TEXTS = {
    "it": {
        "reminder": "Il riepilogo del tuo ordine ({lines} righe, consegna il {day}) è ancora in "
        "attesa di conferma. Rispondi «Confermo» per inviarlo o «Modifica» per cambiare qualcosa.",
        "expired": "Il riepilogo del tuo ordine non è stato confermato ed è scaduto: nessun ordine "
        "è stato inviato. Scrivimi quando vuoi riordinare.",
    },
    "en": {
        "reminder": "The summary of your order ({lines} lines, delivery on {day}) is still waiting "
        "for your confirmation. Reply “Confirm” to send it or “Edit” to change something.",
        "expired": "The summary of your order was not confirmed and has expired: no order was "
        "sent. Write to me whenever you want to order again.",
    },
}


@cache
def _lambda() -> Any:
    return boto3.client("lambda")


def _now() -> datetime:
    return datetime.now(UTC)


def _stamp(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _quiet(local: time) -> bool:
    start, end = (parse_cutoff(part) for part in os.environ["QUIET_HOURS"].split("-"))
    return local >= start or local < end  # the window crosses midnight


def _pending() -> list[dict[str, Any]]:
    orders: list[dict[str, Any]] = []
    query: dict[str, Any] = {
        "IndexName": "by-status",
        "KeyConditionExpression": Key("status").eq("PENDING_CONFIRMATION"),
    }
    while True:
        page = table("orders").query(**query)
        orders += page["Items"]
        if "LastEvaluatedKey" not in page:
            return orders
        query["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _language(order: dict[str, Any]) -> str:
    conversation = (
        table("conversations").get_item(Key={"conversationId": order["conversationId"]}).get("Item")
    )
    locale = str((conversation or {}).get("lastInboundLocale", "it-IT"))
    return locale.split("-")[0].lower() if locale.split("-")[0].lower() in TEXTS else "it"


def _notify(order: dict[str, Any], kind: str, key: str, **values: Any) -> bool:
    """False only for a transient failure, worth retrying at the next sweep."""
    text = TEXTS[_language(order)][kind].format(**values)
    response = _lambda().invoke(
        FunctionName=os.environ["NOTIFIER_FUNCTION_NAME"],
        Payload=json.dumps(
            {
                "kind": "reply",
                "conversationId": order["conversationId"],
                "idempotencyKey": key,
                "text": text,
            }
        ).encode(),
    )
    if response.get("FunctionError"):
        error_type = json.loads(response["Payload"].read()).get("errorType")
        logger.warning("message not sent", extra={"kind": kind, "error": error_type})
        return error_type in PERMANENT_NOTIFIER_ERRORS
    return True


def _expire(order: dict[str, Any], now: datetime) -> bool:
    check_transition("PENDING_CONFIRMATION", "EXPIRED")
    stamp = _stamp(now)
    try:
        table("orders").update_item(
            Key={"orderId": order["orderId"]},
            UpdateExpression="SET #s = :e, updatedAt = :ts, version = :next",
            # an edit since the read (version) means the customer is active: leave it
            ConditionExpression="#s = :p AND version = :v",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":e": "EXPIRED",
                ":p": "PENDING_CONFIRMATION",
                ":ts": stamp,
                ":v": int(order.get("version", 0)),
                ":next": int(order.get("version", 0)) + 1,
            },
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        return False
    put_event(
        SOURCE,
        "order.status_changed",
        {"orderId": order["orderId"], "from": "PENDING_CONFIRMATION", "to": "EXPIRED", "ts": stamp},
    )
    return True


def _expires_at(since: datetime) -> datetime:
    """End of the local day the summary was shown (F-07.C4)."""
    day: date = rome(since).date() + timedelta(days=1)
    return datetime.combine(day, time(0, 0), tzinfo=ROME)


def handler(_event: dict[str, Any], _context: Any) -> dict[str, int]:
    now = _now()
    if _quiet(rome(now).time()):
        return {}
    reminder_after = timedelta(hours=float(os.environ["PENDING_REMINDER_HOURS"]))
    done: Counter[str] = Counter()
    for order in _pending():
        since_text = order.get("pendingSince") or order["updatedAt"]
        since = datetime.fromisoformat(since_text)
        if not order.get("conversationId"):
            continue  # nobody to write to (an order made from the console)
        if now >= _expires_at(since):
            if _expire(order, now):
                _notify(order, "expired", f"expired#{order['orderId']}")
                done["expired"] += 1
        elif now >= since + reminder_after and order.get("reminderSentAt", "") < since_text:
            active = sum(
                1
                for line in order["lines"]
                if line["status"] in {"MATCHED", "SUBSTITUTED", "ADJUSTED"}
            )
            day = date.fromisoformat(order["deliveryDate"]).strftime("%d/%m")
            if _notify(
                order,
                "reminder",
                f"reminder#{order['orderId']}#{since_text}",
                lines=active,
                day=day,
            ):
                table("orders").update_item(
                    Key={"orderId": order["orderId"]},
                    UpdateExpression="SET reminderSentAt = :ts",
                    ExpressionAttributeValues={":ts": _stamp(now)},
                )
                done["reminded"] += 1
    logger.info("sweep done", extra=dict(done))
    return dict(done)
