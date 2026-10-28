"""Turn Dispatcher (T-22, T-67): FN-26 acceptance criteria, flows §3.3 cases C1-C5, E-05, E-11,
E-12 (courtesy at the first failed turn, handoff LOW_CONFIDENCE at the second)."""

import json
from collections.abc import Callable, Iterator
from typing import Any

import boto3
import pytest
from moto import mock_aws
from suppliagent_shared.aws import reset_clients
from turn_dispatcher import handler as dispatcher
from turn_dispatcher.handler import AgentTurnError

NOW = 1_800_000_000_000  # epoch ms
CONV = "conv_con001"
TEXT_MS, MEDIA_MS, MAX_MS, LOCK_MS = 3000, 6000, 15000, 120000
CALLER = {
    "channel": "WHATSAPP",
    "from": "+393330000001",
    "role": "CUSTOMER_CONTACT",
    "contactId": "con_001",
    "customerIds": ["cus_001"],
    "locale": "it-IT",
}


class Fakes:
    """The SQS, Lambda and AgentCore clients, recording calls. `on_agent` runs mid-turn."""

    def __init__(self) -> None:
        self.now = NOW
        self.flushes: list[dict[str, Any]] = []
        self.turns: list[dict[str, Any]] = []
        self.notifications: list[dict[str, Any]] = []
        self.reply: dict[str, Any] = {"conversationId": CONV, "reply": "Ciao!"}
        self.agent_error: Exception | None = None
        self.notifier_error: str | None = None  # errorType of a failed Notifier invocation
        self.on_agent: Callable[[], None] | None = None

    def send_message(self, **request: Any) -> None:
        self.flushes.append(
            {"delay": request["DelaySeconds"], **json.loads(request["MessageBody"])}
        )

    def invoke_agent_runtime(self, **request: Any) -> dict[str, Any]:
        self.turns.append(json.loads(request["payload"]))
        if self.on_agent:
            self.on_agent()
        if self.agent_error:
            raise self.agent_error
        body = json.dumps(self.reply).encode()
        return {"response": type("Body", (), {"read": lambda _s: body})()}

    def invoke(self, **request: Any) -> dict[str, Any]:
        self.notifications.append(json.loads(request["Payload"]))
        if not self.notifier_error:
            return {}
        body = json.dumps({"errorType": self.notifier_error}).encode()
        return {
            "FunctionError": "Unhandled",
            "Payload": type("Body", (), {"read": lambda _s: body})(),
        }


@pytest.fixture(autouse=True)
def fakes(monkeypatch: pytest.MonkeyPatch) -> Iterator[Fakes]:
    for name, value in {
        "AWS_DEFAULT_REGION": "eu-west-1",
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "TABLE_PREFIX": "suppliagent-test-",
        "EVENT_BUS_NAME": "suppliagent-test-events",
        "TURN_FLUSH_QUEUE_URL": "https://sqs.test/turn-flush",
        "AGENT_RUNTIME_ARN": "arn:aws:bedrock-agentcore:eu-west-1:1:runtime/x",
        "NOTIFIER_FUNCTION_NAME": "suppliagent-test-notifier",
        "DEBOUNCE_TEXT_MS": str(TEXT_MS),
        "DEBOUNCE_MEDIA_MS": str(MEDIA_MS),
        "DEBOUNCE_MAX_MS": str(MAX_MS),
        "TURN_LOCK_TTL_MS": str(LOCK_MS),
        "TURN_MAX_MESSAGES": "3",
    }.items():
        monkeypatch.setenv(name, value)
    fake = Fakes()
    monkeypatch.setattr(dispatcher, "_sqs", lambda: fake)
    monkeypatch.setattr(dispatcher, "_lambda", lambda: fake)
    monkeypatch.setattr(dispatcher, "_agent", lambda: fake)
    monkeypatch.setattr(dispatcher, "_now_ms", lambda: fake.now)
    with mock_aws():
        reset_clients()
        resource: Any = boto3.resource("dynamodb")
        for name_, key in (("turn-buffer", "conversationId"), ("conversations", "conversationId")):
            resource.create_table(
                TableName=f"suppliagent-test-{name_}",
                KeySchema=[{"AttributeName": key, "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": key, "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
            )
        boto3.client("events").create_event_bus(Name="suppliagent-test-events")
        yield fake
        reset_clients()


def message(
    message_id: str, ts: str = "2026-10-26T10:00:00.000Z", kind: str | None = None, **extra: Any
) -> dict[str, Any]:
    item: dict[str, Any] = {"messageId": message_id, "ts": ts, "text": "ciao"} | extra
    if kind:
        item["attachments"] = [{"type": kind, "s3Uri": f"s3://media/{message_id}"}]
    return item


def put_buffer(
    pending: list[dict[str, Any]],
    last_ago_ms: int = 10_000,
    first_ago_ms: int | None = None,
    conversation_id: str = CONV,
    **extra: Any,
) -> None:
    """Messages as the Router stores them: each with its own arrival time `at`. The newest
    arrived `last_ago_ms` ago, the oldest `first_ago_ms` ago, the others as the newest."""
    first_ago = first_ago_ms if first_ago_ms is not None else last_ago_ms
    stamped = [
        {"at": NOW - (first_ago if i == 0 else last_ago_ms)} | m for i, m in enumerate(pending)
    ]
    table: Any = boto3.resource("dynamodb").Table("suppliagent-test-turn-buffer")
    table.put_item(
        Item={"conversationId": conversation_id, "pending": stamped, "caller": CALLER} | extra
    )


def buffer(conversation_id: str = CONV) -> dict[str, Any]:
    table: Any = boto3.resource("dynamodb").Table("suppliagent-test-turn-buffer")
    item: dict[str, Any] = table.get_item(Key={"conversationId": conversation_id})["Item"]
    return item


def flush(conversation_id: str = CONV) -> None:
    body = json.dumps({"conversationId": conversation_id})
    dispatcher.handler({"Records": [{"body": body}]}, None)


def test_single_message_gets_one_turn_and_one_reply(fakes: Fakes) -> None:  # C1
    put_buffer([message("msg_1")])

    flush()

    [turn] = fakes.turns
    assert (turn["role"], turn["contactId"], turn["channelAddress"]) == (
        "CUSTOMER_CONTACT",
        "con_001",
        "WHATSAPP#+393330000001",
    )
    assert turn["activeCustomerId"] == "cus_001"
    assert turn["proactive"] is False
    assert turn["arrivedDuringPreviousTurn"] is False
    assert [m["messageId"] for m in turn["messages"]] == ["msg_1"]
    [sent] = fakes.notifications
    assert (sent["kind"], sent["conversationId"], sent["text"]) == ("reply", CONV, "Ciao!")
    assert sent["idempotencyKey"] == "turn#msg_1#msg_1"
    item = buffer()
    assert item["pending"] == [] and "lockUntil" not in item and "afterTurn" not in item
    assert fakes.flushes == []


def test_reply_options_of_the_agent_reach_the_notifier(fakes: Fakes) -> None:  # T-25
    options = {
        "kind": "ORDER_SUMMARY",
        "orderId": "ord_1",
        "options": [{"id": "order_confirm", "title": "Confermo"}],
    }
    fakes.reply = {"conversationId": CONV, "reply": "Riepilogo", "interactive": options}
    put_buffer([message("msg_1")])

    flush()

    [sent] = fakes.notifications
    assert sent["interactive"] == options


def test_options_refused_by_the_notifier_still_send_the_text(fakes: Fakes) -> None:  # T-25
    fakes.reply = {"conversationId": CONV, "reply": "Quale?", "interactive": {"kind": "BAD"}}
    plain_invoke = fakes.invoke

    def invoke(**request: Any) -> dict[str, Any]:
        if "interactive" not in json.loads(request["Payload"]):
            return plain_invoke(**request)
        fakes.notifications.append(json.loads(request["Payload"]))
        body = json.dumps({"errorType": "ValidationError"}).encode()
        return {"FunctionError": "Unhandled", "Payload": type("B", (), {"read": lambda _s: body})()}

    fakes.invoke = invoke  # type: ignore[method-assign]
    put_buffer([message("msg_1")])

    flush()

    assert len(fakes.turns) == 1  # the agent is not run again
    first, second = fakes.notifications
    assert "interactive" in first and "interactive" not in second
    assert second["text"] == "Quale?" and second["idempotencyKey"] == first["idempotencyKey"]
    assert buffer()["pending"] == []


def test_a_tap_reaches_the_agent_with_the_message_it_replies_to(fakes: Fakes) -> None:  # T-25
    tap = {"id": "order_confirm", "title": "Confermo", "contextId": "wamid.SUMMARY"}
    put_buffer([message("msg_1") | {"interactiveReply": tap}])

    flush()

    assert fakes.turns[0]["messages"][0]["interactiveReply"] == tap
    assert "interactive" not in fakes.notifications[0]  # a plain reply has no options


def test_flush_before_the_debounce_is_over_waits_for_it(fakes: Fakes) -> None:
    put_buffer([message("msg_1")], last_ago_ms=1000)

    flush()

    assert fakes.turns == []
    assert fakes.flushes == [{"delay": 2, "conversationId": CONV}]  # 3 s debounce - 1 s elapsed
    assert len(buffer()["pending"]) == 1


def test_photo_voice_and_text_burst_is_one_turn_in_order_of_arrival(fakes: Fakes) -> None:  # C2
    put_buffer(  # appended out of order by parallel router invocations
        [
            message("msg_c", "2026-10-26T10:00:04.000Z"),
            message("msg_a", "2026-10-26T10:00:00.000Z", "image"),
            message("msg_b", "2026-10-26T10:00:02.000Z", "audio"),
        ],
        last_ago_ms=7000,
    )

    flush()

    [turn] = fakes.turns  # FN-26: one answer for the whole burst
    assert [m["messageId"] for m in turn["messages"]] == ["msg_a", "msg_b", "msg_c"]
    assert turn["messages"][0]["attachments"] == [{"type": "image", "s3Uri": "s3://media/msg_a"}]
    assert len(fakes.notifications) == 1
    assert buffer()["pending"] == []


def test_media_burst_waits_longer_than_text(fakes: Fakes) -> None:
    put_buffer([message("msg_1", kind="image")], last_ago_ms=4000)  # past 3 s, not 6 s

    flush()

    assert fakes.turns == []
    assert fakes.flushes[0]["delay"] == 2


def test_burst_longer_than_the_maximum_is_answered_anyway(fakes: Fakes) -> None:  # C4
    put_buffer([message("msg_1"), message("msg_2")], last_ago_ms=500, first_ago_ms=16_000)

    flush()

    assert len(fakes.turns) == 1


def test_flush_with_nothing_pending_does_nothing(fakes: Fakes) -> None:
    flush()  # unknown conversation
    put_buffer([])
    flush()

    assert fakes.turns == [] and fakes.flushes == []


def test_messages_during_a_turn_become_one_following_turn(fakes: Fakes) -> None:  # C3
    put_buffer([message("msg_1")])

    def arrive() -> None:  # the router appends while the agent works
        table: Any = boto3.resource("dynamodb").Table("suppliagent-test-turn-buffer")
        table.update_item(
            Key={"conversationId": CONV},
            UpdateExpression="SET pending = list_append(pending, :m)",
            ExpressionAttributeValues={
                ":m": [
                    message("msg_2", "2026-10-26T10:00:09.000Z", at=NOW - 500),
                    message("msg_3", at=NOW),
                ],
            },
        )
        fakes.on_agent = None

    fakes.on_agent = arrive

    flush()

    assert len(fakes.turns) == 1
    item = buffer()
    assert [m["messageId"] for m in item["pending"]] == ["msg_2", "msg_3"]
    assert item["afterTurn"] is True and "lockUntil" not in item
    # They keep their own arrival times: debounceMax is not stretched by the turn that ran.
    assert [m["at"] for m in item["pending"]] == [NOW - 500, NOW]
    assert fakes.flushes == [{"delay": 3, "conversationId": CONV}]

    fakes.now += TEXT_MS
    flush()

    # Sorted by arrival timestamp, not by append order.
    assert [m["messageId"] for m in fakes.turns[1]["messages"]] == ["msg_3", "msg_2"]
    assert fakes.turns[1]["arrivedDuringPreviousTurn"] is True
    assert buffer()["pending"] == []


def test_turn_in_progress_blocks_a_second_one(fakes: Fakes) -> None:
    put_buffer([message("msg_1")], lockUntil=NOW + 30_000)

    flush()

    assert fakes.turns == []
    assert fakes.flushes == [{"delay": 31, "conversationId": CONV}]  # again after the lock expires
    assert len(buffer()["pending"]) == 1


def test_orphan_lock_expires_and_nothing_is_lost(fakes: Fakes) -> None:  # C5, E-11
    put_buffer([message("msg_1")], lockUntil=NOW - 1)

    flush()

    assert len(fakes.turns) == 1 and len(fakes.notifications) == 1
    assert buffer()["pending"] == []


def test_two_conversations_do_not_wait_for_each_other(fakes: Fakes) -> None:
    put_buffer([message("msg_1")], lockUntil=NOW + 60_000)  # conv_con001 is busy
    put_buffer([message("msg_9")], conversation_id="conv_con002")

    flush("conv_con002")

    [turn] = fakes.turns
    assert turn["conversationId"] == "conv_con002"
    assert buffer("conv_con002")["pending"] == []
    assert len(buffer()["pending"]) == 1


def conversation(**extra: Any) -> dict[str, Any]:
    table: Any = boto3.resource("dynamodb").Table("suppliagent-test-conversations")
    table.put_item(Item={"conversationId": CONV, "mode": "AGENT"} | extra)
    item: dict[str, Any] = table.get_item(Key={"conversationId": CONV})["Item"]
    return item


def stored_conversation() -> dict[str, Any]:
    table: Any = boto3.resource("dynamodb").Table("suppliagent-test-conversations")
    item: dict[str, Any] = table.get_item(Key={"conversationId": CONV})["Item"]
    return item


def test_agent_failure_keeps_the_messages_frees_the_lock_and_apologises(fakes: Fakes) -> None:
    put_buffer([message("msg_1")])  # E-05
    fakes.agent_error = RuntimeError("ThrottlingException")

    with pytest.raises(RuntimeError):
        flush()  # SQS redelivers the flush (after the visibility timeout: a delayed flush)

    item = buffer()
    assert len(item["pending"]) == 1 and item["turnFailures"] == 1
    assert item["lockUntil"] == NOW + LOCK_MS // 2  # backoff before the retry
    [courtesy] = fakes.notifications
    assert courtesy["idempotencyKey"] == "courtesy#msg_1"
    assert "tra un attimo" in courtesy["text"]

    fakes.now = NOW + LOCK_MS // 2 + 1  # the SQS retry, after the visibility timeout
    fakes.agent_error = None
    flush()
    assert len(fakes.turns) == 2 and buffer()["pending"] == []
    assert "turnFailures" not in buffer()  # a turn that worked resets the count
    assert [n["idempotencyKey"] for n in fakes.notifications] == [
        "courtesy#msg_1",
        "turn#msg_1#msg_1",
    ]


def test_second_failure_hands_over_to_a_colleague(fakes: Fakes) -> None:  # E-12
    conversation()
    put_buffer([message("msg_1"), message("msg_2", ts="2026-10-26T10:00:01.000Z")])
    fakes.agent_error = RuntimeError("ReadTimeoutError")
    with pytest.raises(RuntimeError):
        flush()
    fakes.now = NOW + LOCK_MS // 2 + 1

    flush()  # the retry fails too: no exception, so the flush does not end in the DLQ

    handoff = stored_conversation()
    assert handoff["mode"] == "HUMAN"
    assert handoff["handoff"]["reason"] == "LOW_CONFIDENCE" and handoff["handoff"]["by"] == "AGENT"
    assert [n["idempotencyKey"] for n in fakes.notifications] == [
        "courtesy#msg_1",
        "handoff#msg_1",
    ]
    assert "collega" in fakes.notifications[-1]["text"]
    item = buffer()
    assert item["pending"] == [] and "lockUntil" not in item and "turnFailures" not in item


def test_courtesy_and_handoff_messages_follow_the_contact_language(fakes: Fakes) -> None:
    conversation()
    put_buffer([message("msg_1")], caller=CALLER | {"locale": "en-GB"})
    fakes.agent_error = AgentTurnError()
    with pytest.raises(AgentTurnError):
        flush()
    fakes.now = NOW + LOCK_MS // 2 + 1
    flush()
    assert "moment" in fakes.notifications[0]["text"]
    assert "colleague" in fakes.notifications[1]["text"]


def test_a_failed_courtesy_message_does_not_hide_the_turn_error(fakes: Fakes) -> None:
    put_buffer([message("msg_1")])
    fakes.agent_error = RuntimeError("ThrottlingException")
    fakes.notifier_error = "ThrottlingException"

    with pytest.raises(RuntimeError, match="ThrottlingException"):
        flush()

    assert len(buffer()["pending"]) == 1 and buffer()["turnFailures"] == 1


def test_another_flush_of_the_burst_waits_for_the_backoff(fakes: Fakes) -> None:
    conversation()
    put_buffer([message("msg_1"), message("msg_2", ts="2026-10-26T10:00:01.000Z")])
    fakes.agent_error = RuntimeError("ThrottlingException")
    with pytest.raises(RuntimeError):
        flush()

    fakes.now = NOW + 2000  # the second message's own flush, seconds later
    flush()

    assert len(fakes.turns) == 1  # no immediate second attempt, so no early handoff
    assert stored_conversation()["mode"] == "AGENT"
    assert fakes.flushes[-1]["delay"] >= LOCK_MS // 2 // 1000 - 2  # back after the backoff


def test_a_turn_takes_at_most_the_configured_number_of_messages(fakes: Fakes) -> None:
    put_buffer([message(f"msg_{i}", ts=f"2026-10-26T10:00:0{i}.000Z") for i in range(5)])

    flush()

    [turn] = fakes.turns
    assert [m["messageId"] for m in turn["messages"]] == ["msg_0", "msg_1", "msg_2"]
    item = buffer()
    assert [m["messageId"] for m in item["pending"]] == ["msg_3", "msg_4"]
    assert item["afterTurn"] is True and len(fakes.flushes) == 1  # the rest: one more turn


def test_invalid_request_from_the_runtime_is_an_error_not_a_reply(fakes: Fakes) -> None:
    put_buffer([message("msg_1")])
    fakes.reply = {"error": "INVALID_REQUEST"}

    with pytest.raises(AgentTurnError):
        flush()

    # no reply, only the courtesy message of the first failure (E-05)
    assert [n["idempotencyKey"] for n in fakes.notifications] == ["courtesy#msg_1"]
    assert len(buffer()["pending"]) == 1


def test_transient_notifier_failure_keeps_the_messages(fakes: Fakes) -> None:
    put_buffer([message("msg_1")])
    fakes.notifier_error = "ThrottlingException"

    with pytest.raises(AgentTurnError):
        flush()

    assert len(buffer()["pending"]) == 1 and "lockUntil" not in buffer()


@pytest.mark.parametrize("error", ["ChannelUnavailableError", "AccessDeniedError"])
def test_permanent_notifier_failure_ends_the_turn_instead_of_rerunning_the_agent(
    fakes: Fakes, error: str
) -> None:
    put_buffer([message("msg_1")])
    fakes.notifier_error = error

    flush()  # no exception: a retry would run the agent's tools again for nothing

    assert len(fakes.turns) == 1 and buffer()["pending"] == []


def test_failed_turn_keeps_the_after_turn_flag_for_the_retry(fakes: Fakes) -> None:
    put_buffer([message("msg_1")], afterTurn=True)
    fakes.agent_error = RuntimeError("ThrottlingException")
    with pytest.raises(RuntimeError):
        flush()

    fakes.now = NOW + LOCK_MS // 2 + 1  # after the backoff
    fakes.agent_error = None
    flush()

    assert fakes.turns[1]["arrivedDuringPreviousTurn"] is True
    assert "afterTurn" not in buffer()  # consumed by the turn that completed


def test_release_error_does_not_hide_the_turn_error(
    fakes: Fakes, monkeypatch: pytest.MonkeyPatch
) -> None:
    put_buffer([message("msg_1")])
    fakes.agent_error = RuntimeError("ThrottlingException")

    def broken(*_args: Any) -> None:
        raise OSError("DynamoDB down")

    monkeypatch.setattr(dispatcher, "_release", broken)

    with pytest.raises(RuntimeError, match="ThrottlingException"):
        flush()


def test_empty_reply_sends_nothing(fakes: Fakes) -> None:
    put_buffer([message("msg_1")])
    fakes.reply = {"conversationId": CONV, "reply": ""}

    flush()

    assert fakes.notifications == [] and buffer()["pending"] == []


@pytest.mark.parametrize(
    ("last_inbound", "open_"),
    [("2026-10-26T10:00:00Z", True), ("2020-01-01T00:00:00Z", False), (None, False)],
)
def test_whatsapp_window_comes_from_the_last_whatsapp_message(
    fakes: Fakes, monkeypatch: pytest.MonkeyPatch, last_inbound: str | None, open_: bool
) -> None:
    import datetime

    class Clock(datetime.datetime):
        @classmethod
        def now(cls, tz: Any = None) -> "Clock":
            return cls(2026, 10, 26, 12, 0, tzinfo=tz)

    monkeypatch.setattr(dispatcher, "datetime", Clock)
    conversations: Any = boto3.resource("dynamodb").Table("suppliagent-test-conversations")
    conversations.put_item(
        Item={"conversationId": CONV}
        | ({"lastWhatsappInboundAt": last_inbound} if last_inbound else {})
    )
    put_buffer([message("msg_1")])

    flush()

    assert fakes.turns[0]["whatsappWindowOpen"] is open_


def test_active_order_comes_from_the_latest_message_that_carries_one(fakes: Fakes) -> None:
    put_buffer([message("msg_1", orderId="ord_1"), message("msg_2", "2026-10-26T10:00:01.000Z")])

    flush()

    assert fakes.turns[0]["activeOrderId"] == "ord_1"


def test_several_venues_leave_the_active_one_to_the_agent(fakes: Fakes) -> None:  # F-02.C5
    put_buffer([message("msg_1")], caller=CALLER | {"customerIds": ["cus_001", "cus_005"]})

    flush()

    assert fakes.turns[0]["activeCustomerId"] is None
    assert fakes.turns[0]["customerIds"] == ["cus_001", "cus_005"]


def test_conversation_handed_off_after_the_router_queued_the_messages_gets_no_turn(
    fakes: Fakes,
) -> None:  # FN-24: while HUMAN the agent stays silent
    conversations: Any = boto3.resource("dynamodb").Table("suppliagent-test-conversations")
    conversations.put_item(Item={"conversationId": CONV, "mode": "HUMAN"})
    put_buffer([message("msg_1")])

    flush()

    assert fakes.turns == [] and fakes.notifications == []
    item = buffer()
    assert item["pending"] == [] and "lockUntil" not in item  # no replay after Release


def test_handoff_drops_also_the_messages_over_the_cap(fakes: Fakes) -> None:
    conversation()
    put_buffer([message(f"msg_{i}", ts=f"2026-10-26T10:00:0{i}.000Z") for i in range(5)])
    fakes.agent_error = RuntimeError("ThrottlingException")
    with pytest.raises(RuntimeError):
        flush()
    fakes.now = NOW + LOCK_MS // 2 + 1
    flush()

    assert stored_conversation()["mode"] == "HUMAN"
    assert buffer()["pending"] == [] and fakes.flushes == []
