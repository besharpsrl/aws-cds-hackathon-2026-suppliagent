"""FN-19, F-13: who gets a reorder proposal, at most once every 7 days, never at night or without
consent, never with an order in progress. Nothing is sent from here."""

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import boto3
import proactive_trigger.handler as trigger
import pytest
from moto import mock_aws
from suppliagent_shared.aws import reset_clients

MORNING = "2026-10-28T08:30:00Z"  # 09:30 in Rome


@pytest.fixture(autouse=True)
def aws(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    for name, value in {
        "AWS_DEFAULT_REGION": "eu-west-1",
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "TABLE_PREFIX": "suppliagent-test-",
        "EVENT_BUS_NAME": "bus",
        "REORDER_DUE_FACTOR": "1.5",
        "REORDER_COOLDOWN_DAYS": "7",
        "QUIET_HOURS": "21:00-07:00",
    }.items():
        monkeypatch.setenv(name, value)
    with mock_aws():
        reset_clients()
        resource: Any = boto3.resource("dynamodb")
        for name in ("contacts", "customer-insights"):
            key = "contactId" if name == "contacts" else "customerId"
            resource.create_table(
                TableName=f"suppliagent-test-{name}",
                KeySchema=[{"AttributeName": key, "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": key, "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
            )
        resource.create_table(
            TableName="suppliagent-test-orders",
            KeySchema=[{"AttributeName": "orderId", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": a, "AttributeType": "S"}
                for a in ("orderId", "customerId", "createdAt")
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "by-customerId",
                    "KeySchema": [
                        {"AttributeName": "customerId", "KeyType": "HASH"},
                        {"AttributeName": "createdAt", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        contacts = resource.Table("suppliagent-test-contacts")
        contacts.put_item(
            Item={
                "contactId": "con_001",
                "status": "VERIFIED",
                "customerIds": ["cus_001"],
                "proactiveConsent": True,
            }
        )
        contacts.put_item(
            Item={
                "contactId": "con_002",
                "status": "VERIFIED",
                "customerIds": ["cus_002"],
                "proactiveConsent": False,
            }
        )
        # a stranger who claimed cus_002 and said yes: not verified, never counts
        contacts.put_item(
            Item={
                "contactId": "con_009",
                "status": "PENDING_VERIFICATION",
                "customerIds": ["cus_002"],
                "proactiveConsent": True,
            }
        )
        yield resource
        reset_clients()


@pytest.fixture(autouse=True)
def events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    sent: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(trigger, "put_event", lambda _s, kind, detail: sent.append((kind, detail)))
    return sent


def insights(aws: Any, customer_id: str = "cus_001", **extra: Any) -> None:
    aws.Table("suppliagent-test-customer-insights").put_item(
        Item={
            "customerId": customer_id,
            "expectedReorders": [
                # 10 days ago, every 6 days: overdue (>= 9 days)
                {
                    "sku": "OLIO-EVO-5L",
                    "everyDays": Decimal(6),
                    "lastOrderedAt": "2026-10-18T09:00:00Z",
                },
                # 4 days ago, every 7 days: not yet
                {
                    "sku": "BURRATA-125",
                    "everyDays": Decimal(7),
                    "lastOrderedAt": "2026-10-24T09:00:00Z",
                },
            ],
            **extra,
        }
    )


def run(now: str = MORNING) -> dict[str, int]:
    return trigger.handler({"now": now}, None)


def test_overdue_customer_with_consent_is_proposed_once(
    aws: Any, events: list[tuple[str, dict[str, Any]]]
) -> None:
    insights(aws)
    assert run() == {"due": 1}
    assert events == [
        (
            "reorder.due",
            {"customerId": "cus_001", "contactIds": ["con_001"], "skus": ["OLIO-EVO-5L"]},
        )
    ]
    item = aws.Table("suppliagent-test-customer-insights").get_item(Key={"customerId": "cus_001"})[
        "Item"
    ]
    assert item["lastProposalAt"] == "2026-10-28T08:30:00Z"
    assert run("2026-11-03T08:30:00Z") == {"cooldown": 1}  # 6 days later
    assert run("2026-11-04T08:30:00Z") == {"due": 1}  # 7 days later
    assert [kind for kind, _ in events] == ["reorder.due", "reorder.due"]


def test_nothing_is_overdue_nothing_happens(aws: Any, events: list[Any]) -> None:
    insights(aws)
    assert run("2026-10-25T08:30:00Z") == {}
    assert events == []


def test_no_consent_only_signals_the_rep(aws: Any, events: list[Any]) -> None:
    """F-13.C4: no message, only `reorder.skipped` (consent false, never asked or only from a
    contact still to verify), once per cooldown."""
    insights(aws, "cus_002")
    insights(aws, "cus_003")
    assert run() == {"noConsent": 2}
    assert events == [
        ("reorder.skipped", {"customerId": "cus_002", "reason": "NO_CONSENT"}),
        ("reorder.skipped", {"customerId": "cus_003", "reason": "NO_CONSENT"}),
    ]
    assert run("2026-10-29T08:30:00Z") == {"cooldown": 2}
    assert len(events) == 2


def test_order_in_progress_means_no_proposal(aws: Any, events: list[Any]) -> None:
    """F-13.C1, with or without consent."""
    insights(aws)
    insights(aws, "cus_002")
    aws.Table("suppliagent-test-orders").put_item(
        Item={"orderId": "ord_2", "customerId": "cus_002", "createdAt": "1", "status": "DRAFT"}
    )
    orders = aws.Table("suppliagent-test-orders")
    orders.put_item(
        Item={
            "orderId": "ord_old",
            "customerId": "cus_001",
            "createdAt": "1",
            "status": "DELIVERED",
        }
    )
    orders.put_item(
        Item={
            "orderId": "ord_new",
            "customerId": "cus_001",
            "createdAt": "2",
            "status": "PENDING_CONFIRMATION",
        }
    )
    assert run() == {"orderInProgress": 2}
    assert events == []


@pytest.mark.parametrize("now", ["2026-10-28T20:30:00Z", "2026-10-28T05:30:00Z"])
def test_quiet_hours(aws: Any, events: list[Any], now: str) -> None:
    insights(aws)
    assert run(now) == {}
    assert events == []
