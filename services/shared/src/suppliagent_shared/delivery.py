"""Delivery date and cut-off rules (FN-10, F-06.C6-C8), shared by the pricing and orders tools.

Orders placed before the cut-off (local time, `Europe/Rome`) are delivered from the next day on;
after it, from the day after. A delivery is served on the customer's delivery days, except the
dates the zone is closed (`DeliveryCalendar`). An order stays changeable until the cut-off of the
day before its delivery.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from suppliagent_shared.aws import table

ROME = ZoneInfo("Europe/Rome")
WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
SEARCH_DAYS = 28  # a customer with at least one delivery day always has one in four weeks
# Dates written to the customer (templates, SMS), in their language.
DAYS = {
    "it": ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"),
    "en": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
}
MONTHS = {
    "it": (
        "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
        "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
    ),
    "en": (
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ),
}  # fmt: skip


def format_day(value: date, language: str, weekday: bool = False) -> str:
    """ "29 ottobre", or "giovedì 29 ottobre" with `weekday` ("Thursday 29 October" in English)."""
    language = language if language in MONTHS else "it"
    text = f"{value.day} {MONTHS[language][value.month - 1]}"
    return f"{DAYS[language][value.weekday()]} {text}" if weekday else text


def rome(moment: datetime | None = None) -> datetime:
    return (moment or datetime.now(UTC)).astimezone(ROME)


def parse_cutoff(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def delivery_dates(
    served_days: list[str],
    closed: Callable[[date], bool],
    now: datetime,
    cutoff: time,
    count: int = 3,
) -> tuple[list[date], bool]:
    """The next `count` delivery dates, and whether `now` is past today's cut-off."""
    local = rome(now)
    after = local.time() >= cutoff
    first = local.date() + timedelta(days=2 if after else 1)
    found: list[date] = []
    for offset in range(SEARCH_DAYS):
        day = first + timedelta(days=offset)
        if WEEKDAYS[day.weekday()] in served_days and not closed(day):
            found.append(day)
            if len(found) == count:
                break
    return found, after


def cutoff_at(delivery: date, cutoff: time) -> datetime:
    """Last moment to change an order delivered on `delivery`: the cut-off of the day before."""
    return datetime.combine(delivery - timedelta(days=1), cutoff, tzinfo=ROME)


def calendar_closed(zone: str) -> Callable[[date], bool]:
    """Whether the zone has no delivery on a date, from `DeliveryCalendar` exceptions."""

    def closed(day: date) -> bool:
        entry = table("delivery-calendar").get_item(Key={"zone": zone, "date": day.isoformat()})
        item = entry.get("Item")
        return bool(item and item.get("closed", True))

    return closed
