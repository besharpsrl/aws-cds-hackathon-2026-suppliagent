"""Moto tables loaded with the committed seed data (seed/data), the inbound-mail and media buckets,
the WhatsApp phone number parameter and a fake EUM Social client."""

import json
from collections.abc import Callable, Iterator
from decimal import Decimal
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import boto3
import pytest
from inbound_router import handler, media
from moto import mock_aws
from suppliagent_shared.aws import reset_clients

SEED = Path(__file__).parents[3] / "seed" / "data"
# table short name -> (key attributes, GSI partition keys); mirrors infra/lib/stacks/data-stack.ts
TABLES = {
    "customers": (("customerId",), ("repId",)),
    "contacts": (("contactId",), ("customerId",)),
    "channel-identities": (("channelAddress",), ("contactId",)),
    "sales-reps": (("repId",), ()),
    "conversations": (("conversationId",), ("contactId",)),
    "messages": (("conversationId", "tsMessageId"), ("providerMessageId",)),
    "turn-buffer": (("conversationId",), ()),
}
BUCKET = "suppliagent-test-inbound-mail"
MEDIA_BUCKET = "suppliagent-test-media"
PHONE_PARAM = "/suppliagent/test/waPhoneNumberId"
PHONE_NUMBER_ID = "phone-number-id-0123456789abcdef"


def _clear_caches() -> None:
    reset_clients()
    for client in (handler._s3, media._s3, media._ssm):  # `_social` is always faked
        client.cache_clear()


def _create(resource: Any, name: str, key: tuple[str, ...], gsis: tuple[str, ...]) -> Any:
    extra: dict[str, Any] = {}
    if gsis:
        extra["GlobalSecondaryIndexes"] = [
            {
                "IndexName": f"by-{g}",
                "KeySchema": [{"AttributeName": g, "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }
            for g in gsis
        ]
    return resource.create_table(
        TableName=f"suppliagent-test-{name}",
        KeySchema=[{"AttributeName": key[0], "KeyType": "HASH"}]
        + [{"AttributeName": k, "KeyType": "RANGE"} for k in key[1:]],
        AttributeDefinitions=[
            {"AttributeName": a, "AttributeType": "S"} for a in sorted(set(key) | set(gsis))
        ],
        BillingMode="PAY_PER_REQUEST",
        **extra,
    )


@pytest.fixture(autouse=True)
def aws(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("TABLE_PREFIX", "suppliagent-test-")
    monkeypatch.setenv("EVENT_BUS_NAME", "suppliagent-test-events")
    monkeypatch.setenv("INBOUND_MAIL_BUCKET", BUCKET)
    monkeypatch.setenv("MEDIA_BUCKET", MEDIA_BUCKET)
    monkeypatch.setenv("WA_PHONE_NUMBER_ID_PARAM", PHONE_PARAM)
    monkeypatch.setenv("SANDBOX_PARAM", "/suppliagent/test/notifierSandbox")
    monkeypatch.setenv("ORDER_DOMAIN", "ordini.example.com")
    monkeypatch.setenv("TURN_FLUSH_QUEUE_URL", "https://sqs.test/turn-flush")
    monkeypatch.setenv("NOTIFIER_FUNCTION_NAME", "suppliagent-test-notifier")
    monkeypatch.setenv("DEBOUNCE_TEXT_MS", "3000")
    monkeypatch.setenv("DEBOUNCE_MEDIA_MS", "6000")
    with mock_aws():
        _clear_caches()
        resource: Any = boto3.resource("dynamodb")
        for name, (key, gsis) in TABLES.items():
            table = _create(resource, name, key, gsis)
            seed = SEED / f"{name}.json"
            items = json.loads(seed.read_text(), parse_float=Decimal) if seed.exists() else []
            with table.batch_writer() as batch:
                for item in items:
                    batch.put_item(Item=item)
        boto3.client("events").create_event_bus(Name="suppliagent-test-events")
        for bucket in (BUCKET, MEDIA_BUCKET):
            boto3.client("s3").create_bucket(
                Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": "eu-west-1"}
            )
        boto3.client("ssm").put_parameter(Name=PHONE_PARAM, Value=PHONE_NUMBER_ID, Type="String")
        yield resource
        _clear_caches()


class FakeSocial:
    """EUM Social `GetWhatsAppMessageMedia`: writes `<key prefix><mediaId>.<ext>` (moto has no
    `socialmessaging`). `fail` simulates an expired or unknown media id."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail = False
        self.file_size_kb = 1

    def get_whatsapp_message_media(self, **request: Any) -> dict[str, Any]:
        self.calls.append(request)
        if self.fail:
            raise RuntimeError("ResourceNotFoundException")
        target = request["destinationS3File"]
        boto3.client("s3").put_object(
            Bucket=target["bucketName"], Key=f"{target['key']}{request['mediaId']}.jpeg", Body=b"x"
        )
        return {"mimeType": "image/jpeg", "fileSize": self.file_size_kb}


@pytest.fixture(autouse=True)
def social(monkeypatch: pytest.MonkeyPatch) -> FakeSocial:
    fake = FakeSocial()
    monkeypatch.setattr(media, "_social", lambda: fake)
    return fake


class Recorder:
    """Stands in for the SQS and Lambda clients: records the calls the router makes."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []  # SQS send_message
        self.invoked: list[dict[str, Any]] = []  # Lambda invoke
        self.invoke_fails = False

    def send_message(self, **request: Any) -> None:
        self.sent.append(request)

    def invoke(self, **request: Any) -> None:
        if self.invoke_fails:
            raise RuntimeError("ServiceException")
        self.invoked.append(request)


@pytest.fixture(autouse=True)
def recorder(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    fake = Recorder()
    monkeypatch.setattr(handler, "_sqs", lambda: fake)
    monkeypatch.setattr(handler, "_lambda", lambda: fake)
    return fake


# Event builders as fixtures: with `--import-mode=importlib` test modules cannot import each other.
Builder = Callable[..., Any]


def _wa_event(
    messages: list[dict[str, Any]] | None = None,
    at: str = "2026-10-26T10:00:00.123456789Z",
    **value: Any,
) -> dict[str, Any]:
    """EUM Social event: AWS header + `whatsAppWebhookEntry` as a JSON string."""
    content = {"messages": messages} if messages is not None else {}
    entry = {
        "id": "503131219501234",
        "changes": [
            {
                "field": "messages",
                "value": {"messaging_product": "whatsapp", **content, **value},
            }
        ],
    }
    return {
        "context": {},
        "whatsAppWebhookEntry": json.dumps(entry),
        "aws_account_id": "123456789012",
        "message_timestamp": at,
        "messageId": "6d69f07a-c317-4278-9d5c-6a84078419ec",
    }


def _ses_notification(
    destination: str = "ordine@ordini.example.com", dmarc: str = "PASS", virus: str = "PASS"
) -> dict[str, Any]:
    """SES receipt-rule notification (S3 action): the mail itself is in the bucket."""
    return {
        "notificationType": "Received",
        "mail": {
            "timestamp": "2026-10-26T09:30:00.250Z",
            "messageId": "ses-abc",
            "destination": [destination],
        },
        "receipt": {
            "spfVerdict": {"status": "PASS"},
            "dkimVerdict": {"status": "PASS"},
            "dmarcVerdict": {"status": dmarc},
            "virusVerdict": {"status": virus},
            "action": {"type": "S3", "bucketName": BUCKET, "objectKey": "mail/ses-abc"},
        },
    }


def _raw_mail(
    body: str,
    sender: str = "Forno Antico <Ordini.FornoAntico@Example.com>",
    attachments: tuple[tuple[str, str, bytes], ...] = (),
) -> bytes:
    """MIME mail; `attachments` are (filename, mime type, content)."""
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, "ordine@ordini.example.com", "Ordine"
    msg.set_content(body)
    for filename, mime, content in attachments:
        maintype, subtype = mime.split("/")
        msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)
    return msg.as_bytes()


@pytest.fixture
def wa_event() -> Builder:
    return _wa_event


@pytest.fixture
def ses_notification() -> Builder:
    return _ses_notification


@pytest.fixture
def raw_mail() -> Builder:
    return _raw_mail
