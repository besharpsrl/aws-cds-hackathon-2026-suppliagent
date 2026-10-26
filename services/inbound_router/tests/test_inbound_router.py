"""Inbound Router (T-21): FN-01 and FN-03 acceptance criteria, F-02 identity cases, idempotency."""

import json
from collections.abc import Callable
from typing import Any

import boto3
import pytest
from boto3.dynamodb.conditions import Key
from inbound_router import handler as router
from suppliagent_shared.errors import InvalidInputError
from suppliagent_shared.messages import NormalizedMessage

Builder = Callable[..., Any]


def sqs_event(message: dict[str, Any]) -> dict[str, Any]:
    """One SQS record holding the SNS envelope, as delivered by the `inbound` queue."""
    envelope = {"Type": "Notification", "TopicArn": "arn:aws:sns:x", "Message": json.dumps(message)}
    return {"Records": [{"messageId": "sqs-1", "body": json.dumps(envelope)}]}


@pytest.fixture
def wa_text(wa_event: Builder) -> Builder:
    def build(
        sender: str,
        text: str = "ciao",
        provider_id: str = "wamid.1",
        at: str = "2026-10-26T10:00:00.123456789Z",
    ) -> dict[str, Any]:
        message = {"from": sender, "id": provider_id, "type": "text", "text": {"body": text}}
        return dict(wa_event([message], at))

    return build


@pytest.fixture
def mail(ses_notification: Builder, raw_mail: Builder) -> Builder:
    """Stores a raw mail in the inbound bucket and returns the SES notification for it."""

    def build(raw: bytes, **notification: Any) -> dict[str, Any]:
        event: dict[str, Any] = ses_notification(**notification)
        action = event["receipt"]["action"]
        boto3.client("s3").put_object(
            Bucket=action["bucketName"], Key=action["objectKey"], Body=raw
        )
        return event

    return build


def stored(conversation_id: str) -> list[dict[str, Any]]:
    table: Any = boto3.resource("dynamodb").Table("suppliagent-test-messages")
    items: list[dict[str, Any]] = table.query(
        KeyConditionExpression=Key("conversationId").eq(conversation_id)
    )["Items"]
    return items


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    sent: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        router, "put_event", lambda _s, detail_type, d: sent.append((detail_type, d))
    )
    return sent


def test_known_contact_message_is_stored_with_identity(events: list[Any], wa_text: Builder) -> None:
    router.handler(sqs_event(wa_text("393330000001", "ciao")), None)

    [item] = stored("conv_con001")
    message = NormalizedMessage.model_validate(
        {k: v for k, v in item.items() if k != "tsMessageId"}
    )
    assert (message.role, message.contactId, message.locale) == (
        "CUSTOMER_CONTACT",
        "con_001",
        "it-IT",
    )
    assert message.customerIds == ["cus_001", "cus_005"]  # F-02.C5: more than one venue
    assert (message.from_, message.text) == ("+393330000001", "ciao")
    assert item["tsMessageId"].startswith("2026-10-26T10:00:00.123Z#msg_")
    assert events == [
        (
            "conversation.started",
            {"contactId": "con_001", "role": "CUSTOMER_CONTACT", "channel": "WHATSAPP"},
        )
    ]


def test_contact_only_gets_its_own_venues(events: list[Any], wa_text: Builder) -> None:
    router.handler(sqs_event(wa_text("393330000002")), None)  # negative: never another's venues

    [item] = stored("conv_con002")
    assert item["customerIds"] == ["cus_002"]


def test_english_contact_gets_english_locale(events: list[Any], wa_text: Builder) -> None:
    router.handler(sqs_event(wa_text("447700900004")), None)

    assert stored("conv_con004")[0]["locale"] == "en-GB"


def test_sales_rep_gets_portfolio_and_role(events: list[Any], wa_text: Builder) -> None:
    router.handler(sqs_event(wa_text("393330000101")), None)

    [item] = stored("conv_rep001")
    assert (item["role"], item["contactId"]) == ("SALES_REP", "rep_001")
    assert sorted(item["customerIds"]) == ["cus_001", "cus_002", "cus_003"]


def test_unknown_sender_is_stored_as_unknown_without_access(
    events: list[Any], wa_text: Builder
) -> None:
    router.handler(sqs_event(wa_text("393339999999")), None)  # F-02.C4

    conversations: Any = boto3.resource("dynamodb").Table("suppliagent-test-conversations")
    [conversation] = conversations.scan()["Items"]
    assert conversation["conversationId"].startswith("conv_u")
    assert "contactId" not in conversation  # a GSI key cannot be empty
    [item] = stored(conversation["conversationId"])
    assert (item["role"], item["customerIds"]) == ("UNKNOWN", [])
    assert "contactId" not in item


def test_same_message_delivered_twice_is_stored_once(events: list[Any], wa_text: Builder) -> None:
    for _ in range(2):  # SQS standard queues deliver at least once
        router.handler(sqs_event(wa_text("393330000001")), None)

    assert len(stored("conv_con001")) == 1
    assert len(events) == 1


def test_burst_keeps_one_conversation_and_one_event(events: list[Any], wa_text: Builder) -> None:
    router.handler(sqs_event(wa_text("393330000001", "foto", "wamid.1")), None)
    router.handler(
        sqs_event(wa_text("393330000001", "aggiungi burro", "wamid.2", "2026-10-26T10:00:04Z")),
        None,
    )

    assert [m["text"] for m in stored("conv_con001")] == ["foto", "aggiungi burro"]
    assert len(events) == 1


def test_existing_conversation_state_is_preserved(events: list[Any], wa_text: Builder) -> None:
    conversations: Any = boto3.resource("dynamodb").Table("suppliagent-test-conversations")
    conversations.put_item(
        Item={"conversationId": "conv_con001", "mode": "HUMAN", "identifyAttempts": 2}
    )

    router.handler(sqs_event(wa_text("393330000001")), None)

    item = conversations.get_item(Key={"conversationId": "conv_con001"})["Item"]
    assert (item["mode"], item["identifyAttempts"]) == ("HUMAN", 2)  # handoff is never reset
    assert events == []  # not a new conversation


def test_email_order_is_read_from_s3(events: list[Any], mail: Builder, raw_mail: Builder) -> None:
    notification = mail(
        raw_mail("10 kg farina", "Ordini.FornoAntico@example.com"),
        destination="ordine+ord_789@ordini.example.com",
    )

    router.handler(sqs_event(notification), None)

    # Known address -> same contact and conversation as WhatsApp (F-15).
    [item] = stored("conv_con001")
    assert (item["channel"], item["orderId"], item["text"]) == (
        "EMAIL",
        "ord_789",
        "Ordine\n10 kg farina",
    )


def test_spoofed_email_from_a_known_contact_gets_no_identity(
    events: list[Any], mail: Builder, raw_mail: Builder
) -> None:
    # Negative authorization: a forged `From` must not inherit the contact's scope (§5.3.2).
    notification = mail(raw_mail("10 kg farina", "ordini.fornoantico@example.com"), dmarc="FAIL")

    router.handler(sqs_event(notification), None)

    assert stored("conv_con001") == []
    conversations: Any = boto3.resource("dynamodb").Table("suppliagent-test-conversations")
    [conversation] = conversations.scan()["Items"]
    [item] = stored(conversation["conversationId"])
    assert (item["role"], item["customerIds"]) == ("UNKNOWN", [])
    assert "contactId" not in item


def test_email_from_a_foreign_bucket_is_rejected(
    events: list[Any], ses_notification: Builder
) -> None:
    notification = ses_notification()
    notification["receipt"]["action"]["bucketName"] = "someone-elses-bucket"

    with pytest.raises(InvalidInputError):
        router.handler(sqs_event(notification), None)


def test_unknown_event_shape_goes_to_the_dlq(events: list[Any]) -> None:
    with pytest.raises(InvalidInputError):
        router.handler(sqs_event({"hello": "world"}), None)


def test_email_object_must_be_the_notified_message(
    events: list[Any], ses_notification: Builder
) -> None:
    notification = ses_notification()
    notification["receipt"]["action"]["objectKey"] = "mail/another-message"

    with pytest.raises(InvalidInputError):
        router.handler(sqs_event(notification), None)


def test_redelivery_with_a_new_timestamp_is_still_a_duplicate(
    events: list[Any], wa_text: Builder
) -> None:
    router.handler(sqs_event(wa_text("393330000001", at="2026-10-26T10:00:00Z")), None)
    router.handler(sqs_event(wa_text("393330000001", at="2026-10-26T10:05:00Z")), None)  # E-01

    assert len(stored("conv_con001")) == 1


def test_contact_pending_verification_gets_no_venues(events: list[Any], wa_text: Builder) -> None:
    # Negative authorization: same rule as caller_scope (fail-closed until verified).
    dynamodb: Any = boto3.resource("dynamodb")
    dynamodb.Table("suppliagent-test-contacts").put_item(
        Item={"contactId": "con_new", "customerId": "cus_002", "customerIds": ["cus_002"],
              "language": "it", "status": "PENDING_VERIFICATION"}
    )  # fmt: skip
    dynamodb.Table("suppliagent-test-channel-identities").put_item(
        Item={"channelAddress": "WHATSAPP#+393338888888", "channel": "WHATSAPP",
              "contactId": "con_new", "role": "CUSTOMER_CONTACT", "verified": False,
              "conversationId": "conv_uabc"}
    )  # fmt: skip

    router.handler(sqs_event(wa_text("393338888888")), None)

    # Stays in the conversation it was identified in (session, handoff and buffer survive).
    [item] = stored("conv_uabc")
    assert (item["role"], item["contactId"], item["customerIds"]) == (
        "CUSTOMER_CONTACT",
        "con_new",
        [],
    )


def test_unverified_email_never_lands_in_the_address_owners_conversation(
    events: list[Any], mail: Builder, raw_mail: Builder
) -> None:
    router.handler(sqs_event(mail(raw_mail("a", "nuovo@example.org"))), None)
    router.handler(
        sqs_event(mail(raw_mail("b", "nuovo@example.org"), dmarc="GRAY")), None
    )  # same address, forged or not, kept apart

    conversations: Any = boto3.resource("dynamodb").Table("suppliagent-test-conversations")
    assert len(conversations.scan()["Items"]) == 2


def test_whatsapp_delivery_status_is_ignored(events: list[Any], wa_event: Builder) -> None:
    router.handler(sqs_event(wa_event(None, statuses=[{"id": "wamid.1", "status": "read"}])), None)

    assert events == []
