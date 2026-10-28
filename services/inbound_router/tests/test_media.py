"""Media to S3 (T-23): WhatsApp media via EUM Social, email attachments (FN-05, FN-06, 02 §3.4)."""

import json
from collections.abc import Callable
from typing import Any

import boto3
import pytest
from boto3.dynamodb.conditions import Key
from inbound_router import handler as router
from inbound_router import media
from suppliagent_shared.errors import SuppliAgentError

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


JPEG, PDF_BYTES, XLSX_BYTES = b"\xff\xd8\xff\xe0jpg", b"%PDF-1.7", b"PK\x03\x04xlsx"


def test_email_attachments_are_uploaded_and_unsafe_ones_kept_without_file(mail: Builder) -> None:
    notification = mail(
        ("bigliettino.JPG", "image/jpeg", JPEG),
        ("ordine.pdf", PDF, PDF_BYTES),
        ("ordine.xlsx", XLSX, XLSX_BYTES),
        ("setup.exe", "application/x-msdownload", b"MZ"),
        ("big.pdf", PDF, PDF_BYTES + b"0" * (10 * 1024 * 1024)),
        ("fake.pdf", PDF, b"MZ\x90\x00"),  # an executable declared as PDF
        ("old.xls", "application/vnd.ms-excel", b"\xd0\xcf\x11\xe0"),  # legacy, macros
    )

    router.handler(sqs_event(notification), None)

    [item] = stored("conv_con001")
    prefix = f"media/con_001/{item['messageId']}/"
    assert [(a["type"], a.get("s3Uri")) for a in item["attachments"]] == [
        ("image", f"s3://{MEDIA}/{prefix}0.jpg"),
        ("document", f"s3://{MEDIA}/{prefix}1.pdf"),
        ("document", f"s3://{MEDIA}/{prefix}2.xlsx"),
        ("document", None),  # rejected but visible to the agent (E-13)
        ("document", None),
        ("document", None),
        ("document", None),
    ]
    assert media_keys() == [f"{prefix}0.jpg", f"{prefix}1.pdf", f"{prefix}2.xlsx"]
    head = boto3.client("s3").head_object(Bucket=MEDIA, Key=f"{prefix}1.pdf")
    assert head["ContentDisposition"] == "attachment"  # never rendered by the browser


def test_attachment_key_comes_from_the_type_not_the_file_name(mail: Builder) -> None:
    router.handler(sqs_event(mail(("../../con_002/x/evil.html", PDF, PDF_BYTES))), None)

    [key] = media_keys()
    item = stored("conv_con001")[0]
    assert key == f"media/con_001/{item['messageId']}/0.pdf"


@pytest.mark.parametrize("virus", ["FAIL", "GRAY", "PROCESSING_FAILED"])
def test_attachments_without_a_clean_virus_scan_are_not_stored(mail: Builder, virus: str) -> None:
    router.handler(sqs_event(mail(("ordine.pdf", PDF, PDF_BYTES), virus=virus)), None)  # E-13

    [attachment] = stored("conv_con001")[0]["attachments"]
    assert "s3Uri" not in attachment
    assert media_keys() == []


def test_at_most_ten_attachments_per_mail_are_stored(mail: Builder) -> None:
    router.handler(sqs_event(mail(*[(f"{i}.pdf", PDF, PDF_BYTES) for i in range(12)])), None)

    assert len(stored("conv_con001")[0]["attachments"]) == 12
    assert len(media_keys()) == 10


def test_oversized_whatsapp_media_is_not_handed_to_the_agent(
    wa_media: Builder, social: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(media, "MAX_FILE_BYTES", 1000)
    social.file_size = 1001

    router.handler(sqs_event(wa_media("image", "image/jpeg")), None)

    assert "s3Uri" not in stored("conv_con001")[0]["attachments"][0]


def test_a_typical_whatsapp_photo_is_handed_to_the_agent(wa_media: Builder, social: Any) -> None:
    social.file_size = 157_299  # real photo of 27/10, dropped when `fileSize` was read as KB

    router.handler(sqs_event(wa_media("image", "image/jpeg")), None)

    assert stored("conv_con001")[0]["attachments"][0]["s3Uri"].endswith(".jpeg")


SIM_ID = "sim_" + "ab" * 16


def simulated_photo(wa_event: Builder, media_id: str = SIM_ID) -> dict[str, Any]:
    message = {
        "from": "393330000001",
        "id": "wamid.sim1",
        "type": "image",
        "image": {"id": media_id, "mime_type": "image/jpeg"},
    }
    return dict(wa_event([message]))


def set_sandbox(value: str) -> None:
    boto3.client("ssm").put_parameter(
        Name="/suppliagent/test/notifierSandbox", Value=value, Type="String", Overwrite=True
    )


def upload_simulated(media_id: str = SIM_ID, key_name: str = "file.jpg") -> None:
    boto3.client("s3").put_object(
        Bucket=MEDIA,
        Key=f"sim/{media_id}/{key_name}",
        Body=b"\xff\xd8\xff",
        ContentType="image/jpeg",
    )


def test_simulated_media_is_copied_under_the_contacts_prefix_in_sandbox(
    wa_event: Builder, social: Any
) -> None:
    set_sandbox("true")
    upload_simulated()

    router.handler(sqs_event(simulated_photo(wa_event)), None)

    assert social.calls == []  # EUM Social is not involved
    [item] = stored("conv_con001")
    key = f"media/con_001/{item['messageId']}/{SIM_ID}.jpg"
    assert item["attachments"][0]["s3Uri"] == f"s3://{MEDIA}/{key}"
    assert key in media_keys()


@pytest.mark.parametrize("sandbox", [None, "false"])
def test_simulated_media_is_ignored_outside_the_sandbox(
    wa_event: Builder, social: Any, sandbox: str | None
) -> None:
    if sandbox:
        set_sandbox(sandbox)
    upload_simulated()

    router.handler(sqs_event(simulated_photo(wa_event)), None)

    assert len(social.calls) == 1  # a real download (the fake): nothing copied from `sim/`
    assert not any(k.startswith("media/") and k.endswith(".jpg") for k in media_keys())


def test_media_id_outside_the_simulator_format_is_not_a_bucket_path(
    wa_event: Builder, social: Any
) -> None:
    set_sandbox("true")
    boto3.client("s3").put_object(Bucket=MEDIA, Key="sim/../secret/file.jpg", Body=b"x")

    router.handler(sqs_event(simulated_photo(wa_event, media_id="sim_../secret")), None)

    # Not the simulator's shape: handled as a real media id (phone number set, EUM Social fake).
    assert len(social.calls) == 1
    assert not any(k.startswith("media/") and k.endswith(".jpg") for k in media_keys())


def test_simulated_media_missing_from_the_bucket_fails_so_sqs_retries(
    wa_event: Builder, social: Any
) -> None:
    set_sandbox("true")

    with pytest.raises(SuppliAgentError):
        router.handler(sqs_event(simulated_photo(wa_event)), None)


def test_on_the_last_attempt_a_failed_download_reaches_the_agent_without_file(
    wa_media: Builder, social: Any
) -> None:
    social.fail = True  # E-02 after the retries: the agent asks to send it again (T-24)
    event = sqs_event(wa_media("image", "image/jpeg"))
    event["Records"][0]["attributes"] = {"ApproximateReceiveCount": "3"}
    router.handler(event, None)
    [item] = stored("conv_con001")
    [attachment] = item["attachments"]
    assert attachment["type"] == "image" and "s3Uri" not in attachment
