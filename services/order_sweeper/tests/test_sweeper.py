"""FN-12: reminder at 2 h, expiry at the end of the day, nothing at night, nothing confirmed."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import boto3
import order_sweeper.handler as sweeper
import pytest
from moto import mock_aws
from suppliagent_shared.aws import reset_clients

SINCE = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)  # 13:00 in Rome


class Notifier:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error: str | None = None

    def invoke(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(json.loads(kwargs["Payload"]))

        class Payload:
            def __init__(self, error: str | None) -> None:
                self.error = error

            def read(self) -> bytes:
                return json.dumps({"errorType": self.error}).encode()

        return {"FunctionError": "Unhandled", "Payload": Payload(self.error)} if self.error else {}


class Clock:
    now = SINCE


@pytest.fixture(autouse=True)
def aws(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    for name, value in {
        "AWS_DEFAULT_REGION": "eu-west-1",
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "TABLE_PREFIX": "suppliagent-test-",
        "EVENT_BUS_NAME": "bus",
        "NOTIFIER_FUNCTION_NAME": "notifier",
        "PENDING_REMINDER_HOURS": "2",
        "QUIET_HOURS": "21:00-07:00",
        "DELIVERY_CUTOFF": "18:00",
    }.items():
        monkeypatch.setenv(name, value)
    with mock_aws():
        reset_clients()
        resource: Any = boto3.resource("dynamodb")
        resource.create_table(
            TableName="suppliagent-test-orders",
            KeySchema=[{"AttributeName": "orderId", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "orderId", "AttributeType": "S"},
                {"AttributeName": "status", "AttributeType": "S"},
                {"AttributeName": "updatedAt", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "by-status",
                    "KeySchema": [
                        {"AttributeName": "status", "KeyType": "HASH"},
                        {"AttributeName": "updatedAt", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        resource.create_table(
            TableName="suppliagent-test-conversations",
            KeySchema=[{"AttributeName": "conversationId", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "conversationId", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        resource.Table("suppliagent-test-conversations").put_item(
            Item={"conversationId": "conv_1", "lastInboundLocale": "it-IT"}
        )
        resource.Table("suppliagent-test-conversations").put_item(
            Item={"conversationId": "conv_en", "lastInboundLocale": "en-GB"}
        )
        yield resource
        reset_clients()


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> type[Clock]:
    Clock.now = SINCE
    monkeypatch.setattr(sweeper, "_now", lambda: Clock.now)
    return Clock


@pytest.fixture(autouse=True)
def notifier(monkeypatch: pytest.MonkeyPatch) -> Notifier:
    fake = Notifier()
    monkeypatch.setattr(sweeper, "_lambda", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    sent: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(sweeper, "put_event", lambda _s, kind, detail: sent.append((kind, detail)))
    return sent


def add(aws: Any, order_id: str = "ord_1", **extra: Any) -> None:
    aws.Table("suppliagent-test-orders").put_item(
        Item={
            "orderId": order_id,
            "status": "PENDING_CONFIRMATION",
            "conversationId": "conv_1",
            "pendingSince": "2026-10-28T12:00:00.000Z",
            "updatedAt": "2026-10-28T12:00:00.000Z",
            "deliveryDate": "2026-10-29",
            "version": 3,
            "lines": [{"lineId": "l1", "status": "MATCHED"}, {"lineId": "l2", "status": "REMOVED"}],
            **extra,
        }
    )


def status(aws: Any, order_id: str = "ord_1") -> dict[str, Any]:
    item: dict[str, Any] = aws.Table("suppliagent-test-orders").get_item(Key={"orderId": order_id})[
        "Item"
    ]
    return item


def test_nothing_happens_before_two_hours(aws: Any, notifier: Notifier, clock: type[Clock]) -> None:
    add(aws)
    clock.now = datetime(2026, 10, 28, 13, 30, tzinfo=UTC)
    assert sweeper.handler({}, None) == {}
    assert notifier.calls == []


def test_reminder_after_two_hours_once(aws: Any, notifier: Notifier, clock: type[Clock]) -> None:
    add(aws)
    clock.now = datetime(2026, 10, 28, 14, 5, tzinfo=UTC)
    assert sweeper.handler({}, None) == {"reminded": 1}
    (call,) = notifier.calls
    assert call["kind"] == "reply" and call["conversationId"] == "conv_1"
    assert call["idempotencyKey"] == "reminder#ord_1#2026-10-28T12:00:00.000Z"
    assert "1 righe" in call["text"] and "29/10" in call["text"] and "Confermo" in call["text"]
    # outside the WhatsApp window the Notifier sends the approved template (T-24)
    assert call["template"] == {
        "name": "order_pending_reminder",
        "params": ["1", "giovedì 29 ottobre", "oggi alle 18:00"],
    }
    assert sweeper.handler({}, None) == {}  # not again
    assert len(notifier.calls) == 1
    assert status(aws)["status"] == "PENDING_CONFIRMATION"


def test_a_new_summary_restarts_the_reminder(
    aws: Any, notifier: Notifier, clock: type[Clock]
) -> None:
    add(aws, reminderSentAt="2026-10-28T10:00:00.000Z", pendingSince="2026-10-28T12:30:00.000Z")
    clock.now = datetime(2026, 10, 28, 14, 45, tzinfo=UTC)
    assert sweeper.handler({}, None) == {"reminded": 1}


def test_reminder_in_english(aws: Any, notifier: Notifier, clock: type[Clock]) -> None:
    add(aws, conversationId="conv_en")
    clock.now = datetime(2026, 10, 28, 14, 5, tzinfo=UTC)
    sweeper.handler({}, None)
    assert "Reply “Confirm”" in notifier.calls[0]["text"]
    assert notifier.calls[0]["template"]["params"][1:] == ["Thursday 29 October", "today at 18:00"]


def test_order_expires_at_the_end_of_the_day_with_a_message(
    aws: Any, notifier: Notifier, clock: type[Clock], events: Any
) -> None:
    add(aws)
    clock.now = datetime(
        2026, 10, 29, 6, 5, tzinfo=UTC
    )  # 07:05 in Rome, after midnight and the night
    assert sweeper.handler({}, None) == {"expired": 1}
    item = status(aws)
    assert item["status"] == "EXPIRED" and item["version"] == 4
    assert notifier.calls[0]["idempotencyKey"] == "expired#ord_1"
    assert "template" not in notifier.calls[0]  # no approved template for the expiry
    assert "nessun ordine è stato inviato" in notifier.calls[0]["text"]
    assert events == [
        (
            "order.status_changed",
            {
                "orderId": "ord_1",
                "from": "PENDING_CONFIRMATION",
                "to": "EXPIRED",
                "ts": item["updatedAt"],
            },
        )
    ]


def test_nothing_is_written_at_night(aws: Any, notifier: Notifier, clock: type[Clock]) -> None:
    add(aws)
    for hour_utc in (20, 23, 4):  # 21:xx, 00:xx and 05:xx in Rome (CET): quiet
        clock.now = datetime(2026, 10, 28 if hour_utc == 20 else 29, hour_utc, 30, tzinfo=UTC)
        assert sweeper.handler({}, None) == {}
    assert notifier.calls == [] and status(aws)["status"] == "PENDING_CONFIRMATION"


def test_an_edit_during_the_sweep_wins(
    aws: Any, notifier: Notifier, clock: type[Clock], monkeypatch: pytest.MonkeyPatch
) -> None:
    add(aws)
    clock.now = datetime(2026, 10, 29, 8, 0, tzinfo=UTC)
    stale = sweeper._pending()
    aws.Table("suppliagent-test-orders").update_item(
        Key={"orderId": "ord_1"},
        UpdateExpression="SET version = :v",
        ExpressionAttributeValues={":v": 4},
    )  # the customer edited the order after the sweep read it
    monkeypatch.setattr(sweeper, "_pending", lambda: stale)
    assert sweeper.handler({}, None) == {}
    assert status(aws)["status"] == "PENDING_CONFIRMATION" and notifier.calls == []


def test_a_closed_whatsapp_window_does_not_block_the_expiry(
    aws: Any, notifier: Notifier, clock: type[Clock]
) -> None:
    add(aws)
    notifier.error = "ChannelUnavailableError"
    clock.now = datetime(2026, 10, 29, 8, 0, tzinfo=UTC)
    assert sweeper.handler({}, None) == {"expired": 1}
    assert status(aws)["status"] == "EXPIRED"


def test_transient_notifier_error_retries_the_reminder_later(
    aws: Any, notifier: Notifier, clock: type[Clock]
) -> None:
    add(aws)
    clock.now = datetime(2026, 10, 28, 14, 5, tzinfo=UTC)
    notifier.error = "ThrottlingException"
    assert sweeper.handler({}, None) == {}
    notifier.error = None
    assert sweeper.handler({}, None) == {"reminded": 1}


def test_permanent_notifier_error_does_not_retry_the_reminder(
    aws: Any, notifier: Notifier, clock: type[Clock]
) -> None:
    add(aws)
    clock.now = datetime(2026, 10, 28, 14, 5, tzinfo=UTC)
    notifier.error = "ChannelUnavailableError"
    assert sweeper.handler({}, None) == {"reminded": 1}
    assert sweeper.handler({}, None) == {}


def test_other_statuses_and_orders_without_conversation_are_left_alone(
    aws: Any, notifier: Notifier, clock: type[Clock]
) -> None:
    add(aws, "ord_draft", status="DRAFT")
    add(aws, "ord_console", conversationId=None)
    aws.Table("suppliagent-test-orders").update_item(
        Key={"orderId": "ord_console"}, UpdateExpression="REMOVE conversationId"
    )
    clock.now = datetime(2026, 10, 30, 8, 0, tzinfo=UTC)
    assert sweeper.handler({}, None) == {}
    assert status(aws, "ord_draft")["status"] == "DRAFT" and notifier.calls == []
