"""Inbound Router, T-22 (FN-26, FN-24): TurnBuffer, flush scheduling, handoff, read receipt."""

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import boto3
import pytest
from inbound_router import handler as router

Builder = Callable[..., Any]
ANNA = "393330000001"  # con_001 -> conv_con001


def sqs_event(message: dict[str, Any]) -> dict[str, Any]:
    envelope = {"Type": "Notification", "TopicArn": "arn:aws:sns:x", "Message": json.dumps(message)}
    return {"Records": [{"messageId": "sqs-1", "body": json.dumps(envelope)}]}


@pytest.fixture
def wa(wa_event: Builder) -> Builder:
    def build(
        kind: str = "text",
        provider_id: str = "wamid.1",
        sender: str = ANNA,
        at: str = "2026-10-26T10:00:00.123456789Z",
    ) -> dict[str, Any]:
        message: dict[str, Any] = {"from": sender, "id": provider_id, "type": kind}
        message[kind] = (
            {"body": "ciao"} if kind == "text" else {"id": "530", "mime_type": "image/jpeg"}
        )
        return dict(wa_event([message], at))

    return build


def buffer(conversation_id: str = "conv_con001") -> dict[str, Any]:
    table: Any = boto3.resource("dynamodb").Table("suppliagent-test-turn-buffer")
    item: dict[str, Any] = table.get_item(Key={"conversationId": conversation_id}).get("Item", {})
    return item


def conversation(conversation_id: str = "conv_con001") -> dict[str, Any]:
    table: Any = boto3.resource("dynamodb").Table("suppliagent-test-conversations")
    item: dict[str, Any] = table.get_item(Key={"conversationId": conversation_id})["Item"]
    return item


def test_text_message_is_buffered_and_flushed_after_the_text_debounce(
    wa: Builder, recorder: Any
) -> None:
    router.handler(sqs_event(wa()), None)

    item = buffer()
    [entry] = item["pending"]
    assert (entry["text"], entry["ts"]) == ("ciao", "2026-10-26T10:00:00.123Z")
    assert item["caller"] == {
        "channel": "WHATSAPP",
        "from": f"+{ANNA}",
        "role": "CUSTOMER_CONTACT",
        "contactId": "con_001",
        "customerIds": ["cus_001", "cus_005"],
        "locale": "it-IT",
    }
    assert isinstance(entry["at"], Decimal)  # arrival time, what the debounce counts from
    assert isinstance(item["expiresAt"], Decimal)
    [flush] = recorder.sent
    assert json.loads(flush["MessageBody"]) == {"conversationId": "conv_con001"}
    assert flush["DelaySeconds"] == 3


def test_media_message_waits_for_the_media_debounce(wa: Builder, recorder: Any) -> None:
    router.handler(sqs_event(wa("image")), None)

    assert recorder.sent[0]["DelaySeconds"] == 6
    [entry] = buffer()["pending"]
    assert entry["attachments"][0]["type"] == "image"


def test_burst_accumulates_in_order_and_keeps_the_first_timestamp(
    wa: Builder, recorder: Any
) -> None:
    router.handler(sqs_event(wa("image", "wamid.1")), None)
    router.handler(sqs_event(wa("text", "wamid.2", at="2026-10-26T10:00:04Z")), None)

    item = buffer()
    assert [m["ts"] for m in item["pending"]] == [
        "2026-10-26T10:00:00.123Z",
        "2026-10-26T10:00:04.000Z",
    ]
    assert len(recorder.sent) == 2


def test_redelivery_is_not_appended_twice_but_still_flushes(wa: Builder, recorder: Any) -> None:
    for _ in range(2):
        router.handler(sqs_event(wa()), None)

    assert len(buffer()["pending"]) == 1
    assert len(recorder.sent) == 2  # the first send may have been lost: a flush is harmless


def test_human_mode_stores_the_message_but_starts_no_turn(wa: Builder, recorder: Any) -> None:
    router.handler(sqs_event(wa("text", "wamid.1")), None)
    table: Any = boto3.resource("dynamodb").Table("suppliagent-test-conversations")
    table.update_item(
        Key={"conversationId": "conv_con001"},
        UpdateExpression="SET #m = :h",
        ExpressionAttributeNames={"#m": "mode"},
        ExpressionAttributeValues={":h": "HUMAN"},
    )
    recorder.sent.clear()

    router.handler(sqs_event(wa("text", "wamid.2")), None)

    assert len(buffer()["pending"]) == 1  # only the one from before the handoff
    assert recorder.sent == []
    messages: Any = boto3.resource("dynamodb").Table("suppliagent-test-messages")
    assert messages.scan()["Count"] == 2
    assert conversation()["mode"] == "HUMAN"  # the router never changes the mode


def test_unverified_email_gets_no_turn(mail_notification: Builder, recorder: Any) -> None:
    router.handler(sqs_event(mail_notification(dmarc="FAIL")), None)

    assert recorder.sent == []  # no reply to a sender nobody vouches for (backscatter)
    table: Any = boto3.resource("dynamodb").Table("suppliagent-test-conversations")
    [item] = table.scan()["Items"]
    assert "lastInboundFrom" not in item  # the Notifier would have no address to write to


@pytest.fixture
def mail_notification(ses_notification: Builder, raw_mail: Builder) -> Builder:
    def build(**notification: Any) -> dict[str, Any]:
        event: dict[str, Any] = ses_notification(**notification)
        action = event["receipt"]["action"]
        boto3.client("s3").put_object(
            Bucket=action["bucketName"],
            Key=action["objectKey"],
            Body=raw_mail("ordine", "ordini.fornoantico@example.com"),
        )
        return event

    return build


def test_verified_sender_address_and_whatsapp_window_are_recorded(wa: Builder) -> None:
    router.handler(sqs_event(wa()), None)

    item = conversation()
    assert (item["lastInboundChannel"], item["lastInboundFrom"]) == ("WHATSAPP", f"+{ANNA}")
    assert item["lastWhatsappInboundAt"] == "2026-10-26T10:00:00.123Z"
    assert item["lastInboundLocale"] == "it-IT"


def test_email_sender_does_not_open_the_whatsapp_window(
    mail_notification: Builder, recorder: Any
) -> None:
    router.handler(sqs_event(mail_notification()), None)

    item = conversation()
    assert item["lastInboundChannel"] == "EMAIL"
    assert "lastWhatsappInboundAt" not in item
    assert len(recorder.sent) == 1  # a verified email is answered


def test_new_whatsapp_message_requests_a_read_receipt(wa: Builder, recorder: Any) -> None:
    router.handler(sqs_event(wa(provider_id="wamid.9")), None)

    [call] = recorder.invoked
    assert call["FunctionName"] == "suppliagent-test-notifier"
    assert call["InvocationType"] == "Event"
    assert json.loads(call["Payload"]) == {
        "kind": "read_receipt",
        "conversationId": "conv_con001",
        "providerMessageId": "wamid.9",
        "tsMessageId": json.loads(call["Payload"])["tsMessageId"],
    }
    assert json.loads(call["Payload"])["tsMessageId"].startswith("2026-10-26T10:00:00.123Z#msg_")


def test_duplicate_gets_no_second_read_receipt(wa: Builder, recorder: Any) -> None:
    for _ in range(2):
        router.handler(sqs_event(wa()), None)

    assert len(recorder.invoked) == 1


def test_read_receipt_failure_does_not_fail_the_message(wa: Builder, recorder: Any) -> None:
    recorder.invoke_fails = True

    router.handler(sqs_event(wa()), None)  # no exception: SQS would redeliver a stored message

    assert len(buffer()["pending"]) == 1


def test_an_older_message_does_not_move_the_reply_address_or_the_window_back(
    wa: Builder, mail_notification: Builder
) -> None:
    router.handler(sqs_event(wa(at="2026-10-26T10:00:00.000Z")), None)  # newest: WhatsApp
    # A redriven old message (or an out-of-order redelivery) of the same contact, on WhatsApp.
    router.handler(sqs_event(wa(provider_id="wamid.old", at="2026-10-26T08:00:00.000Z")), None)

    item = conversation()
    assert item["lastWhatsappInboundAt"] == "2026-10-26T10:00:00.000Z"
    assert item["lastInboundAt"] == "2026-10-26T10:00:00.000Z"
