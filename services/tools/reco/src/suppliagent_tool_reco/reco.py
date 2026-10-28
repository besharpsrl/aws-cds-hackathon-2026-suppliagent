"""recommend_products and record_suggestion_outcome (FN-11, FN-20; F-07 step 1, F-07.C1/C2, F-10.A).

Suggestions come from data only: the nightly `CustomerInsights` (expected reorders, dropped
products, what similar venues buy; T-08) and the promotions valid today. Each one carries its reason
as a code plus the figures behind it; the agent words it.

- For an order (`orderId`): at most **one** suggestion per order, recorded on the order so a second
  call never proposes another; for a customer contact only with the proactive consent, never a
  product the customer turned down in the last 30 days. Priority: usual product the customer is due
  to reorder and left out > what similar venues buy > promotion (F-07 step 1).
- For a sales rep's briefing (`customerId`, no order): up to 3 suggestions, one per kind first
  (overdue reorders, dropped products, similar venues, promotions).

Only products that are sold, in stock and on the venue's price list are suggested.
The outcome (`record_suggestion_outcome`) is tracked on the order and as `order.suggestion` for
the KPI (02 §6.4); a refusal is kept on `CustomerInsights.rejectedSuggestions`.

Environment: `TABLE_PREFIX`, `EVENT_BUS_NAME`.
"""

# ruff: noqa: N815 - field names are the camelCase wire names (02 §6).

from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from aws_lambda_powertools import Logger
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from pydantic import BaseModel, ConfigDict, Field, model_validator
from suppliagent_shared.auth import CallerContext, require_customer_access
from suppliagent_shared.aws import put_event, table
from suppliagent_shared.delivery import rome
from suppliagent_shared.errors import AccessDeniedError, NotFoundError
from suppliagent_shared.models import Role, parse_order_id
from suppliagent_shared.orders import ACTIVE_LINES, EDITABLE
from suppliagent_shared.pricing import price_of

logger = Logger(service="tool-reco")
SOURCE = "suppliagent.tool-reco"
MAX_BRIEFING = 3
REJECTED_DAYS = 30
HISTORY_LIMIT = 30  # recent orders scanned for the last quantity of a product

REORDER_DUE, DROPPED, SIMILAR_VENUES, PROMOTION = (
    "REORDER_DUE",
    "DROPPED",
    "SIMILAR_VENUES",
    "PROMOTION",
)
ORDER_KINDS = (REORDER_DUE, SIMILAR_VENUES, PROMOTION)  # never "you stopped buying" to a customer
BRIEFING_KINDS = (REORDER_DUE, DROPPED, SIMILAR_VENUES, PROMOTION)
# The analyzer words its promotion suggestions this way (insights_analyzer.analysis): promotions
# are read live here instead, so a nightly one that has since ended is never proposed.
INSIGHT_PROMO_PREFIX = "In promozione"


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    caller: CallerContext  # set by the agent code, never by the model


class RecommendInput(ToolInput):
    orderId: str | None = Field(None, max_length=64)
    customerId: str | None = Field(None, max_length=64)

    @model_validator(mode="after")
    def _one_target(self) -> "RecommendInput":
        if (self.orderId is None) == (self.customerId is None):
            raise ValueError("exactly one of orderId, customerId")
        return self


class OutcomeInput(ToolInput):
    orderId: str = Field(max_length=64)
    accepted: bool


def _now() -> datetime:
    return datetime.now(UTC)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _emit(detail_type: str, detail: dict[str, Any]) -> None:
    try:
        put_event(SOURCE, detail_type, detail)
    except Exception:
        logger.warning("event not sent", extra={"type": detail_type})  # KPI only


def _item(name: str, **key: str) -> dict[str, Any] | None:
    item: dict[str, Any] | None = table(name).get_item(Key=key).get("Item")
    return item


def _authorized_order(caller: CallerContext, raw_id: str) -> dict[str, Any]:
    order = (
        table("orders")
        .get_item(Key={"orderId": parse_order_id(raw_id)}, ConsistentRead=True)
        .get("Item")
    )
    if not order:
        raise AccessDeniedError  # same answer as for another customer's order: no id probing
    require_customer_access(caller, order["customerId"])
    result: dict[str, Any] = order
    return result


# --- candidates ----------------------------------------------------------------------------


def _active_promotions(today: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {}
    while True:
        page = table("promotions").scan(**kwargs)
        items += page["Items"]
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    return [p for p in items if str(p["validFrom"]) <= today <= str(p["validTo"])]


def _last_bought(customer_id: str) -> dict[str, tuple[str, Decimal]]:
    """Per SKU, the day and quantity of the latest order in the seeded history."""
    found: dict[str, tuple[str, Decimal]] = {}
    orders = table("order-history").query(
        KeyConditionExpression=Key("customerId").eq(customer_id),
        ScanIndexForward=False,
        Limit=HISTORY_LIMIT,
    )["Items"]
    for order in orders:
        for line in order.get("lines", []):
            found.setdefault(str(line["sku"]), (str(order["date"]), Decimal(line["quantity"])))
    return found


def _candidates(
    customer_id: str, insights: dict[str, Any], due_by: datetime, today: str
) -> dict[str, list[dict[str, Any]]]:
    """Candidates per kind, best first; not yet filtered for the order or availability."""
    due = sorted(
        (r for r in insights.get("expectedReorders", []) if str(r["dueAt"]) <= _stamp(due_by)),
        key=lambda r: (str(r["dueAt"]), str(r["sku"])),
    )
    last = _last_bought(customer_id) if due or insights.get("droppedProducts") else {}
    by_kind: dict[str, list[dict[str, Any]]] = {kind: [] for kind in BRIEFING_KINDS}
    for r in due:
        item: dict[str, Any] = {
            "sku": str(r["sku"]),
            "reason": REORDER_DUE,
            "everyDays": int(r["everyDays"]),
            "lastOrderedAt": str(r["lastOrderedAt"]),
        }
        if r["sku"] in last:
            item["lastQuantity"] = last[r["sku"]][1]
        by_kind[REORDER_DUE].append(item)
    for sku in insights.get("droppedProducts", []):
        item = {"sku": str(sku), "reason": DROPPED}
        if sku in last:
            item["lastOrderedAt"], item["lastQuantity"] = last[sku]
        by_kind[DROPPED].append(item)
    for s in insights.get("suggestions", []):
        if not str(s.get("reason", "")).startswith(INSIGHT_PROMO_PREFIX):
            by_kind[SIMILAR_VENUES].append(
                {"sku": str(s["sku"]), "reason": SIMILAR_VENUES, "note": str(s.get("reason", ""))}
            )
    own = {str(r["sku"]) for r in insights.get("expectedReorders", [])}
    for p in sorted(_active_promotions(today), key=lambda p: (p["sku"] not in own, p["promoId"])):
        by_kind[PROMOTION].append({"sku": str(p["sku"]), "reason": PROMOTION})
    return by_kind


def _offer(candidate: dict[str, Any], price_list: str, today: str) -> dict[str, Any] | None:
    """The candidate with product and price data, or None when it cannot be ordered now."""
    sku = candidate["sku"]
    product = _item("products", sku=sku)
    stock = _item("stock", sku=sku)
    if not product or not product.get("active", True) or not stock:
        return None
    if Decimal(stock["quantity"]) <= 0:
        return None
    price = price_of(price_list, sku, today)
    if not price:
        return None
    offer: dict[str, Any] = {
        **candidate,
        **{k: product[k] for k in ("name", "brand", "format", "unit") if product.get(k)},
        "multiple": int(product.get("multiple", 1)),
        "unitPrice": price.unit,
        "finalPrice": price.final,
    }
    if price.promo:
        offer["promo"] = {
            "description": price.promo["description"],
            "promoPrice": Decimal(price.promo["promoPrice"]),
            "validTo": price.promo["validTo"],
        }
    elif candidate["reason"] == PROMOTION:
        return None  # ended since the scan (or not on this price list)
    return offer


def _pick(
    by_kind: dict[str, list[dict[str, Any]]],
    kinds: Iterable[str],
    limit: int,
    skip: set[str],
    price_list: str,
    today: str,
) -> list[dict[str, Any]]:
    """Up to `limit` offers: the best of each kind in priority order first, then the rest."""
    queues = {kind: iter(by_kind[kind]) for kind in kinds}

    def next_offer(queue: Iterator[dict[str, Any]]) -> dict[str, Any] | None:
        for candidate in queue:
            if candidate["sku"] in skip:
                continue
            skip.add(candidate["sku"])
            if offer := _offer(candidate, price_list, today):
                return offer
        return None

    picked: list[dict[str, Any]] = []
    for _round in range(limit):
        for queue in queues.values():
            if len(picked) == limit:
                return picked
            if offer := next_offer(queue):
                picked.append(offer)
    return picked


def _rejected(insights: dict[str, Any], now: datetime) -> set[str]:
    since = _stamp(now - timedelta(days=REJECTED_DAYS))
    return {str(r["sku"]) for r in insights.get("rejectedSuggestions", []) if str(r["at"]) >= since}


def _none(reason: str, **extra: Any) -> dict[str, Any]:
    return {"status": "NONE", "reason": reason, "suggestions": [], **extra}


# --- tools ---------------------------------------------------------------------------------


def recommend_products(args: RecommendInput) -> dict[str, Any]:
    caller = args.caller
    if args.orderId is None:
        if caller.role is not Role.SALES_REP:
            # FN-11: a customer gets a suggestion only within an order
            require_customer_access(caller, args.customerId)
            return _none("ORDER_REQUIRED")
        return _briefing(caller, str(args.customerId))
    order = _authorized_order(caller, args.orderId)
    return _for_order(caller, order)


def _briefing(caller: CallerContext, customer_id: str) -> dict[str, Any]:
    require_customer_access(caller, customer_id)
    customer = _item("customers", customerId=customer_id)
    if not customer:
        raise NotFoundError
    now = _now()
    today = rome(now).date().isoformat()
    insights = _item("customer-insights", customerId=customer_id) or {}
    by_kind = _candidates(customer_id, insights, now, today)
    picked = _pick(by_kind, BRIEFING_KINDS, MAX_BRIEFING, set(), customer["priceListId"], today)
    if not picked:
        return _none("NOTHING_RELEVANT", customerId=customer_id)
    return {"status": "OK", "customerId": customer_id, "suggestions": picked}


def _for_order(caller: CallerContext, order: dict[str, Any]) -> dict[str, Any]:
    order_id, customer_id = order["orderId"], order["customerId"]
    if order.get("suggestion"):
        return _none("ALREADY_SUGGESTED", orderId=order_id)  # FN-11: max 1 per order
    if order["status"] not in EDITABLE:
        return _none("ORDER_CLOSED", orderId=order_id)
    if caller.role is Role.CUSTOMER_CONTACT:
        contact = _item("contacts", contactId=str(caller.contactId)) or {}
        if contact.get("proactiveConsent") is not True:
            return _none("NO_CONSENT", orderId=order_id)
    customer = _item("customers", customerId=customer_id)
    if not customer:
        raise NotFoundError
    now = _now()
    today = rome(now).date().isoformat()
    insights = _item("customer-insights", customerId=customer_id) or {}
    # due by the delivery day: what runs out before the next delivery is what they forgot
    due_by = now
    if order.get("deliveryDate"):
        delivery = date.fromisoformat(order["deliveryDate"])
        due_by = max(now, datetime.combine(delivery, time.max, UTC))
    in_order = {
        str(line["sku"])
        for line in order.get("lines", [])
        if line.get("sku") and line["status"] in ACTIVE_LINES | {"AMBIGUOUS", "OUT_OF_STOCK"}
    }
    in_order |= {
        str(c["sku"]) for line in order.get("lines", []) for c in line.get("candidates", [])
    }
    skip = in_order | _rejected(insights, now)
    by_kind = _candidates(customer_id, insights, due_by, today)
    picked = _pick(by_kind, ORDER_KINDS, 1, skip, customer["priceListId"], today)
    if not picked:
        return _none("NOTHING_RELEVANT", orderId=order_id)
    suggestion = picked[0]
    record = {
        "sku": suggestion["sku"],
        "reason": suggestion["reason"],
        "suggestedAt": _stamp(now),
        "suggestedBy": caller.contactId,
    }
    try:
        table("orders").update_item(
            Key={"orderId": order_id},
            UpdateExpression="SET suggestion = :s",
            ConditionExpression="attribute_not_exists(suggestion) AND #status IN (:a, :b, :c)",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":s": record,
                **{f":{k}": v for k, v in zip("abc", sorted(EDITABLE), strict=True)},
            },
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        return _none("ALREADY_SUGGESTED", orderId=order_id)  # a concurrent call won
    return {"status": "OK", "orderId": order_id, "suggestions": [suggestion]}


def record_suggestion_outcome(args: OutcomeInput) -> dict[str, Any]:
    order = _authorized_order(args.caller, args.orderId)
    suggestion = order.get("suggestion")
    if not suggestion:
        return {"status": "NO_SUGGESTION", "orderId": order["orderId"]}
    if "accepted" in suggestion:
        return {
            "status": "ALREADY_RECORDED",
            "orderId": order["orderId"],
            "accepted": suggestion["accepted"],
        }
    now = _now()
    value: Decimal | None = None
    if args.accepted:
        value = next(
            (
                Decimal(line["lineTotal"])
                for line in order.get("lines", [])
                if line.get("sku") == suggestion["sku"]
                and line["status"] in ACTIVE_LINES
                and "lineTotal" in line
            ),
            None,
        )
    sets = {"accepted": args.accepted, "answeredAt": _stamp(now)}
    if value is not None:
        sets["value"] = value
    try:
        table("orders").update_item(
            Key={"orderId": order["orderId"]},
            UpdateExpression="SET " + ", ".join(f"suggestion.#{k} = :{k}" for k in sets),
            ConditionExpression="attribute_exists(suggestion) "
            "AND attribute_not_exists(suggestion.accepted)",
            ExpressionAttributeNames={f"#{k}": k for k in sets},
            ExpressionAttributeValues={f":{k}": v for k, v in sets.items()},
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        return {"status": "ALREADY_RECORDED", "orderId": order["orderId"]}
    if not args.accepted:  # F-07.C2: no insisting, on this order or the next ones
        table("customer-insights").update_item(
            Key={"customerId": order["customerId"]},
            UpdateExpression="SET rejectedSuggestions = "
            "list_append(if_not_exists(rejectedSuggestions, :empty), :new)",
            ExpressionAttributeValues={
                ":empty": [],
                ":new": [{"sku": suggestion["sku"], "at": _stamp(now)}],
            },
        )
    _emit(
        "order.suggestion",
        {
            "orderId": order["orderId"],
            "sku": suggestion["sku"],
            "reason": suggestion["reason"],
            "accepted": args.accepted,
            "value": float(value) if value is not None else None,
        },
    )
    return {
        "status": "RECORDED",
        "orderId": order["orderId"],
        "accepted": args.accepted,
        **({"value": value} if value is not None else {}),
    }
