"""Order lifecycle tools (FN-12, FN-16, FN-17, FN-18; 02 §2.3, F-07..F-09, F-12, §6.5).

The model proposes SKUs and quantities; everything else on an order (names, units, prices, totals,
status, who may touch it) is decided here. An order is confirmed only from `PENDING_CONFIRMATION`,
the state reached when the summary was produced for the customer, so nothing is sent to the ERP
without an explicit confirmation (AGENTS §8.1). Confirmation is idempotent.

Environment: `TABLE_PREFIX`, `EVENT_BUS_NAME`, `DELIVERY_CUTOFF` (`HH:MM`, Europe/Rome),
`MIN_ORDER_VALUE` (EUR), `MEDIA_BUCKET`.
"""

# ruff: noqa: N815 - field names are the camelCase wire names (02 §6).

import os
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import urlparse

from aws_lambda_powertools import Logger
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError
from pydantic import BaseModel, ConfigDict, Field
from suppliagent_shared.auth import CallerContext, require_customer_access
from suppliagent_shared.aws import put_event, table
from suppliagent_shared.contacts import order_email
from suppliagent_shared.delivery import (
    WEEKDAYS,
    calendar_closed,
    cutoff_at,
    delivery_dates,
    parse_cutoff,
    rome,
)
from suppliagent_shared.errors import (
    AccessDeniedError,
    ConfirmationMismatchError,
    ConflictError,
    InvalidInputError,
    InvalidSkuError,
    NotFoundError,
    OrderLockedError,
)
from suppliagent_shared.models import Role, parse_order_id
from suppliagent_shared.orders import (
    ACTIVE_LINES,
    AFTER_CONFIRMATION,
    EDITABLE,
    UNRESOLVED_LINES,
    check_transition,
)
from suppliagent_shared.pricing import price_of

logger = Logger(service="tool-orders")
SOURCE = "suppliagent.tool-orders"
OPTIONS = 3  # delivery dates offered when the one on the order does not work
MAX_LINES = 60
STATUS_LIMIT = 5
ISSUE_STATUSES = frozenset({"OUT_FOR_DELIVERY", "DELIVERED", "DELIVERY_ISSUE"})
OPEN_STATUSES_NOT = frozenset({"CANCELLED", "EXPIRED"})
CENTS = Decimal("0.01")
Source = Literal["photo", "voice", "text", "email", "reorder", "rep"]
LineStatus = Literal["AMBIGUOUS", "UNMATCHED", "OUT_OF_STOCK", "SUBSTITUTED", "ADJUSTED"]


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    caller: CallerContext  # set by the agent code, never by the model


class LineSpec(BaseModel):
    """A line as the model proposes it: no price, name or unit, those come from the catalog."""

    model_config = ConfigDict(extra="forbid")

    rawText: str | None = Field(None, max_length=300)
    rawUnit: str | None = Field(None, max_length=30)
    sku: str | None = Field(None, max_length=64)
    quantity: float | None = Field(None, gt=0, le=100000)
    # Default: MATCHED with sku and quantity, else AMBIGUOUS (candidates given) or UNMATCHED.
    # SUBSTITUTED / ADJUSTED: the customer accepted a substitute / a rounding to the pack.
    status: LineStatus | None = None
    candidates: list[str] = Field(default=[], max_length=3)
    sourceMessageId: str | None = Field(None, max_length=64)
    note: str | None = Field(None, max_length=200)


class LineOp(LineSpec):
    op: Literal["add", "update", "remove"]
    lineId: str | None = Field(None, max_length=16)  # update, remove


class CreateOrderDraftInput(ToolInput):
    customerId: str = Field(max_length=64)
    lines: list[LineSpec] = Field(max_length=MAX_LINES)
    source: Source = "text"
    deliveryDate: date | None = None
    deliveryNotes: str | None = Field(None, max_length=300)


class UpdateOrderDraftInput(ToolInput):
    orderId: str = Field(max_length=64)
    ops: list[LineOp] = Field(default=[], max_length=MAX_LINES)
    deliveryDate: date | None = None
    deliveryNotes: str | None = Field(None, max_length=300)


class RequestConfirmationInput(ToolInput):
    orderId: str = Field(max_length=64)


class InteractiveReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contextId: str = Field(max_length=128)


class ConfirmOrderInput(ToolInput):
    orderId: str = Field(max_length=64)
    # Default: derived from the conversation. A repeated call never makes a second order anyway.
    idempotencyKey: str | None = Field(None, max_length=128)
    # Only for a tap on a confirmation button: it must answer the summary of THIS order.
    interactiveReply: InteractiveReply | None = None


class CancelOrderInput(ToolInput):
    orderId: str = Field(max_length=64)


class GetOrderStatusInput(ToolInput):
    customerId: str | None = Field(None, max_length=64)
    orderId: str | None = Field(None, max_length=64)


class ReportDeliveryIssueInput(ToolInput):
    orderId: str = Field(max_length=64)
    type: Literal["MISSING", "DAMAGED", "WRONG", "EXPIRED"]
    lineIds: list[str] = Field(default=[], max_length=20)
    note: str | None = Field(None, max_length=500)
    s3Uris: list[str] = Field(default=[], max_length=5)  # photos, as given for the attachment


def _now() -> datetime:
    return datetime.now(UTC)


def _stamp(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _emit(detail_type: str, detail: dict[str, Any], *, strict: bool = False) -> None:
    """Application event (02 §6.4). Best effort unless `strict`: `order.confirmed` feeds the ERP."""
    try:
        put_event(SOURCE, detail_type, detail)
    except Exception:
        if strict:
            raise
        logger.warning("event not sent", extra={"type": detail_type})  # KPI only


# --- loading, authorization, persistence ---------------------------------------------------


def _load(order_id: str) -> dict[str, Any]:
    item: dict[str, Any] | None = (
        table("orders").get_item(Key={"orderId": order_id}, ConsistentRead=True).get("Item")
    )
    if not item:
        raise AccessDeniedError  # same answer as for another customer's order: no id probing
    return item


def _authorized(caller: CallerContext, raw_id: str) -> dict[str, Any]:
    order = _load(parse_order_id(raw_id))
    require_customer_access(caller, order["customerId"])
    return order


def _customer(customer_id: str) -> dict[str, Any]:
    customer: dict[str, Any] | None = (
        table("customers").get_item(Key={"customerId": customer_id}).get("Item")
    )
    if not customer:
        raise NotFoundError
    return customer


def _write(
    order: dict[str, Any],
    sets: dict[str, Any],
    *,
    new_status: str | None = None,
    allowed: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Conditional update of the fields in `sets`: the order must still be in `allowed` statuses
    (default: the one read) and at the version read. Emits `order.status_changed`."""
    old = order["status"]
    sets = {**sets, "updatedAt": _stamp(_now()), "version": int(order.get("version", 0)) + 1}
    if new_status and new_status != old:
        check_transition(old, new_status)
        sets["status"] = new_status
    allowed = allowed or frozenset({old})
    names = {"#status": "status", **{f"#{k}": k for k in sets}}
    values: dict[str, Any] = {":v": int(order.get("version", 0))}
    values.update({f":{k}": v for k, v in sets.items()})
    values.update({f":s{i}": status for i, status in enumerate(sorted(allowed))})
    guard = " OR ".join(f"#status = :s{i}" for i in range(len(allowed)))
    try:
        table("orders").update_item(
            Key={"orderId": order["orderId"]},
            UpdateExpression="SET " + ", ".join(f"#{k} = :{k}" for k in sets),
            ConditionExpression=f"version = :v AND ({guard})",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        raise ConflictError from exc
    updated = {**order, **sets}
    if updated["status"] != old:
        _emit(
            "order.status_changed",
            {
                "orderId": order["orderId"],
                "from": old,
                "to": updated["status"],
                "ts": sets["updatedAt"],
            },
        )
    return updated


# --- lines ---------------------------------------------------------------------------------


def _product(sku: str) -> dict[str, Any]:
    product: dict[str, Any] | None = table("products").get_item(Key={"sku": sku}).get("Item")
    if not product or not product.get("active", True):
        raise InvalidSkuError
    return product


def _line(line_id: str, spec: LineSpec, price_list: str, today: str) -> dict[str, Any]:
    resolved = {"SUBSTITUTED", "ADJUSTED", None}
    if spec.status in resolved and spec.status and not (spec.sku and spec.quantity):
        raise InvalidInputError
    status = spec.status or (
        "MATCHED" if spec.sku and spec.quantity else "AMBIGUOUS" if spec.candidates else "UNMATCHED"
    )
    line: dict[str, Any] = {"lineId": line_id, "status": status}
    for key in ("rawText", "rawUnit", "sourceMessageId", "note"):
        if value := getattr(spec, key):
            line[key] = value
    line["candidates"] = [
        {"sku": sku, "name": _product(sku)["name"]} for sku in dict.fromkeys(spec.candidates)
    ]
    if spec.sku:
        product = _product(spec.sku)
        line.update(sku=spec.sku, name=product["name"], unit=product["unit"])
        if product.get("format"):
            line["format"] = product["format"]
    if spec.quantity:
        line["quantity"] = _decimal(spec.quantity)
    if status in ACTIVE_LINES and spec.sku and spec.quantity:
        if price := price_of(price_list, spec.sku, today):
            line["unitPrice"] = price.final
            line["lineTotal"] = (price.final * _decimal(spec.quantity)).quantize(CENTS)
    return line


def _total(lines: list[dict[str, Any]]) -> Decimal:
    return sum(
        (ln.get("lineTotal", Decimal(0)) for ln in lines if ln["status"] in ACTIVE_LINES),
        Decimal(0),
    ).quantize(CENTS)


def _editable_status(lines: list[dict[str, Any]]) -> str:
    return (
        "NEEDS_CLARIFICATION" if any(ln["status"] in UNRESOLVED_LINES for ln in lines) else "DRAFT"
    )


def _view(order: dict[str, Any]) -> dict[str, Any]:
    """What the model gets: no internal fields (conversation, version, idempotency keys)."""
    keep = ("lineId", "status", "rawText", "sku", "name", "format", "quantity", "unit", "unitPrice")
    lines = []
    for line in order["lines"]:
        if line["status"] == "REMOVED":
            continue
        shown = {k: line[k] for k in (*keep, "lineTotal", "note", "candidates") if k in line}
        lines.append(shown)
    view = {
        "orderId": order["orderId"],
        "status": order["status"],
        "deliveryDate": order.get("deliveryDate"),
        "deliveryNotes": order.get("deliveryNotes"),
        "lines": lines,
        "total": order["total"],
        "currency": "EUR",
    }
    if order.get("erpOrderNumber"):
        view["erpOrderNumber"] = order["erpOrderNumber"]
    return {k: v for k, v in view.items() if v is not None}


def _apply(
    order: dict[str, Any], args: UpdateOrderDraftInput, customer: dict[str, Any]
) -> list[dict[str, Any]]:
    lines = [dict(line) for line in order["lines"]]
    today = rome().date().isoformat()
    by_id = {line["lineId"]: line for line in lines}
    for op in args.ops:
        if op.op == "add":
            next_id = 1 + max((int(i[1:]) for i in by_id), default=0)
            line = _line(f"l{next_id}", op, customer["priceListId"], today)
            lines.append(line)
            by_id[line["lineId"]] = line
            continue
        old = by_id.get(op.lineId or "")
        if not old or old["status"] == "REMOVED":
            raise InvalidInputError
        if op.op == "remove":
            old["status"] = "REMOVED"
            old.pop("lineTotal", None)
            continue
        given = op.model_fields_set
        merged = LineSpec(
            rawText=op.rawText if "rawText" in given else old.get("rawText"),
            rawUnit=op.rawUnit if "rawUnit" in given else old.get("rawUnit"),
            sku=op.sku if "sku" in given else old.get("sku"),
            quantity=op.quantity
            if "quantity" in given
            else float(old["quantity"])
            if "quantity" in old
            else None,
            status=op.status if "status" in given else None,
            candidates=op.candidates
            if "candidates" in given
            else [c["sku"] for c in old["candidates"]],
            sourceMessageId=old.get("sourceMessageId"),
            note=op.note if "note" in given else old.get("note"),
        )
        new = _line(old["lineId"], merged, customer["priceListId"], today)
        if new.get("sku") != old.get("sku") and old.get("sku"):
            _emit(
                "order.line_corrected",
                {
                    "orderId": order["orderId"],
                    "lineId": old["lineId"],
                    "by": args.caller.role.value,
                    "fromSku": old["sku"],
                    "toSku": new.get("sku"),
                },
            )
        old.clear()
        old.update(new)
    return lines


# --- delivery rules and confirmation checks -----------------------------------------------


def _delivery_ok(customer: dict[str, Any], day: date, now: datetime) -> bool:
    """A served, open day whose cut-off (the evening before) has not passed."""
    return (
        WEEKDAYS[day.weekday()] in customer["deliveryDays"]
        and not calendar_closed(customer["zone"])(day)
        and now < cutoff_at(day, parse_cutoff(os.environ["DELIVERY_CUTOFF"]))
    )


def _issues(order: dict[str, Any], customer: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    """Why the order cannot be confirmed yet; empty when it can."""
    issues: list[dict[str, Any]] = []
    lines = order["lines"]
    active = [ln for ln in lines if ln["status"] in ACTIVE_LINES]
    if unresolved := [ln["lineId"] for ln in lines if ln["status"] in UNRESOLVED_LINES]:
        issues.append({"code": "UNRESOLVED_LINES", "lineIds": unresolved})
    if not active:
        issues.append({"code": "NO_LINES"})
    if unpriced := [ln["lineId"] for ln in active if "unitPrice" not in ln]:
        issues.append({"code": "NO_PRICE", "lineIds": unpriced})  # never confirm a price-less line
    for line in active:
        pack = int(_product(line["sku"]).get("multiple", 1))
        if line["quantity"] % pack:
            issues.append(
                {
                    "code": "NOT_A_MULTIPLE",
                    "lineId": line["lineId"],
                    "multiple": pack,
                    "roundedQuantity": -(-int(line["quantity"]) // pack) * pack,
                }
            )
    delivery = order.get("deliveryDate")
    if not delivery or not _delivery_ok(customer, date.fromisoformat(delivery), now):
        options, _ = delivery_dates(
            customer["deliveryDays"],
            calendar_closed(customer["zone"]),
            now,
            parse_cutoff(os.environ["DELIVERY_CUTOFF"]),
            OPTIONS,
        )
        issues.append(
            {
                "code": "INVALID_DELIVERY_DATE" if delivery else "NO_DELIVERY_DATE",
                "options": [d.isoformat() for d in options],
            }
        )
    minimum = Decimal(os.environ["MIN_ORDER_VALUE"])
    if active and (total := _total(lines)) < minimum:
        issues.append(
            {"code": "BELOW_MINIMUM", "minOrderValue": minimum, "missing": minimum - total}
        )
    return issues


def _locked(order: dict[str, Any], now: datetime) -> None:
    """Changes after the confirmation: only until the cut-off before the delivery (F-08.C3)."""
    delivery = order.get("deliveryDate")
    if order["status"] not in AFTER_CONFIRMATION or not delivery:
        raise OrderLockedError
    if now >= cutoff_at(date.fromisoformat(delivery), parse_cutoff(os.environ["DELIVERY_CUTOFF"])):
        raise OrderLockedError


# --- tools ---------------------------------------------------------------------------------


def create_order_draft(args: CreateOrderDraftInput) -> dict[str, Any]:
    require_customer_access(args.caller, args.customerId)
    customer = _customer(args.customerId)
    conversation = args.caller.conversationId
    if conversation:  # a retry, or a model that forgot the id, must not open a second draft
        recent = table("orders").query(
            IndexName="by-customerId",
            KeyConditionExpression=Key("customerId").eq(args.customerId),
            ScanIndexForward=False,
            Limit=10,
        )["Items"]
        for existing in recent:
            if existing.get("conversationId") == conversation and existing["status"] in EDITABLE:
                return {"existing": True, "order": _view(existing)}
    now = _now()
    today = rome(now).date().isoformat()
    lines = [
        _line(f"l{i}", spec, customer["priceListId"], today) for i, spec in enumerate(args.lines, 1)
    ]
    stamp = _stamp(now)
    order: dict[str, Any] = {
        "orderId": f"ord_{uuid.uuid4().hex[:12]}",
        "customerId": args.customerId,
        "repId": customer["repId"],
        "status": _editable_status(lines),
        "createdAt": stamp,
        "updatedAt": stamp,
        "createdBy": args.caller.contactId,
        "source": "rep" if args.caller.role is Role.SALES_REP else args.source,
        "lines": lines,
        "total": _total(lines),
        "version": 0,
    }
    if conversation:
        order["conversationId"] = conversation
    if args.deliveryDate:
        order["deliveryDate"] = args.deliveryDate.isoformat()
    if args.deliveryNotes:
        order["deliveryNotes"] = args.deliveryNotes
    table("orders").put_item(Item=order, ConditionExpression="attribute_not_exists(orderId)")
    _emit("order.draft_created", {"orderId": order["orderId"], "source": order["source"]})
    return {"existing": False, "order": _view(order)}


def update_order_draft(args: UpdateOrderDraftInput) -> dict[str, Any]:
    order = _authorized(args.caller, args.orderId)
    customer = _customer(order["customerId"])
    now = _now()
    after = order["status"] in AFTER_CONFIRMATION
    if after:
        _locked(order, now)
    elif order["status"] not in EDITABLE:
        raise OrderLockedError
    lines = _apply(order, args, customer) if args.ops else order["lines"]
    sets: dict[str, Any] = {"lines": lines, "total": _total(lines)}
    if args.deliveryDate:
        sets["deliveryDate"] = args.deliveryDate.isoformat()
    if args.deliveryNotes:
        sets["deliveryNotes"] = args.deliveryNotes
    if after:
        # F-08.C2: the confirmed order changes in place; saved only if it is still confirmable
        candidate = {**order, **sets}
        if issues := _issues(candidate, customer, now):
            return {"status": "NEEDS_FIXES", "issues": issues, "order": _view(order)}
        sets["revision"] = int(order.get("revision", 0)) + 1
        updated = _write(order, sets, allowed=AFTER_CONFIRMATION)
        _emit("order.updated", {"orderId": order["orderId"], "revision": sets["revision"]})
        # T-26b: whether the updated confirmation goes out by email (the Notifier's recipient, who
        # confirmed); a flag, not the address: the caller may be someone else (a sales rep).
        recipient = str(order.get("confirmedBy") or order.get("createdBy") or "")
        return {
            "status": "UPDATED",
            "order": _view(updated),
            "confirmationEmail": order_email(recipient) is not None,
        }
    updated = _write(order, sets, new_status=_editable_status(lines))
    return {"status": updated["status"], "order": _view(updated)}


def request_order_confirmation(args: RequestConfirmationInput) -> dict[str, Any]:
    order = _authorized(args.caller, args.orderId)
    if order["status"] in AFTER_CONFIRMATION:
        # T-68: a change after the confirmation stays confirmed; nothing to ask again
        return {
            "status": "NOT_CONFIRMABLE",
            "orderStatus": order["status"],
            "reason": "ALREADY_CONFIRMED",
        }
    if order["status"] not in EDITABLE:
        return {"status": "NOT_CONFIRMABLE", "orderStatus": order["status"]}
    customer = _customer(order["customerId"])
    if issues := _issues(order, customer, _now()):
        return {"status": "NEEDS_FIXES", "issues": issues, "order": _view(order)}
    # `pendingSince` also restarts the 2 h reminder (F-07.C4) when the summary is shown again
    sets = {"pendingSince": _stamp(_now())}
    updated = _write(order, sets, new_status="PENDING_CONFIRMATION", allowed=EDITABLE)
    # F-07.C7: where the confirmation email will go (the caller confirms); null = ask for one
    return {
        "status": "PENDING_CONFIRMATION",
        "summary": _view(updated),
        "orderEmail": order_email(args.caller.contactId),
    }


def confirm_order(args: ConfirmOrderInput) -> dict[str, Any]:
    order = _authorized(args.caller, args.orderId)
    if args.interactiveReply and (
        # the button id can be forged: only a reply to the summary sent for this order counts
        order.get("summaryMessageId") != args.interactiveReply.contextId
    ):
        raise ConfirmationMismatchError
    if order["status"] == "PENDING_CONFIRMATION":
        if not _customer_replied(args.caller, order):
            # The model cannot confirm in the turn that produced the summary (or on an old message):
            # a message of this conversation must have arrived after the summary was shown.
            return {
                "status": "NOT_CONFIRMABLE",
                "orderStatus": "PENDING_CONFIRMATION",
                "reason": "NEEDS_CUSTOMER_REPLY",
            }
        now = _now()
        if issues := _issues(order, _customer(order["customerId"]), now):
            return {"status": "NEEDS_FIXES", "issues": issues, "order": _view(order)}
        key = args.idempotencyKey or f"{args.caller.conversationId}:{order['orderId']}"
        lines = [
            {**line, "status": "CONFIRMED"} if line["status"] in ACTIVE_LINES else line
            for line in order["lines"]
        ]
        sets = {
            "lines": lines,
            "confirmedAt": _stamp(now),
            "confirmedBy": args.caller.contactId,
            "idempotencyKey": key,
        }
        try:
            order = _write(order, sets, new_status="CONFIRMED")
        except ConflictError:
            # a concurrent confirmation (double tap) won: answer as the duplicate it is
            order = _load(order["orderId"])
            if order["status"] == "PENDING_CONFIRMATION":
                raise
        else:
            return _announce(order, duplicate=False)
    if order.get("confirmedAt"):
        return _announce(order, duplicate=True)
    # DRAFT: no summary shown yet; EXPIRED, CANCELLED: gone. The agent explains and goes on.
    return {"status": "NOT_CONFIRMABLE", "orderStatus": order["status"]}


def _customer_replied(caller: CallerContext, order: dict[str, Any]) -> bool:
    """An inbound message of the caller's conversation stored after the summary (server-side
    evidence from `Messages`, written by the Inbound Router, not by the model)."""
    if not caller.conversationId:
        return False
    since = order.get("pendingSince") or order["updatedAt"]
    found = table("messages").query(
        KeyConditionExpression=Key("conversationId").eq(caller.conversationId)
        & Key("tsMessageId").gt(since),
        FilterExpression=Attr("direction").eq("INBOUND"),
    )
    return bool(found["Items"])


def _announce(order: dict[str, Any], *, duplicate: bool) -> dict[str, Any]:
    """`order.confirmed` once per order: a repeat sends it again only if the first send failed."""
    if not order.get("confirmedEventAt"):
        active = [ln for ln in order["lines"] if ln["status"] in ACTIVE_LINES]
        _emit(
            "order.confirmed",
            {
                "orderId": order["orderId"],
                "value": float(order["total"]),
                "lines": len(active),
                "createdBy": order["createdBy"],
            },
            strict=True,
        )
        table("orders").update_item(
            Key={"orderId": order["orderId"]},
            UpdateExpression="SET confirmedEventAt = :ts",
            ExpressionAttributeValues={":ts": _stamp(_now())},
        )
    return {"status": "ALREADY_CONFIRMED" if duplicate else "CONFIRMED", "order": _view(order)}


def cancel_order(args: CancelOrderInput) -> dict[str, Any]:
    order = _authorized(args.caller, args.orderId)
    if order["status"] in AFTER_CONFIRMATION:
        _locked(order, _now())
        # ponytail: the ERP is not told (the mock reads Orders); a real ERP needs `cancelOrder`.
        updated = _write(order, {}, new_status="CANCELLED", allowed=AFTER_CONFIRMATION)
    elif order["status"] in EDITABLE:
        updated = _write(order, {}, new_status="CANCELLED", allowed=EDITABLE)
    elif order["status"] in OPEN_STATUSES_NOT:
        return {"status": order["status"], "order": _view(order)}  # already gone
    else:
        raise OrderLockedError
    return {"status": "CANCELLED", "order": _view(updated)}


def get_order_status(args: GetOrderStatusInput) -> dict[str, Any]:
    if bool(args.orderId) == bool(args.customerId):
        raise InvalidInputError  # exactly one of the two
    if args.orderId:
        orders = [_authorized(args.caller, args.orderId)]
    else:
        require_customer_access(args.caller, str(args.customerId))
        orders = table("orders").query(
            IndexName="by-customerId",
            KeyConditionExpression=Key("customerId").eq(args.customerId),
            ScanIndexForward=False,
            Limit=STATUS_LIMIT,
        )["Items"]
    results = []
    for order in orders:
        entry: dict[str, Any] = {
            k: order[k]
            for k in ("orderId", "status", "deliveryDate", "erpOrderNumber")
            if k in order
        }
        entry["lines"] = sum(1 for ln in order["lines"] if ln["status"] in ACTIVE_LINES)
        entry["total"] = order["total"]
        if order["status"] in {"SCHEDULED", "OUT_FOR_DELIVERY", "DELIVERED", "DELIVERY_ISSUE"}:
            delivery = table("deliveries").get_item(Key={"orderId": order["orderId"]}).get("Item")
            if delivery:
                entry["deliveryWindow"] = delivery.get("window")
        results.append(entry)
    return {"orders": results}


def _media_key(caller: CallerContext, s3_uri: str) -> str:
    """Photo of the caller's own conversation: `media/<owner>/<msg>/<file>` (same rule as T-43)."""
    uri = urlparse(s3_uri)
    parts = uri.path.lstrip("/").split("/")
    owners = {owner for owner in (caller.contactId, caller.conversationId) if owner}
    if (
        uri.scheme != "s3"
        or uri.netloc != os.environ["MEDIA_BUCKET"]
        or uri.query
        or uri.fragment
        or uri.params
        or len(parts) != 4
        or parts[0] != "media"
        or parts[1] not in owners
        or any(part in ("", ".", "..") for part in parts)
    ):
        raise AccessDeniedError
    return uri.path.lstrip("/")


def report_delivery_issue(args: ReportDeliveryIssueInput) -> dict[str, Any]:
    order = _authorized(args.caller, args.orderId)
    if order["status"] not in ISSUE_STATUSES:
        raise InvalidInputError  # nothing was delivered yet
    known = {line["lineId"] for line in order["lines"]}
    if not set(args.lineIds) <= known:
        raise InvalidInputError
    for uri in args.s3Uris:
        _media_key(args.caller, uri)
    issue_id = f"iss_{uuid.uuid4().hex[:12]}"
    item: dict[str, Any] = {
        "issueId": issue_id,
        "orderId": order["orderId"],
        "customerId": order["customerId"],
        "type": args.type,
        # spoiled or wrong goods first (FN-18: visible in the console with priority)
        "priority": "HIGH" if args.type in ("DAMAGED", "EXPIRED") else "NORMAL",
        "status": "OPEN",
        "lineIds": args.lineIds,
        "s3Uris": args.s3Uris,
        "reportedBy": args.caller.contactId,
        "createdAt": _stamp(_now()),
    }
    if args.note:
        item["note"] = args.note
    table("issues").put_item(Item=item)
    if order["status"] != "DELIVERY_ISSUE":
        _write(order, {"lastIssueId": issue_id}, new_status="DELIVERY_ISSUE")
    _emit("delivery.issue_reported", {"orderId": order["orderId"], "type": args.type})
    return {"issueId": issue_id, "status": "REPORTED"}
