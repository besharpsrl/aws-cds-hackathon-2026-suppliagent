"""FN-09 / FN-10 acceptance: availability with substitutes and multiples, prices, delivery date."""

from datetime import date, datetime
from typing import Any

import pytest
from pydantic import BaseModel
from suppliagent_shared.auth import CallerContext
from suppliagent_shared.errors import AccessDeniedError, NotFoundError
from suppliagent_tool_inventory_pricing.inventory import (
    CheckAvailabilityInput,
    DeliveryOptionsInput,
    GetPricesInput,
    check_availability,
    get_delivery_options,
    get_prices,
)


def make[T: BaseModel](cls: type[T], **kwargs: Any) -> T:
    """Validated model from plain values (the Gateway sends JSON, not typed objects)."""
    return cls.model_validate(kwargs)


CUSTOMER = make(
    CallerContext, role="CUSTOMER_CONTACT", contactId="con_001", channelAddress="WHATSAPP#+39333"
)
REP = make(CallerContext, role="SALES_REP", contactId="rep_001", channelAddress="WHATSAPP#+39334")
STRANGER = make(CallerContext, role="UNKNOWN", channelAddress="WHATSAPP#+39335")
WEDNESDAY = date(2026, 10, 28)


def availability(caller: CallerContext, *lines: tuple[str, float]) -> dict[str, Any]:
    return check_availability(
        make(
            CheckAvailabilityInput,
            caller=caller,
            lines=[{"sku": s, "quantity": q} for s, q in lines],
            deliveryDate=date(2026, 10, 29),
        )
    )


def by_sku(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {r["sku"]: r for r in result["results"]}


def test_available_line_has_no_noise() -> None:
    line = by_sku(availability(CUSTOMER, ("FDL-PIZZA-1KG", 25)))["FDL-PIZZA-1KG"]
    assert line["status"] == "AVAILABLE"
    assert "substitutes" not in line and "roundedQuantity" not in line


def test_out_of_stock_offers_substitutes_that_are_available_and_the_restock() -> None:
    line = by_sku(availability(CUSTOMER, ("MOZZ-BUF-250", 4)))["MOZZ-BUF-250"]
    assert line["status"] == "OUT_OF_STOCK"
    assert line["nextArrival"] == "2026-11-03"
    assert [s["sku"] for s in line["substitutes"]] == ["MOZZ-BUF-125", "BURRATA-125"]


def test_restock_before_the_delivery_date_counts_as_available() -> None:
    result = check_availability(
        make(
            CheckAvailabilityInput,
            caller=CUSTOMER,
            lines=[{"sku": "MOZZ-BUF-250", "quantity": 4}],
            deliveryDate=date(2026, 11, 5),
        )
    )
    assert by_sku(result)["MOZZ-BUF-250"]["status"] == "AVAILABLE"


def test_partial_stock_gives_the_available_quantity() -> None:
    line = by_sku(availability(CUSTOMER, ("GRANA-GRAT-1KG", 10)))["GRANA-GRAT-1KG"]
    assert line["status"] == "PARTIAL"
    assert line["availableQuantity"] == 6


def test_pack_multiple_is_not_enforced() -> None:
    line = by_sku(availability(CUSTOMER, ("BURRO-PAN-1KG", 3), ("MOZZ-BUF-125", 4)))
    assert "roundedQuantity" not in line["BURRO-PAN-1KG"]


def test_discontinued_product_points_to_its_substitute() -> None:
    line = by_sku(availability(CUSTOMER, ("BURRO-PAN-500", 2)))["BURRO-PAN-500"]
    assert line["status"] == "DISCONTINUED"
    assert [s["sku"] for s in line["substitutes"]] == ["BURRO-PAN-1KG"]


def test_unknown_sku() -> None:
    assert by_sku(availability(CUSTOMER, ("NOPE", 1)))["NOPE"] == {
        "sku": "NOPE",
        "status": "UNKNOWN_SKU",
    }


def test_exact_stock_is_internal() -> None:
    assert (
        "stockQuantity" not in by_sku(availability(CUSTOMER, ("FDL-PIZZA-1KG", 1)))["FDL-PIZZA-1KG"]
    )
    rep_line = by_sku(availability(REP, ("FDL-PIZZA-1KG", 1)))["FDL-PIZZA-1KG"]
    assert rep_line["stockQuantity"] == 400


def test_unknown_caller_is_denied_everywhere() -> None:
    with pytest.raises(AccessDeniedError):
        availability(STRANGER, ("FDL-PIZZA-1KG", 1))
    with pytest.raises(AccessDeniedError):
        get_prices(
            make(GetPricesInput, caller=STRANGER, customerId="cus_001", skus=["FDL-PIZZA-1KG"])
        )
    with pytest.raises(AccessDeniedError):
        get_delivery_options(make(DeliveryOptionsInput, caller=STRANGER, customerId="cus_001"))


def test_prices_come_from_the_customer_price_list_with_the_valid_promo() -> None:
    result = get_prices(
        make(
            GetPricesInput,
            caller=CUSTOMER,
            customerId="cus_001",
            skus=["FDL-PIZZA-2KG", "FDL-PIZZA-1KG", "NOPE"],
        )
    )
    prices = by_sku(result)
    assert prices["FDL-PIZZA-1KG"]["finalPrice"] == 6.80 and "promo" not in prices["FDL-PIZZA-1KG"]
    assert prices["FDL-PIZZA-2KG"]["unitPrice"] == 13.20
    assert prices["FDL-PIZZA-2KG"]["finalPrice"] == 12.40
    assert prices["FDL-PIZZA-2KG"]["promo"]["promoId"] == "promo_002"
    assert prices["NOPE"]["status"] == "NO_PRICE"


def test_expired_promo_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    import suppliagent_tool_inventory_pricing.inventory as inventory

    monkeypatch.setattr(inventory, "_today", lambda: date(2026, 11, 20))
    result = get_prices(
        make(GetPricesInput, caller=CUSTOMER, customerId="cus_001", skus=["FDL-PIZZA-2KG"])
    )
    assert by_sku(result)["FDL-PIZZA-2KG"]["finalPrice"] == 13.20


def test_beverage_price_list_for_the_pub() -> None:
    caller = make(
        CallerContext,
        role="CUSTOMER_CONTACT",
        contactId="con_004",
        channelAddress="WHATSAPP#+39336",
    )
    result = get_prices(
        make(GetPricesInput, caller=caller, customerId="cus_004", skus=["BIRRA-FUSTO-20L"])
    )
    assert result["priceList"] == "LIST_BEVERAGE"
    assert by_sku(result)["BIRRA-FUSTO-20L"]["finalPrice"] == 56.0


def test_prices_of_another_customer_are_denied() -> None:
    with pytest.raises(AccessDeniedError):  # con_001 owns cus_001 and cus_005, not cus_002
        get_prices(
            make(GetPricesInput, caller=CUSTOMER, customerId="cus_002", skus=["FDL-PIZZA-1KG"])
        )
    with pytest.raises(AccessDeniedError):  # rep_001's portfolio: cus_001..003
        get_prices(make(GetPricesInput, caller=REP, customerId="cus_004", skus=["FDL-PIZZA-1KG"]))


def test_delivery_before_cutoff_is_the_next_served_day() -> None:
    now = datetime.fromisoformat("2026-10-28T09:00:00+00:00")  # Wed 10:00 in Rome
    result = get_delivery_options(
        make(DeliveryOptionsInput, caller=CUSTOMER, customerId="cus_001", orderTime=now)
    )
    assert result["nextDeliveryDate"] == "2026-10-29"  # Thursday
    assert result["options"] == ["2026-10-29", "2026-11-02", "2026-11-05"]
    assert result["afterCutoff"] is False and "missedDeliveryDate" not in result
    assert result["servedDays"] == ["MON", "THU"] and result["minOrderValue"] == 80


def test_delivery_after_cutoff_moves_to_the_following_day() -> None:
    now = datetime.fromisoformat("2026-10-28T18:30:00+00:00")  # Wed 19:30 in Rome
    result = get_delivery_options(
        make(DeliveryOptionsInput, caller=CUSTOMER, customerId="cus_001", orderTime=now)
    )
    assert result["afterCutoff"] is True
    assert result["missedDeliveryDate"] == "2026-10-29"
    assert result["nextDeliveryDate"] == "2026-11-02"


def test_closed_zone_date_is_skipped() -> None:
    now = datetime.fromisoformat("2026-12-07T09:00:00+00:00")  # Mon: Tuesday 8 Dec is closed
    result = get_delivery_options(
        make(DeliveryOptionsInput, caller=REP, customerId="cus_002", orderTime=now)
    )
    assert result["nextDeliveryDate"] == "2026-12-11"


def test_requested_date_is_checked_against_the_calendar() -> None:
    now = datetime.fromisoformat("2026-10-28T09:00:00+00:00")

    def served(day: str) -> bool:
        out = get_delivery_options(
            make(
                DeliveryOptionsInput,
                caller=CUSTOMER,
                customerId="cus_001",
                orderTime=now,
                requestedDate=day,
            )
        )
        return bool(out["requestedDateServed"])

    assert served("2026-11-02")  # a Monday
    assert not served("2026-10-30")  # a Friday: not a delivery day
    assert not served("2026-10-28")  # too early


def test_delivery_options_for_unknown_customer_of_a_rep() -> None:
    with pytest.raises(AccessDeniedError):
        get_delivery_options(make(DeliveryOptionsInput, caller=REP, customerId="cus_999"))


def test_missing_customer_row_is_not_found(aws: Any) -> None:
    aws.Table("suppliagent-test-customers").delete_item(Key={"customerId": "cus_001"})
    # scope comes from the contact: the venue is still "owned" but the row is gone
    with pytest.raises(NotFoundError):
        get_prices(
            make(GetPricesInput, caller=CUSTOMER, customerId="cus_001", skus=["FDL-PIZZA-1KG"])
        )
