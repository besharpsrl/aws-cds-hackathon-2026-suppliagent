"""FN-24 / F-14: `handoff_to_human` and Release (`suppliagent_shared.handoff`)."""

from types import SimpleNamespace
from typing import Any

import pytest
import suppliagent_shared.handoff as shared
from suppliagent_shared.errors import InvalidInputError, NotFoundError
from suppliagent_shared.handoff import HandoffReason, release_handoff, start_handoff
from suppliagent_tool_orders.handler import lambda_handler
from suppliagent_tool_orders.handoff import HandoffInput, handoff_to_human

CONV = "conv_1"
Events = list[tuple[str, dict[str, Any]]]


def caller(
    role: str = "CUSTOMER_CONTACT", contact: str | None = "con_001", conv: str = CONV
) -> dict[str, Any]:
    return {
        "role": role,
        "channelAddress": "WHATSAPP#+393330000001",
        "conversationId": conv,
        **({"contactId": contact} if contact else {}),
    }


@pytest.fixture
def handoff_events(monkeypatch: pytest.MonkeyPatch) -> Events:
    sent: Events = []
    monkeypatch.setattr(shared, "put_event", lambda _src, kind, detail: sent.append((kind, detail)))
    return sent


@pytest.fixture
def conversations(aws: Any) -> Any:
    table = aws.Table("suppliagent-test-conversations")
    table.put_item(Item={"conversationId": CONV, "mode": "AGENT", "role": "CUSTOMER_CONTACT"})
    return table


def handoff(who: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    args = {"reason": "CUSTOMER_REQUEST", "summary": "Wants to talk about an invoice."} | kwargs
    return handoff_to_human(HandoffInput.model_validate({"caller": who or caller(), **args}))


def test_handoff_moves_the_conversation_to_human(
    conversations: Any, handoff_events: Events
) -> None:
    assert handoff() == {"status": "HANDED_OFF"}
    item = conversations.get_item(Key={"conversationId": CONV})["Item"]
    assert item["mode"] == "HUMAN"
    assert item["handoff"]["reason"] == "CUSTOMER_REQUEST"
    assert item["handoff"]["summary"] == "Wants to talk about an invoice."
    assert item["handoff"]["by"] == "AGENT"
    # IDs and reason only: the summary may hold personal data
    assert handoff_events == [
        ("handoff.started", {"conversationId": CONV, "reason": "CUSTOMER_REQUEST", "by": "AGENT"})
    ]


def test_second_handoff_keeps_the_first(conversations: Any, handoff_events: Events) -> None:
    handoff()
    assert handoff(reason="NEGATIVE_SENTIMENT") == {"status": "ALREADY_HANDED_OFF"}
    item = conversations.get_item(Key={"conversationId": CONV})["Item"]
    assert item["handoff"]["reason"] == "CUSTOMER_REQUEST"
    assert len(handoff_events) == 1


def test_unknown_caller_can_hand_off(conversations: Any, handoff_events: Events) -> None:
    who = caller("UNKNOWN", None)  # F-02.C4: identification failed
    assert handoff(who, reason="IDENTIFICATION_FAILED")["status"] == "HANDED_OFF"


def test_handoff_only_touches_the_callers_conversation(
    conversations: Any, handoff_events: Events
) -> None:
    conversations.put_item(Item={"conversationId": "conv_other", "mode": "AGENT"})
    handoff()
    other = conversations.get_item(Key={"conversationId": "conv_other"})["Item"]
    assert other["mode"] == "AGENT"
    with pytest.raises(NotFoundError):  # never creates a conversation
        handoff(caller(conv="conv_missing"))
    assert "Item" not in conversations.get_item(Key={"conversationId": "conv_missing"})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"reason": "OPERATOR_TAKEOVER"},  # console only
        {"reason": "BORED"},
        {"summary": ""},
        {"summary": "   "},
        {"conversationId": "conv_other"},  # the model cannot pick the conversation
    ],
)
def test_invalid_handoff_is_rejected(conversations: Any, kwargs: dict[str, Any]) -> None:
    with pytest.raises((InvalidInputError, ValueError)):
        handoff(**kwargs)


def test_handoff_needs_a_conversation(conversations: Any) -> None:
    with pytest.raises(InvalidInputError):
        handoff(caller(conv=""))


def test_release_gives_the_conversation_back(conversations: Any, handoff_events: Events) -> None:
    handoff()
    assert release_handoff("suppliagent.console-api", CONV, by="op_1") is True
    item = conversations.get_item(Key={"conversationId": CONV})["Item"]
    assert item["mode"] == "AGENT"
    assert "handoff" not in item
    assert "releasedAt" in item
    assert handoff_events[-1] == (
        "handoff.released",
        {"conversationId": CONV, "reason": "CUSTOMER_REQUEST", "by": "op_1"},
    )
    assert release_handoff("suppliagent.console-api", CONV, by="op_1") is False  # already AGENT
    assert handoff()["status"] == "HANDED_OFF"  # a new handoff after the release


def test_operator_takeover(conversations: Any, handoff_events: Events) -> None:
    reason = HandoffReason.OPERATOR_TAKEOVER
    assert start_handoff("suppliagent.console-api", CONV, reason, "", by="op_1") is True
    assert handoff_events[0][1]["by"] == "op_1"


def context(tool: str) -> Any:
    return SimpleNamespace(
        client_context=SimpleNamespace(custom={"bedrockAgentCoreToolName": f"orders___{tool}"})
    )


def test_handler_routes_handoff(conversations: Any, handoff_events: Events) -> None:
    event = {"caller": caller(), "reason": "OUT_OF_SCOPE", "summary": "Asks for a discount."}
    assert lambda_handler(event, context("handoff_to_human")) == {"status": "HANDED_OFF"}
    bad = {**event, "reason": "OPERATOR_TAKEOVER"}
    assert lambda_handler(bad, context("handoff_to_human")) == {"error": "INVALID_INPUT"}
