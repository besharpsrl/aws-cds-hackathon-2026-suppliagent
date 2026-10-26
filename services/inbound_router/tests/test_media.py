"""Media to S3 (T-23): WhatsApp media via EUM Social, email attachments (FN-05, FN-06, 02 §3.4)."""

import json
from collections.abc import Callable
from typing import Any

import boto3
import pytest
from boto3.dynamodb.conditions import Key
from inbound_router import handler as router

Builder = Callable[..., Any]
MEDIA = "suppliagent-test-media"
PDF = "application/pdf"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def sqs_event(message: dict[str, Any]) -> dict[str, Any]:
    envelope = {"Type": "Notification", "Message": json.dumps(message)}
    return {"Records": [{"messageId": "sqs-1", "body": json.dumps(envelope)}]}


def stored(conversation_id: str) -> list[dict[str, Any]]:
    table: Any = boto3.resource("dynamodb").Table("suppliagent-test-messages")
    items: list[dict[str, Any]] = table.query(
        KeyConditionExpression=Key("conversationId").eq(conversation_id)
    )["Items"]
    return items


def media_keys() -> list[str]:
    found = boto3.client("s3").list_objects_v2(Bucket=MEDIA).get("Contents", [])
    return sorted(o["Key"] for o in found)


@pytest.fixture(autouse=True)
def no_events(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(router, "put_event", lambda *_: None)


@pytest.fixture
def wa_media(wa_event: Builder) -> Builder:
    def build(kind: str, mime: str, sender: str = "393330000001") -> dict[str, Any]:
        message = {
            "from": sender,
            "id": "wamid.m1",
            "type": kind,
            kind: {"id": "530", "mime_type": mime},
        }
        return dict(wa_event([message]))

    return build


@pytest.fixture
def mail(ses_notification: Builder, raw_mail: Builder) -> Builder:
    def build(*files: tuple[str, str, bytes], **notification: Any) -> dict[str, Any]:
        event: dict[str, Any] = ses_notification(**notification)
        action = event["receipt"]["action"]
        raw = raw_mail("ordine in allegato", attachments=files)
        boto3.client("s3").put_object(
            Bucket=action["bucketName"], Key=action["objectKey"], Body=raw
        )
        return event

    return build


def test_whatsapp_photo_is_saved_to_the_contacts_media_prefix(
    wa_media: Builder, social: Any
) -> None:
    router.handler(sqs_event(wa_media("image", "image/jpeg")), None)

    [call] = social.calls
    assert call["mediaId"] == "530"
    assert call["originationPhoneNumberId"] == "phone-number-id-0123456789abcdef"  # from SSM
    [item] = stored("conv_con001")
    [attachment] = item["attachments"]
    key = f"media/con_001/{item['messageId']}/530.jpeg"
    assert attachment == {
        "type": "image",
        "mimeType": "image/jpeg",
        "mediaId": "530",
        "s3Uri": f"s3://{MEDIA}/{key}",
    }
    assert media_keys() == [key]


def test_whatsapp_voice_note_is_saved(wa_media: Builder, social: Any) -> None:
    router.handler(sqs_event(wa_media("audio", "audio/ogg; codecs=opus")), None)

    assert len(social.calls) == 1
    assert stored("conv_con001")[0]["attachments"][0]["s3Uri"].startswith(f"s3://{MEDIA}/media/")


@pytest.mark.parametrize(
    ("kind", "mime"),
    [
        ("sticker", "image/webp"),  # not processed (02 §3.4)
        ("video", "video/mp4"),
        ("document", "application/x-msdownload"),  # not allowed (E-13)
        ("image", "image/svg+xml"),
    ],
)
def test_unprocessed_or_unsafe_whatsapp_media_is_not_downloaded(
    wa_media: Builder, social: Any, kind: str, mime: str
) -> None:
    router.handler(sqs_event(wa_media(kind, mime)), None)

    assert social.calls == []
    [attachment] = stored("conv_con001")[0]["attachments"]
    assert "s3Uri" not in attachment


def test_media_is_kept_unfetched_while_the_phone_number_is_not_configured(
    wa_media: Builder, social: Any
) -> None:
    boto3.client("ssm").put_parameter(
        Name="/suppliagent/test/waPhoneNumberId", Value="UNSET", Type="String", Overwrite=True
    )

    router.handler(sqs_event(wa_media("image", "image/jpeg")), None)

    assert social.calls == []
    assert "s3Uri" not in stored("conv_con001")[0]["attachments"][0]


def test_failed_download_stores_nothing_so_sqs_retries(wa_media: Builder, social: Any) -> None:
    social.fail = True  # E-02

    with pytest.raises(RuntimeError):
        router.handler(sqs_event(wa_media("image", "image/jpeg")), None)

    assert stored("conv_con001") == []
    conversations: Any = boto3.resource("dynamodb").Table("suppliagent-test-conversations")
    assert conversations.scan()["Items"] == []


def test_unknown_sender_media_goes_under_its_conversation(wa_media: Builder) -> None:
    router.handler(sqs_event(wa_media("image", "image/jpeg", sender="393339999999")), None)

    [key] = media_keys()
    assert key.startswith("media/conv_u")


def test_email_attachments_are_uploaded_and_unsafe_ones_dropped(mail: Builder) -> None:
    notification = mail(
        ("bigliettino.JPG", "image/jpeg", b"jpg"),
        ("ordine.pdf", PDF, b"%PDF"),
        ("ordine.xlsx", XLSX, b"xlsx"),
        ("setup.exe", "application/x-msdownload", b"MZ"),
        ("big.pdf", PDF, b"0" * (10 * 1024 * 1024 + 1)),
    )

    router.handler(sqs_event(notification), None)

    [item] = stored("conv_con001")
    prefix = f"media/con_001/{item['messageId']}/"
    assert [(a["type"], a["s3Uri"]) for a in item["attachments"]] == [
        ("image", f"s3://{MEDIA}/{prefix}0.jpg"),
        ("document", f"s3://{MEDIA}/{prefix}1.pdf"),
        ("document", f"s3://{MEDIA}/{prefix}2.xlsx"),
    ]
    assert media_keys() == [f"{prefix}0.jpg", f"{prefix}1.pdf", f"{prefix}2.xlsx"]


def test_attachment_filename_never_escapes_the_message_prefix(mail: Builder) -> None:
    router.handler(sqs_event(mail(("../../con_002/x/evil.pdf", PDF, b"%PDF"))), None)

    [key] = media_keys()
    item = stored("conv_con001")[0]
    assert key == f"media/con_001/{item['messageId']}/0.pdf"


def test_attachments_of_an_infected_mail_are_dropped(mail: Builder) -> None:
    router.handler(sqs_event(mail(("ordine.pdf", PDF, b"%PDF"), virus="FAIL")), None)  # E-13

    assert stored("conv_con001")[0]["attachments"] == []
    assert media_keys() == []
