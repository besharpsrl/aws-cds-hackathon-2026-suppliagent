"""FN-19/FN-20: insights computed from the order history, deterministic on the seed."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import boto3
import pytest
from insights_analyzer.analysis import analyze, reorders, suggestions
from insights_analyzer.handler import handler
from moto import mock_aws
from suppliagent_shared.aws import reset_clients

AS_OF = datetime(2026, 10, 28, 1, 0, tzinfo=UTC)
SEED = Path(__file__).resolve().parents[3] / "seed" / "data"


def seed(name: str) -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = json.loads((SEED / f"{name}.json").read_text(encoding="utf-8"))
    return data


def order(day: str, *skus: str) -> dict[str, Any]:
    return {"date": day, "lines": [{"sku": s} for s in skus]}


def test_average_interval_and_due_date() -> None:
    history = [order("2026-10-01", "OIL"), order("2026-10-08", "OIL"), order("2026-10-15", "OIL")]
    expected, dropped = reorders(history, AS_OF)
    assert expected == [
        {
            "sku": "OIL",
            "everyDays": 7,
            "lastOrderedAt": "2026-10-15T09:00:00Z",
            "dueAt": "2026-10-22T09:00:00Z",
        }
    ]
    assert dropped == []


def test_single_order_gives_no_interval() -> None:
    assert reorders([order("2026-10-20", "OIL")], AS_OF) == ([], [])


def test_regular_product_absent_for_two_intervals_is_dropped() -> None:
    history = [order(f"2026-09-0{d}", "BURRATA") for d in (1, 4, 7)]  # every 3 days, last 7/9
    expected, dropped = reorders(history, AS_OF)
    assert expected == []
    assert dropped == ["BURRATA"]


def test_orders_after_as_of_are_ignored() -> None:
    history = [order("2026-10-01", "OIL"), order("2026-10-08", "OIL"), order("2026-11-01", "OIL")]
    assert reorders(history, AS_OF)[0][0]["lastOrderedAt"] == "2026-10-08T09:00:00Z"


def test_suggestions_same_type_then_zone_then_promotions() -> None:
    customers = [
        {"customerId": "cus_a", "venueType": "pizzeria", "zone": "Z1"},
        {"customerId": "cus_b", "venueType": "pizzeria", "zone": "Z2"},
        {"customerId": "cus_c", "venueType": "pizzeria", "zone": "Z2"},
        {"customerId": "cus_d", "venueType": "bar", "zone": "Z1"},
    ]
    bought = {
        "cus_a": {"FLOUR", "OIL"},
        "cus_b": {"FLOUR", "MOZZ", "BASIL"},
        "cus_c": {"MOZZ"},
        "cus_d": {"COFFEE"},  # a bar: not similar to a pizzeria
    }
    promos = [
        {"promoId": "p1", "sku": "OIL", "validFrom": "2026-10-19", "validTo": "2026-11-15"},
        {"promoId": "p2", "sku": "FLOUR", "validFrom": "2026-11-01", "validTo": "2026-11-15"},
        {"promoId": "p3", "sku": "COFFEE", "validFrom": "2026-10-19", "validTo": "2026-11-15"},
    ]
    result = suggestions(customers[0], customers, bought, promos, AS_OF)
    assert result == [
        {"sku": "MOZZ", "reason": "Ordinato da 2 locali dello stesso tipo"},
        {"sku": "BASIL", "reason": "Ordinato da 1 locali dello stesso tipo"},
        {"sku": "COFFEE", "reason": "Ordinato da 1 locali della stessa zona"},
    ]
    alone = {"customerId": "cus_e", "venueType": "pub", "zone": "Z9"}
    assert suggestions(alone, [*customers, alone], bought, promos, AS_OF) == [
        {"sku": "OIL", "reason": "In promozione fino al 2026-11-15"},
        {"sku": "COFFEE", "reason": "In promozione fino al 2026-11-15"},
    ]  # nobody similar: active promotions only (p2 starts later)


def test_seed_scenario_has_overdue_reorders_and_stays_within_history() -> None:
    """F-13 demo: deterministic insights on the seed, every SKU bought by that customer."""
    customers = seed("customers")
    history: dict[str, list[dict[str, Any]]] = {}
    for entry in seed("order-history"):
        history.setdefault(entry["customerId"], []).append(entry)
    insights = {i["customerId"]: i for i in analyze(customers, history, seed("promotions"), AS_OF)}
    assert set(insights) == {c["customerId"] for c in customers}
    marco = insights["cus_001"]
    assert {"OLIO-EVO-5L", "POM-PELATI-2500"} <= {r["sku"] for r in marco["expectedReorders"]}
    assert any(r["dueAt"] < marco["updatedAt"] for r in marco["expectedReorders"])
    for customer_id, item in insights.items():
        own = {li["sku"] for o in history.get(customer_id, []) for li in o["lines"]}
        assert {r["sku"] for r in item["expectedReorders"]} | set(item["droppedProducts"]) <= own
        assert len(item["suggestions"]) <= 3


@pytest.fixture
def aws(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    for name, value in {
        "AWS_DEFAULT_REGION": "eu-west-1",
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "TABLE_PREFIX": "suppliagent-test-",
    }.items():
        monkeypatch.setenv(name, value)
    with mock_aws():
        reset_clients()
        resource: Any = boto3.resource("dynamodb")
        for name, keys in {
            "customers": ["customerId"],
            "promotions": ["promoId"],
            "customer-insights": ["customerId"],
            "order-history": ["customerId", "dateOrderId"],
        }.items():
            resource.create_table(
                TableName=f"suppliagent-test-{name}",
                KeySchema=[
                    {"AttributeName": k, "KeyType": "HASH" if i == 0 else "RANGE"}
                    for i, k in enumerate(keys)
                ],
                AttributeDefinitions=[{"AttributeName": k, "AttributeType": "S"} for k in keys],
                BillingMode="PAY_PER_REQUEST",
            )
        yield resource
        reset_clients()


def test_handler_writes_insights_and_keeps_the_trigger_cooldown(aws: Any) -> None:
    aws.Table("suppliagent-test-customers").put_item(
        Item={"customerId": "cus_001", "venueType": "pizzeria", "zone": "Z1"}
    )
    for day in ("2026-10-01", "2026-10-08", "2026-10-15"):
        aws.Table("suppliagent-test-order-history").put_item(
            Item={
                "customerId": "cus_001",
                "dateOrderId": f"{day}#ord_{day}",
                "date": day,
                "lines": [{"sku": "OIL", "quantity": Decimal(2)}],
            }
        )
    aws.Table("suppliagent-test-customer-insights").put_item(
        Item={"customerId": "cus_001", "lastProposalAt": "2026-10-25T08:00:00Z"}
    )
    assert handler({"asOf": "2026-10-28T01:00:00Z"}, None) == {
        "customers": 1,
        "expectedReorders": 1,
        "droppedProducts": 0,
    }
    item = aws.Table("suppliagent-test-customer-insights").get_item(Key={"customerId": "cus_001"})[
        "Item"
    ]
    assert item["lastProposalAt"] == "2026-10-25T08:00:00Z"
    assert item["expectedReorders"][0]["dueAt"] == "2026-10-22T09:00:00Z"
    assert item["updatedAt"] == "2026-10-28T01:00:00Z"
