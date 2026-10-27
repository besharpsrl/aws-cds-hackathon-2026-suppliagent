"""Price of a SKU for a price list on a given day: list price, best valid promotion, final price."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from boto3.dynamodb.conditions import Key

from suppliagent_shared.aws import table


@dataclass(frozen=True)
class Price:
    unit: Decimal  # list price per product unit, EUR
    final: Decimal  # the promotion's price when it is lower
    promo: dict[str, Any] | None


def price_of(price_list_id: str, sku: str, today: str) -> Price | None:
    """`today` is `YYYY-MM-DD` (local day). None when the list has no price for the SKU."""
    entry = (
        table("price-lists").get_item(Key={"priceListId": price_list_id, "sku": sku}).get("Item")
    )
    if not entry:
        return None
    unit = Decimal(entry["price"])
    promos = table("promotions").query(
        IndexName="by-sku", KeyConditionExpression=Key("sku").eq(sku)
    )["Items"]
    valid = [p for p in promos if p["validFrom"] <= today <= p["validTo"]]
    best = min(valid, key=lambda p: p["promoPrice"], default=None)
    return Price(unit, min(unit, Decimal(best["promoPrice"])) if best else unit, best)
