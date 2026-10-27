"""ERP interface and its hackathon mock (FN-13; INFRASTRUCTURE_DESIGN §5.5).

`ErpAdapter` is what a real ERP (REST, EDI, SFTP) would implement. The mock keeps everything in
`Orders` / `Deliveries`: it numbers a confirmed order, then lets it be scheduled and delivered.

Environment: `TABLE_PREFIX`, `EVENT_BUS_NAME`, `ERP_FAILURE_PARAM` (SSM, `true` = ERP down, E-08;
missing means up).
"""

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities import parameters
from botocore.exceptions import ClientError
from suppliagent_shared.aws import put_event, table
from suppliagent_shared.errors import ErpUnavailableError, InvalidInputError, NotFoundError

SOURCE = "suppliagent.erp"
DELIVERY_WINDOW = "08:00-12:00"  # ponytail: one fixed slot; per-zone windows if the demo needs them
# Mock delivery progress; each step is one `advance` call (a real ERP would push these).
NEXT_STATUS = {
    "SUBMITTED": "SCHEDULED",
    "SCHEDULED": "OUT_FOR_DELIVERY",
    "OUT_FOR_DELIVERY": "DELIVERED",
}
logger = Logger(service="erp-adapter")


@dataclass(frozen=True)
class ErpResult:
    erpOrderNumber: str  # noqa: N815 - wire name
    status: str


@runtime_checkable
class ErpAdapter(Protocol):
    def submit_order(self, order: dict[str, Any]) -> ErpResult: ...
    def update_order(self, order_id: str) -> ErpResult: ...
    def cancel_order(self, order_id: str) -> None: ...
    def get_order_status(self, erp_order_number: str) -> str: ...


def erp_number(order_id: str) -> str:
    """Mock numbering, reversible so `get_order_status` needs no index: `ord_123` -> `ERP-123`."""
    return "ERP-" + order_id.removeprefix("ord_")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _orders() -> Any:
    return table("orders")


def _get_order(order_id: str) -> dict[str, Any]:
    item: dict[str, Any] | None = _orders().get_item(Key={"orderId": order_id}).get("Item")
    if not item:
        raise NotFoundError
    return item


def _ensure_up(order_id: str) -> None:
    try:
        down = parameters.get_parameter(os.environ["ERP_FAILURE_PARAM"], max_age=60)
    except parameters.exceptions.GetParameterError:
        return
    if str(down).lower() == "true":
        put_event(SOURCE, "erp.failed", {"orderId": order_id, "error": ErpUnavailableError.code})
        logger.warning("erp unavailable", extra={"orderId": order_id})
        raise ErpUnavailableError


def _move(order_id: str, source: set[str], target: str, **fields: str) -> str:
    """Conditional status change (two concurrent calls cannot both win); returns the old status."""
    names = {"#s": "status", **{f"#{k}": k for k in fields}}
    values = {":to": target, ":ts": _now(), **{f":{k}": v for k, v in fields.items()}}
    sets = ", ".join(["#s = :to", "updatedAt = :ts", *(f"#{k} = :{k}" for k in fields)])
    guard = " OR ".join(f"#s = :from{i}" for i in range(len(source)))
    values.update({f":from{i}": status for i, status in enumerate(sorted(source))})
    try:
        old = _orders().update_item(
            Key={"orderId": order_id},
            UpdateExpression="SET " + sets,
            ConditionExpression=guard,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ReturnValues="UPDATED_OLD",
        )["Attributes"]["status"]
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        raise InvalidInputError from exc
    # ponytail: events are KPIs; if this put fails the retry sees the new status and skips them.
    put_event(
        SOURCE,
        "order.status_changed",
        {"orderId": order_id, "from": str(old), "to": target, "ts": values[":ts"]},
    )
    return str(old)


class MockErpAdapter:
    def submit_order(self, order: dict[str, Any]) -> ErpResult:
        """CONFIRMED -> SUBMITTED. A repeated event returns the number already given."""
        order_id = order["orderId"]
        if order["status"] != "CONFIRMED":
            if number := order.get("erpOrderNumber"):
                return ErpResult(number, order["status"])
            raise InvalidInputError
        _ensure_up(order_id)
        number = erp_number(order_id)
        try:
            _move(order_id, {"CONFIRMED"}, "SUBMITTED", erpOrderNumber=number)
        except InvalidInputError:  # lost a race with a concurrent delivery of the same event
            current = _get_order(order_id)
            if current.get("erpOrderNumber") != number:
                raise
            return ErpResult(number, current["status"])
        put_event(SOURCE, "erp.submitted", {"orderId": order_id, "erpOrderNumber": number})
        return ErpResult(number, "SUBMITTED")

    def update_order(self, order_id: str) -> ErpResult:
        """Resubmits an order changed before the cut-off (F-08.C2): same number, no new status."""
        order = _get_order(order_id)
        if order["status"] != "SUBMITTED":
            raise InvalidInputError
        _ensure_up(order_id)
        return ErpResult(order["erpOrderNumber"], "SUBMITTED")

    def cancel_order(self, order_id: str) -> None:
        _ensure_up(order_id)
        _move(order_id, {"CONFIRMED", "SUBMITTED"}, "CANCELLED")

    def get_order_status(self, erp_order_number: str) -> str:
        if not erp_order_number.startswith("ERP-"):
            raise NotFoundError
        return str(_get_order("ord_" + erp_order_number.removeprefix("ERP-"))["status"])

    def advance(self, order_id: str, to: str) -> None:
        """Simulates the ERP planning (SCHEDULED) and the delivery steps, one at a time."""
        order = _get_order(order_id)
        if NEXT_STATUS.get(order["status"]) != to:
            raise InvalidInputError
        if to == "SCHEDULED":
            # Before the status change: a retry after a crash in between writes the same item.
            table("deliveries").put_item(
                Item={
                    "orderId": order_id,
                    "date": order["deliveryDate"],
                    "window": DELIVERY_WINDOW,
                    "customerId": order["customerId"],
                }
            )
        _move(order_id, {order["status"]}, to)
