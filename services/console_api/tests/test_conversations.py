import json
from collections.abc import Iterator
from io import BytesIO
from typing import Any

import boto3
import pytest
from console_api import handler as h
from moto import mock_aws
from suppliagent_shared.aws import reset_clients

KEY_TYPES = ("HASH", "RANGE")
CONV = "conv_1"
KEY = "reply-key-0001"


class FakeLambda:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.result: dict[str, Any] = {"status": "SENT"}
        self.function_error: str | None = None

    def invoke(self, FunctionName: str, Payload: bytes) -> dict[str, Any]:  # noqa: N803
        self.calls.append({"name": FunctionName, "payload": json.loads(Payload)})
        response: dict[str, Any] = {"Payload": BytesIO(json.dumps(self.result).encode())}
        if self.function_error:
            response["FunctionError"] = self.function_error
        return response


@pytest.fixture(autouse=True)
def aws(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeLambda]:
    for name, value in {
        "AWS_DEFAULT_REGION": "eu-west-1",
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",
        "TABLE_PREFIX": "",
        "EVENT_BUS_NAME": "bus",
        "NOTIFIER_FUNCTION_NAME": "notifier-fn",
    }.items():
        monkeypatch.setenv(name, value)
    fake = FakeLambda()
    real_client = boto3.client
    monkeypatch.setattr(
        boto3, "client", lambda s, *a, **k: fake if s == "lambda" else real_client(s, *a, **k)
    )
    with mock_aws():
        reset_clients()
        ddb: Any = boto3.resource("dynamodb")

        def create(name: str, *keys: str) -> Any:
            return ddb.create_table(
                TableName=name,
                BillingMode="PAY_PER_REQUEST",
                KeySchema=[
                    {"AttributeName": k, "KeyType": t}
                    for k, t in zip(keys, KEY_TYPES, strict=False)
                ],
                AttributeDefinitions=[{"AttributeName": k, "AttributeType": "S"} for k in keys],
            )

        conversations = create("conversations", "conversationId")
        conversations.put_item(
            Item={"conversationId": CONV, "contactId": "con_1", "role": "CUSTOMER_CONTACT",
                  "mode": "AGENT", "lastMessageAt": "2026-10-28T08:00:00.000Z",
                  "lastInboundChannel": "WHATSAPP", "lastInboundFrom": "+393330000001"}
        )  # fmt: skip
        conversations.put_item(
            Item={"conversationId": "conv_2", "contactId": "con_2", "role": "CUSTOMER_CONTACT",
                  "mode": "HUMAN", "lastMessageAt": "2026-10-28T07:00:00.000Z",
                  "handoff": {"reason": "OUT_OF_SCOPE", "summary": "Wants a discount",
                              "by": "AGENT", "at": "2026-10-28T07:00:00.000Z"}}
        )  # fmt: skip
        conversations.put_item(
            Item={"conversationId": "conv_3", "contactId": "rep_1", "role": "SALES_REP",
                  "lastMessageAt": "2026-10-28T09:00:00.000Z"}
        )  # fmt: skip
        create("contacts", "contactId").put_item(
            Item={"contactId": "con_1", "name": "Anna", "customerId": "cus_1"}
        )
        create("customers", "customerId").put_item(
            Item={"customerId": "cus_1", "venueName": "Pizzeria Uno"}
        )
        messages = create("messages", "conversationId", "tsMessageId")
        for ts, item in (
            ("2026-10-28T07:59:00.000Z#m1", {"messageId": "m1", "direction": "INBOUND",
                "channel": "WHATSAPP", "receivedAt": "2026-10-28T07:59:00.000Z",
                "from": "+393330000001", "text": "Ciao",
                "attachments": [{"type": "image", "s3Uri": "s3://secret/a.jpg"}]}),
            ("2026-10-28T08:00:00.000Z#m2", {"messageId": "m2", "direction": "OUTBOUND",
                "channel": "WHATSAPP", "sentAt": "2026-10-28T08:00:00.000Z",
                "text": "Buongiorno", "status": "SENT"}),
        ):  # fmt: skip
            messages.put_item(Item={"conversationId": CONV, "tsMessageId": ts, **item})
        boto3.client("events").create_event_bus(Name="bus")
        yield fake
        reset_clients()


def call(
    resource: str,
    groups: str,
    *,
    method: str = "GET",
    conversation_id: str | None = None,
    body: object = None,
) -> tuple[int, dict[str, Any]]:
    event = {
        "httpMethod": method,
        "resource": resource,
        "pathParameters": {"conversationId": conversation_id} if conversation_id else None,
        "body": json.dumps(body) if body is not None else None,
        "queryStringParameters": None,
        "requestContext": {"authorizer": {"claims": {"cognito:groups": groups}}},
    }
    res = h.handler(event, None)
    return res["statusCode"], json.loads(res["body"])


def action(name: str, groups: str = "backoffice", conv: str = CONV, body: object = None) -> Any:
    return call(
        f"/conversations/{{conversationId}}/{name}",
        groups,
        method="POST",
        conversation_id=conv,
        body=body,
    )


def stored(conv: str = CONV) -> dict[str, Any]:
    item: dict[str, Any] = (
        boto3.resource("dynamodb")
        .Table("conversations")
        .get_item(Key={"conversationId": conv})["Item"]
    )
    return item


@pytest.mark.parametrize("groups", ["backoffice", "judge"])
def test_backoffice_and_judge_list_conversations_waiting_ones_first(groups: str) -> None:
    status, body = call("/conversations", groups)

    assert status == 200
    listed = body["conversations"]
    assert [x["conversationId"] for x in listed] == ["conv_2", "conv_3", CONV]
    assert listed[0]["handoff"]["reason"] == "OUT_OF_SCOPE"
    assert listed[2]["mode"] == "AGENT"
    assert (listed[2]["contactName"], listed[2]["customerName"]) == ("Anna", "Pizzeria Uno")
    assert listed[1]["mode"] == "AGENT"  # no `mode` stored yet: the agent answers
    assert "lastInboundFrom" not in json.dumps(body)


def test_a_sales_rep_cannot_read_conversations() -> None:
    assert call("/conversations", "sales_rep")[0] == 403
    assert call("/conversations/{conversationId}", "sales_rep", conversation_id=CONV)[0] == 403


def test_detail_has_the_history_in_order_without_addresses_or_media_uris() -> None:
    status, body = call("/conversations/{conversationId}", "judge", conversation_id=CONV)

    assert status == 200
    assert [m["messageId"] for m in body["messages"]] == ["m1", "m2"]
    assert body["messages"][0]["attachments"] == ["image"]
    assert body["messages"][1]["status"] == "SENT"
    dumped = json.dumps(body)
    assert "+39333" not in dumped and "s3://" not in dumped


def test_missing_conversation_is_404() -> None:
    assert call("/conversations/{conversationId}", "backoffice", conversation_id="nope")[0] == 404
    assert action("takeover", conv="nope")[0] == 404
    assert action("release", conv="nope")[0] == 404
    assert action("reply", conv="nope", body={"text": "x", "idempotencyKey": KEY})[0] == 404


def test_take_over_puts_the_conversation_in_human_mode() -> None:
    status, body = action("takeover")

    assert (status, body) == (200, {"mode": "HUMAN", "started": True})
    item = stored()
    assert item["mode"] == "HUMAN"
    assert item["handoff"]["reason"] == "OPERATOR_TAKEOVER"
    assert item["handoff"]["by"] == "BACKOFFICE"


def test_take_over_keeps_the_agents_handoff_reason() -> None:
    status, body = action("takeover", conv="conv_2")

    assert (status, body["started"]) == (200, False)
    assert stored("conv_2")["handoff"]["reason"] == "OUT_OF_SCOPE"


def test_release_gives_the_conversation_back_to_the_agent() -> None:
    status, body = action("release", conv="conv_2")

    assert (status, body) == (200, {"mode": "AGENT", "released": True})
    item = stored("conv_2")
    assert item["mode"] == "AGENT" and "handoff" not in item and "releasedAt" in item


def test_release_when_not_in_handoff_changes_nothing() -> None:
    assert action("release") == (200, {"mode": "AGENT", "released": False})


def test_reply_goes_through_the_notifier_with_a_namespaced_key(aws: FakeLambda) -> None:
    action("takeover")

    status, body = action("reply", body={"text": "  Ci penso io  ", "idempotencyKey": KEY})

    assert (status, body) == (200, {"status": "SENT"})
    [call_] = aws.calls
    assert call_["name"] == "notifier-fn"
    assert call_["payload"] == {
        "kind": "reply",
        "conversationId": CONV,
        "idempotencyKey": f"console#{CONV}#{KEY}",
        "text": "Ci penso io",
        "sentBy": "OPERATOR",
    }


def test_reply_is_refused_while_the_agent_is_in_charge(aws: FakeLambda) -> None:
    assert action("reply", body={"text": "Ciao", "idempotencyKey": KEY}) == (
        409,
        {"error": "not_in_handoff"},
    )
    assert aws.calls == []


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"text": "x"},
        {"idempotencyKey": KEY},
        {"text": "   ", "idempotencyKey": KEY},
        {"text": "x" * 1001, "idempotencyKey": KEY},
        {"text": 5, "idempotencyKey": KEY},
        {"text": "x", "idempotencyKey": "short"},
        {"text": "x", "idempotencyKey": "a b c d e f g h"},
    ],
)
def test_reply_rejects_a_bad_body(payload: object, aws: FakeLambda) -> None:
    status, body = action("reply", conv="conv_2", body=payload)

    assert (status, body) == (400, {"error": "invalid_body"})
    assert aws.calls == []


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ("AccessDeniedError", (409, "no_reply_address")),
        ("ChannelUnavailableError", (409, "channel_unavailable")),
        ("SendInProgressError", (503, "send_in_progress")),
        ("Boom", (502, "send_failed")),
    ],
)
def test_reply_maps_notifier_failures(
    error: str, expected: tuple[int, str], aws: FakeLambda
) -> None:
    aws.function_error, aws.result = "Unhandled", {"errorType": error, "errorMessage": "secret"}

    status, body = action("reply", conv="conv_2", body={"text": "Ciao", "idempotencyKey": KEY})

    assert (status, body["error"]) == expected
    assert "secret" not in json.dumps(body)


def test_judge_cannot_write_whatever_the_action(aws: FakeLambda) -> None:
    for name in ("takeover", "release", "reply"):
        status, body = action(
            name, "judge", conv="conv_2", body={"text": "x", "idempotencyKey": KEY}
        )
        assert (status, body["error"]) == (403, "read_only")
    assert stored("conv_2")["mode"] == "HUMAN"
    assert aws.calls == []


def test_sales_rep_and_judge_with_sales_rep_cannot_write(aws: FakeLambda) -> None:
    for groups in ("sales_rep", "[judge sales_rep]"):
        for name in ("takeover", "release", "reply"):
            assert action(name, groups, conv="conv_2")[0] == 403
    assert stored("conv_2")["mode"] == "HUMAN" and aws.calls == []


def test_other_methods_are_not_allowed() -> None:
    assert call("/conversations", "backoffice", method="POST")[0] == 405
    assert call("/conversations/{conversationId}", "backoffice", method="PATCH",
                conversation_id=CONV)[0] == 405  # fmt: skip
