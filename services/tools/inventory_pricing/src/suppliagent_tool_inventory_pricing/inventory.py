"""check_availability, get_prices and get_delivery_options (FN-09, FN-10, F-06, 02 §6.5).

Everything the agent says about stock, prices and delivery dates comes from here; the model never
computes it. Customers see whether a quantity is available, never the exact stock (F-10.B).

Environment: `TABLE_PREFIX`, `DELIVERY_CUTOFF` (`HH:MM`, Europe/Rome), `MIN_ORDER_VALUE` (EUR).
"""

# ruff: noqa: N815 - field names are the camelCase wire names (02 §6).

import math
import os
from datetime import UTC, date, datetime, time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from suppliagent_shared.auth import CallerContext, require_customer_access
from suppliagent_shared.aws import table
from suppliagent_shared.delivery import (
    ROME,
    WEEKDAYS,
    calendar_closed,
    delivery_dates,
    parse_cutoff,
    rome,
)
from suppliagent_shared.errors import NotFoundError
from suppliagent_shared.models import Role
from suppliagent_shared.pricing import price_of

MAX_SKUS = 30
MAX_SUBSTITUTES = 3
OPTIONS = 3  # delivery dates offered


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    caller: CallerContext  # set by the agent code, never by the model


class StockLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(max_length=64)
    quantity: float = Field(gt=0, le=100000)


class CheckAvailabilityInput(ToolInput):
    lines: list[StockLine] = Field(min_length=1, max_length=MAX_SKUS)
    deliveryDate: date  # YYYY-MM-DD


class GetPricesInput(ToolInput):
    customerId: str = Field(max_length=64)
    skus: list[str] = Field(min_length=1, max_length=MAX_SKUS)


class DeliveryOptionsInput(ToolInput):
    customerId: str = Field(max_length=64)
    # defaults to now; ISO-8601 (tests, and orders placed earlier in the conversation)
    orderTime: datetime | None = None
    requestedDate: date | None = None


def _today() -> date:
    return rome().date()


def _num(value: Any) -> float:
    return float(value)


def _item(name: str, **key: str) -> dict[str, Any] | None:
    item: dict[str, Any] | None = table(name).get_item(Key=key).get("Item")
    return item


def _status(wanted: float, stock: float, arrives_in_time: bool) -> str:
    if stock >= wanted or arrives_in_time:
        return "AVAILABLE"
    return "PARTIAL" if stock > 0 else "OUT_OF_STOCK"


def _substitute(sku: str, wanted: float, delivery: date) -> dict[str, Any] | None:
    product, stock = _item("products", sku=sku), _item("stock", sku=sku)
    if not product or not product.get("active", True) or not stock:
        return None
    arrives = (
        bool(stock.get("nextArrival")) and date.fromisoformat(stock["nextArrival"]) <= delivery
    )
    if _status(wanted, _num(stock["quantity"]), arrives) != "AVAILABLE":
        return None
    return {k: product.get(k) for k in ("sku", "name", "brand", "format", "unit")}


def check_availability(args: CheckAvailabilityInput) -> dict[str, Any]:
    require_customer_access(args.caller)
    is_rep = args.caller.role is Role.SALES_REP
    results = []
    for line in args.lines:
        product = _item("products", sku=line.sku)
        if not product:
            results.append({"sku": line.sku, "status": "UNKNOWN_SKU"})
            continue
        stock = _item("stock", sku=line.sku) or {"quantity": 0, "substitutes": []}
        available = _num(stock["quantity"])
        next_arrival = stock.get("nextArrival")
        arrives = next_arrival is not None and date.fromisoformat(next_arrival) <= args.deliveryDate
        retired = not product.get("active", True)
        status = "DISCONTINUED" if retired else _status(line.quantity, available, arrives)
        multiple = int(product.get("multiple", 1))
        result: dict[str, Any] = {
            "sku": line.sku,
            "name": product["name"],
            "format": product.get("format"),
            "unit": product["unit"],
            "status": status,
            "multiple": multiple,
        }
        if multiple > 1 and line.quantity % multiple:
            # F-06.C4: the next whole pack, offered to the customer, never applied silently
            result["roundedQuantity"] = math.ceil(line.quantity / multiple) * multiple
        if status == "PARTIAL":
            result["availableQuantity"] = available  # what the customer can have: not hidden
        if status in ("PARTIAL", "OUT_OF_STOCK", "DISCONTINUED"):
            if next_arrival and not retired:
                result["nextArrival"] = next_arrival  # C2: wait for the restock
            subs = (_substitute(s, line.quantity, args.deliveryDate) for s in stock["substitutes"])
            result["substitutes"] = [s for s in subs if s][:MAX_SUBSTITUTES]
        if is_rep and not retired:
            result["stockQuantity"] = available  # internal figure: sales reps only
        results.append(result)
    return {"deliveryDate": args.deliveryDate.isoformat(), "results": results}


def get_prices(args: GetPricesInput) -> dict[str, Any]:
    require_customer_access(args.caller, args.customerId)
    customer = _item("customers", customerId=args.customerId)
    if not customer:
        raise NotFoundError
    today = _today().isoformat()
    results = []
    for sku in args.skus:
        price = price_of(customer["priceListId"], sku, today)
        if not price:
            results.append({"sku": sku, "status": "NO_PRICE"})
            continue
        result: dict[str, Any] = {"sku": sku, "status": "OK", "unitPrice": _num(price.unit)}
        if price.promo:
            result["promo"] = {
                "promoId": price.promo["promoId"],
                "description": price.promo["description"],
                "promoPrice": _num(price.promo["promoPrice"]),
                "validTo": price.promo["validTo"],
            }
        result["finalPrice"] = _num(price.final)
        results.append(result)
    return {"currency": "EUR", "priceList": customer["priceListId"], "results": results}


def get_delivery_options(args: DeliveryOptionsInput) -> dict[str, Any]:
    require_customer_access(args.caller, args.customerId)
    customer = _item("customers", customerId=args.customerId)
    if not customer:
        raise NotFoundError
    cutoff = parse_cutoff(os.environ["DELIVERY_CUTOFF"])
    closed = calendar_closed(customer["zone"])
    now = args.orderTime or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    dates, after = delivery_dates(customer["deliveryDays"], closed, now, cutoff, OPTIONS)
    result: dict[str, Any] = {
        "nextDeliveryDate": dates[0].isoformat() if dates else None,
        "options": [d.isoformat() for d in dates],
        "servedDays": customer["deliveryDays"],
        "cutoff": os.environ["DELIVERY_CUTOFF"],
        "afterCutoff": after,
        "minOrderValue": float(os.environ["MIN_ORDER_VALUE"]),
    }
    if after:  # C6: what the customer would have had before the cut-off
        midnight = datetime.combine(rome(now).date(), time(0, 0), tzinfo=ROME)
        before, _ = delivery_dates(customer["deliveryDays"], closed, midnight, cutoff, 1)
        result["missedDeliveryDate"] = before[0].isoformat() if before else None
    if args.requestedDate:  # C8: a served, open day not earlier than the first possible one
        day = args.requestedDate
        result["requestedDateServed"] = bool(
            dates
            and day >= dates[0]
            and WEEKDAYS[day.weekday()] in customer["deliveryDays"]
            and not closed(day)
        )
    return result
