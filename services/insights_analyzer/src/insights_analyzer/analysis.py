"""Per-customer insights from the order history (INFRASTRUCTURE_DESIGN §5.6, F-13): pure functions.

- expected reorders: average interval between the orders of each SKU bought at least twice;
  `dueAt` = last order + interval (the Proactive Trigger applies `reorderDueFactor` on top);
- dropped products: bought regularly (at least 3 times), absent for more than 2 intervals;
- suggestions (max 3): products the customer never bought that venues of the same `venueType`,
  then of the same zone, buy; then current promotions (on the customer's products first).
"""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

MAX_SUGGESTIONS = 3
DROPPED_MIN_ORDERS = 3
DROPPED_INTERVALS = 2
# The history keeps the day only: orders are placed in the morning (same convention as the seed).
ORDER_TIME = time(9, 0, tzinfo=UTC)


def stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _days_by_sku(history: Iterable[Mapping[str, Any]]) -> dict[str, list[date]]:
    days: dict[str, set[date]] = {}
    for order in history:
        day = date.fromisoformat(str(order["date"]))
        for line in order["lines"]:
            days.setdefault(str(line["sku"]), set()).add(day)
    return {sku: sorted(d) for sku, d in days.items()}


def reorders(
    history: Iterable[Mapping[str, Any]], as_of: datetime
) -> tuple[list[dict[str, Any]], list[str]]:
    """Expected reorders (earliest due first) and dropped products, as of `as_of`."""
    expected: list[dict[str, Any]] = []
    dropped: list[str] = []
    for sku, days in _days_by_sku(history).items():
        days = [d for d in days if datetime.combine(d, ORDER_TIME) <= as_of]
        if len(days) < 2:
            continue
        every = max(1, round((days[-1] - days[0]).days / (len(days) - 1)))
        last = datetime.combine(days[-1], ORDER_TIME)
        if len(days) >= DROPPED_MIN_ORDERS and as_of - last > timedelta(
            days=DROPPED_INTERVALS * every
        ):
            dropped.append(sku)
            continue
        expected.append(
            {
                "sku": sku,
                "everyDays": every,
                "lastOrderedAt": stamp(last),
                "dueAt": stamp(last + timedelta(days=every)),
            }
        )
    expected.sort(key=lambda r: (r["dueAt"], r["sku"]))
    return expected, sorted(dropped)


def _gap(
    own: set[str], peers: Iterable[str], bought: Mapping[str, set[str]], reason: str
) -> list[dict[str, str]]:
    counts: Counter[str] = Counter(
        sku for peer in peers for sku in bought.get(peer, set()) if sku not in own
    )
    return [
        {"sku": sku, "reason": reason.format(n=n)}
        for sku, n in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def suggestions(
    customer: Mapping[str, Any],
    customers: Iterable[Mapping[str, Any]],
    bought: Mapping[str, set[str]],
    promotions: Iterable[Mapping[str, Any]],
    as_of: datetime,
) -> list[dict[str, str]]:
    """Gap against venues of the same type, then of the same zone, then current promotions
    (on the customer's products first)."""
    own = bought.get(customer["customerId"], set())
    peers = [c for c in customers if c["customerId"] != customer["customerId"]]
    same = [c["customerId"] for c in peers if c.get("venueType") == customer.get("venueType")]
    zone = [c["customerId"] for c in peers if c.get("zone") == customer.get("zone")]
    today = as_of.date().isoformat()
    active = [
        p
        for p in sorted(promotions, key=lambda p: (p["sku"] not in own, str(p["promoId"])))
        if str(p["validFrom"]) <= today <= str(p["validTo"])
    ]
    found = (
        _gap(own, same, bought, "Ordinato da {n} locali dello stesso tipo")
        + _gap(own, zone, bought, "Ordinato da {n} locali della stessa zona")
        + [
            {"sku": str(p["sku"]), "reason": f"In promozione fino al {p['validTo']}"}
            for p in active
        ]
    )
    unique: dict[str, dict[str, str]] = {}
    for item in found:
        unique.setdefault(item["sku"], item)
    return list(unique.values())[:MAX_SUGGESTIONS]


def analyze(
    customers: Sequence[Mapping[str, Any]],
    history: Mapping[str, Sequence[Mapping[str, Any]]],
    promotions: Sequence[Mapping[str, Any]],
    as_of: datetime,
) -> list[dict[str, Any]]:
    """`CustomerInsights` items (without the keys the trigger owns, e.g. `lastProposalAt`)."""
    bought = {
        cid: {str(line["sku"]) for order in orders for line in order["lines"]}
        for cid, orders in history.items()
    }
    result = []
    for customer in customers:
        expected, dropped = reorders(history.get(customer["customerId"], []), as_of)
        result.append(
            {
                "customerId": customer["customerId"],
                "expectedReorders": expected,
                "droppedProducts": dropped,
                "suggestions": suggestions(customer, customers, bought, promotions, as_of),
                "updatedAt": stamp(as_of),
            }
        )
    return result
