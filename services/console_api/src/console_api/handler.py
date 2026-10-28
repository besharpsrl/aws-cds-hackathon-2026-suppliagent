"""Console REST API (T-60, T-62): orders for the back-office console and line corrections (FN-28).

Role comes from the Cognito authorizer claims, never from the request body (AGENTS.md §7).
`backoffice` and `judge` read everything; `sales_rep` is limited to its own portfolio (`repId`).
`judge` never writes; `backoffice` and the portfolio's `sales_rep` correct lines.

Environment: `ORDERS_TABLE`, `CUSTOMERS_TABLE`, `CONVERSATIONS_TABLE`, `MESSAGES_TABLE`,
`PRODUCTS_TABLE`, `PRICE_LISTS_TABLE`, `PROMOTIONS_TABLE`, `EVENT_BUS_NAME`,
`IMAGE_URL_TTL_SECONDS`.
"""

import json
import logging
import os
import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

logger = logging.getLogger("console_api")
READ_ALL_ROLES = {"backoffice", "judge"}
WRITE_ROLES = {"backoffice", "sales_rep"}
SUMMARY_FIELDS = ("orderId", "customerId", "repId", "status", "createdAt", "updatedAt")
UNCERTAIN_LINES = {"AMBIGUOUS", "UNMATCHED"}
UNRESOLVED_LINES = UNCERTAIN_LINES | {"OUT_OF_STOCK"}  # as in the orders tool
ACTIVE_LINES = {"MATCHED", "SUBSTITUTED", "ADJUSTED", "CONFIRMED"}
CORRECTABLE_ORDERS = {"DRAFT", "NEEDS_CLARIFICATION"}  # a summary already sent is not edited here
CENTS = Decimal("0.01")
HEADERS = {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}
# ponytail: one page of 100, no pagination; add LastEvaluatedKey paging if the demo outgrows it.
PAGE_SIZE = 100
LINE_RESOURCE = "/orders/{orderId}/lines/{lineId}"


def _json_default(value: object) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(type(value))


def _response(status: int, body: dict[str, object]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": HEADERS,
        "body": json.dumps(body, default=_json_default),
    }


def _groups(claims: dict[str, str]) -> set[str]:
    # REST API authorizers render array claims as "[a b]" or "a,b".
    return {g for g in re.split(r"[\s,\[\]]+", claims.get("cognito:groups", "")) if g}


def _table(env: str = "ORDERS_TABLE") -> Any:
    return boto3.resource("dynamodb").Table(os.environ[env])


def _batch_get(
    env: str, key: str, ids: set[str], projection: str, names: dict[str, str] | None = None
) -> dict[str, dict[str, Any]]:
    """Items by key, best effort: unprocessed keys are left out and the UI falls back to the id."""
    if not ids:
        return {}
    name = os.environ[env]
    request: dict[str, Any] = {
        "Keys": [{key: i} for i in sorted(ids)],
        "ProjectionExpression": projection,
    }
    if names:
        request["ExpressionAttributeNames"] = names
    dynamodb: Any = boto3.resource("dynamodb")
    res = dynamodb.batch_get_item(RequestItems={name: request})
    return {i[key]: i for i in res["Responses"].get(name, [])}


def _summaries(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    customers = _batch_get(
        "CUSTOMERS_TABLE",
        "customerId",
        {i["customerId"] for i in items if "customerId" in i},
        "customerId, venueName",
    )
    conversations = _batch_get(
        "CONVERSATIONS_TABLE",
        "conversationId",
        {i["conversationId"] for i in items if "conversationId" in i},
        "conversationId, #mode",
        {"#mode": "mode"},
    )
    summaries = []
    for item in items:
        summary: dict[str, Any] = {k: item[k] for k in SUMMARY_FIELDS if k in item}
        if name := customers.get(item.get("customerId", ""), {}).get("venueName"):
            summary["customerName"] = name
        summary["uncertainLines"] = sum(
            1 for line in item.get("lines", []) if line.get("status") in UNCERTAIN_LINES
        )
        mode = conversations.get(item.get("conversationId", ""), {}).get("mode")
        summary["handoff"] = mode == "HUMAN"
        summaries.append(summary)
    return summaries


def _list_orders(groups: set[str], claims: dict[str, str], status: str | None) -> dict[str, Any]:
    table = _table()
    if groups & READ_ALL_ROLES:
        if status:
            res = table.query(
                IndexName="by-status",
                KeyConditionExpression=Key("status").eq(status),
                ScanIndexForward=False,
                Limit=PAGE_SIZE,
            )
        else:
            res = table.scan(Limit=PAGE_SIZE)
        items = res["Items"]
    else:
        rep_id = claims.get("custom:repId")
        if not rep_id:
            return _response(403, {"error": "forbidden"})
        res = table.query(
            IndexName="by-repId", KeyConditionExpression=Key("repId").eq(rep_id), Limit=PAGE_SIZE
        )
        items = [i for i in res["Items"] if not status or i.get("status") == status]
    orders = _summaries(items)
    orders.sort(key=lambda o: o.get("createdAt", ""), reverse=True)
    return _response(200, {"orders": orders})


def _ticket_uri(order: dict[str, Any]) -> str | None:
    """The order's `imageS3Uri`, else the photo its lines come from (first image of the chat)."""
    if uri := order.get("imageS3Uri"):
        return str(uri)
    conversation = order.get("conversationId")
    if not conversation:
        return None
    source_ids = {line.get("sourceMessageId") for line in order.get("lines", [])}
    # ponytail: oldest 100 messages of the conversation; page if a chat outgrows it.
    messages = _table("MESSAGES_TABLE").query(
        KeyConditionExpression=Key("conversationId").eq(conversation), Limit=PAGE_SIZE
    )["Items"]
    first: str | None = None
    for message in messages:
        if message.get("direction") != "INBOUND":
            continue
        for attachment in message.get("attachments") or []:
            if attachment.get("type") == "image" and attachment.get("s3Uri"):
                if message.get("messageId") in source_ids:
                    return str(attachment["s3Uri"])
                first = first or str(attachment["s3Uri"])
    return first


def _image_url(order: dict[str, Any]) -> str | None:
    uri = _ticket_uri(order)
    if not uri:
        return None
    bucket, _, key = uri.removeprefix("s3://").partition("/")
    url: str = boto3.client("s3").generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=int(os.environ.get("IMAGE_URL_TTL_SECONDS", "300")),
    )
    return url


def _line_view(line: dict[str, Any]) -> dict[str, Any]:
    """A stored line in the console contract (02 §6.3); unwritten fields get defaults."""
    resolved = bool(line.get("sku"))
    return {
        "rawText": "",
        "rawQuantity": None,
        "rawUnit": None,
        "sourceMessageId": "",
        "imageRegion": None,
        "sku": None,
        "name": None,
        "quantity": None,
        "unit": None,
        # ponytail: the agent stores no match confidence; a chosen SKU shows as certain.
        "confidence": 1 if resolved else 0,
        "correctedBy": None,
        **line,
        "candidates": [
            {"confidence": 0, "boughtBefore": False, **c} for c in line.get("candidates", [])
        ],
    }


def _detail(order: dict[str, Any]) -> dict[str, Any]:
    summary = _summaries([order])[0]
    shown = {
        **order,
        **summary,
        "source": order.get("source", "text"),
        "lines": [
            _line_view(line) for line in order.get("lines", []) if line.get("status") != "REMOVED"
        ],
    }
    return {"order": shown, "imageUrl": _image_url(order)}


def _visible_order(
    groups: set[str], claims: dict[str, str], order_id: str, *, write: bool = False
) -> dict[str, Any] | None:
    # Groups are additive: a `judge` who is also `sales_rep` still writes only in its portfolio.
    all_orders = "backoffice" in groups if write else bool(groups & READ_ALL_ROLES)
    order: dict[str, Any] | None = (
        _table().get_item(Key={"orderId": order_id}, ConsistentRead=True).get("Item")
    )
    rep_id = claims.get("custom:repId")
    allowed = all_orders or bool(rep_id and order and order.get("repId") == rep_id)
    # Same answer for "missing" and "not yours": do not reveal other reps' order ids.
    return order if order and allowed else None


def _get_order(groups: set[str], claims: dict[str, str], order_id: str) -> dict[str, Any]:
    order = _visible_order(groups, claims, order_id)
    if not order:
        return _response(404, {"error": "not_found"})
    return _response(200, _detail(order))


def _price(customer_id: str, sku: str, today: str) -> Decimal | None:
    """Final unit price; keep in sync with `suppliagent_shared.pricing.price_of`."""
    customer = _table("CUSTOMERS_TABLE").get_item(Key={"customerId": customer_id}).get("Item")
    if not customer:
        return None
    entry = (
        _table("PRICE_LISTS_TABLE")
        .get_item(Key={"priceListId": customer["priceListId"], "sku": sku})
        .get("Item")
    )
    if not entry:
        return None
    unit = Decimal(entry["price"])
    promos = _table("PROMOTIONS_TABLE").query(
        IndexName="by-sku", KeyConditionExpression=Key("sku").eq(sku)
    )["Items"]
    valid = [Decimal(p["promoPrice"]) for p in promos if p["validFrom"] <= today <= p["validTo"]]
    return min([unit, *valid])


def _emit(detail_type: str, detail: dict[str, Any]) -> None:
    """Application event (02 §6.4), best effort: it only feeds the KPIs."""
    try:
        boto3.client("events").put_events(
            Entries=[
                {
                    "Source": "suppliagent.console-api",
                    "DetailType": detail_type,
                    "Detail": json.dumps(detail),
                    "EventBusName": os.environ["EVENT_BUS_NAME"],
                }
            ]
        )
    except Exception:
        logger.warning("event not sent", extra={"type": detail_type})


def _quantity(body: dict[str, Any], line: dict[str, Any]) -> Decimal | None:
    given = body.get("quantity", line.get("quantity"))
    if given is None:
        return None
    if isinstance(given, bool) or not isinstance(given, int | float | Decimal):
        raise ValueError(given)
    quantity = Decimal(str(given))
    if not 0 < quantity <= 100000:
        raise ValueError(given)
    return quantity


def _correct_line(
    groups: set[str], claims: dict[str, str], order_id: str, line_id: str, raw_body: str | None
) -> dict[str, Any]:
    """The back office picks one of the line's candidates (FN-28): the line becomes MATCHED."""
    try:
        body = json.loads(raw_body or "")
        sku = body["sku"]
        if not isinstance(sku, str):
            raise TypeError(sku)
    except (ValueError, KeyError, TypeError):
        return _response(400, {"error": "invalid_body"})
    order = _visible_order(groups, claims, order_id, write=True)
    if not order:
        return _response(404, {"error": "not_found"})
    if order["status"] not in CORRECTABLE_ORDERS:
        return _response(409, {"error": "not_editable"})
    lines = [dict(line) for line in order["lines"]]
    line = next((x for x in lines if x["lineId"] == line_id and x["status"] != "REMOVED"), None)
    if not line:
        return _response(404, {"error": "not_found"})
    if sku not in {c["sku"] for c in line.get("candidates", [])}:
        return _response(400, {"error": "invalid_sku"})
    product = _table("PRODUCTS_TABLE").get_item(Key={"sku": sku}).get("Item")
    if not product or not product.get("active", True):
        return _response(400, {"error": "invalid_sku"})
    try:
        quantity = _quantity(body, line)
    except ValueError:
        return _response(400, {"error": "invalid_body"})
    if quantity is None:
        return _response(400, {"error": "quantity_required"})

    previous_sku = line.get("sku")
    by = "backoffice" if "backoffice" in groups else "rep"
    line.update(
        status="MATCHED",
        sku=sku,
        name=product["name"],
        unit=product["unit"],
        quantity=quantity,
        correctedBy=by,
    )
    line.pop("confidence", None)
    for stale in ("format", "unitPrice", "lineTotal"):
        line.pop(stale, None)
    if product.get("format"):
        line["format"] = product["format"]
    today = datetime.now(ZoneInfo("Europe/Rome")).date().isoformat()
    if price := _price(order["customerId"], sku, today):
        line["unitPrice"] = price
        line["lineTotal"] = (price * quantity).quantize(CENTS)

    total = sum(
        (x.get("lineTotal", Decimal(0)) for x in lines if x["status"] in ACTIVE_LINES), Decimal(0)
    ).quantize(CENTS)
    unresolved = any(x["status"] in UNRESOLVED_LINES for x in lines)
    new_status = "NEEDS_CLARIFICATION" if unresolved else "DRAFT"
    version = int(order.get("version", 0))
    now = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    try:
        _table().update_item(
            Key={"orderId": order_id},
            UpdateExpression=(
                "SET #lines = :lines, #total = :total, #status = :new, "
                "updatedAt = :now, #version = :next"
            ),
            ConditionExpression="#version = :v AND #status IN (:s0, :s1)",
            ExpressionAttributeNames={
                "#lines": "lines",
                "#total": "total",
                "#status": "status",
                "#version": "version",
            },
            ExpressionAttributeValues={
                ":lines": lines,
                ":total": total,
                ":new": new_status,
                ":now": now,
                ":next": version + 1,
                ":v": version,
                ":s0": "DRAFT",
                ":s1": "NEEDS_CLARIFICATION",
            },
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        return _response(409, {"error": "conflict"})  # the agent or someone else changed it first
    updated = {
        **order,
        "lines": lines,
        "total": total,
        "status": new_status,
        "updatedAt": now,
        "version": version + 1,
    }
    _emit(
        "order.line_corrected",
        {
            "orderId": order_id,
            "lineId": line_id,
            "by": "BACKOFFICE" if by == "backoffice" else "SALES_REP",
            "fromSku": previous_sku,
            "toSku": sku,
        },
    )
    if new_status != order["status"]:
        _emit(
            "order.status_changed",
            {"orderId": order_id, "from": order["status"], "to": new_status, "ts": now},
        )
    return _response(200, _detail(updated))


def handler(event: dict[str, Any], _context: object) -> dict[str, Any]:
    claims: dict[str, str] = event["requestContext"]["authorizer"]["claims"]
    groups = _groups(claims)
    if not groups & (READ_ALL_ROLES | {"sales_rep"}):
        return _response(403, {"error": "forbidden"})
    resource = event["resource"]
    if event["httpMethod"] != "GET":
        # `judge` is read-only (FN-28): refused before routing, no write endpoint can skip it.
        if not groups & WRITE_ROLES:
            return _response(403, {"error": "read_only"})
        if event["httpMethod"] == "PATCH" and resource == LINE_RESOURCE:
            path = event["pathParameters"]
            return _correct_line(groups, claims, path["orderId"], path["lineId"], event.get("body"))
        return _response(405, {"error": "method_not_allowed"})
    if resource == "/orders":
        query = event.get("queryStringParameters") or {}
        return _list_orders(groups, claims, query.get("status"))
    if resource == "/orders/{orderId}":
        return _get_order(groups, claims, event["pathParameters"]["orderId"])
    return _response(404, {"error": "not_found"})
