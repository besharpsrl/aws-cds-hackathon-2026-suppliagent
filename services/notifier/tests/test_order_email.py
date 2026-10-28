"""Notifier: order confirmation email with PDF (T-26, FN-14, F-07.C7) and its bounces (F-11.C7)."""

import json
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import boto3
import pytest
from aws_lambda_powertools.utilities import parameters
from moto import mock_aws
from notifier import handler as notifier
from notifier.order_email import format_date, render
from suppliagent_shared.aws import reset_clients
from suppliagent_shared.errors import InvalidInputError, NotFoundError

BUCKET = "suppliagent-test-documents"
SANDBOX_PARAM = "/suppliagent/test/notifierSandbox"
CONV = "conv_con001"
RECENT = "2099-01-01T00:00:00.000Z"
PDF = b"%PDF-1.4 test"
ORDER: dict[str, Any] = {
    "orderId": "ord_abc123",
    "customerId": "cus_001",
    "status": "CONFIRMED",
    "conversationId": CONV,
    "createdBy": "con_001",
    "confirmedBy": "con_001",
    "deliveryDate": "2026-10-29",
    "deliveryNotes": "Citofono <rotto>",
    "total": Decimal("1256.50"),
    "lines": [
        {
            "lineId": "l1",
            "status": "CONFIRMED",
            "sku": "FDL-PIZZA-1KG",
            "name": "Fior di latte",
            "format": "1 kg",
            "quantity": Decimal(25),
            "unit": "kg",
            "lineTotal": Decimal("200.00"),
        },
        {"lineId": "l2", "status": "REMOVED", "sku": "X", "name": "Burro tolto", "quantity": 1},
    ],
}


def table_spec(name: str, key: str, gsi: str | None = None) -> dict[str, Any]:
    attributes = {key} | ({gsi} if gsi else set())
    spec: dict[str, Any] = {
        "TableName": f"suppliagent-test-{name}",
        "KeySchema": [{"AttributeName": key, "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": a, "AttributeType": "S"} for a in attributes],
        "BillingMode": "PAY_PER_REQUEST",
    }
    if gsi:
        spec["GlobalSecondaryIndexes"] = [
            {
                "IndexName": f"by-{gsi}",
                "KeySchema": [{"AttributeName": gsi, "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }
        ]
    return spec


class Fakes:
    def __init__(self) -> None:
        self.emails: list[dict[str, Any]] = []
        self.whatsapp: list[dict[str, Any]] = []
        self.fail = False

    def send_email(self, **request: Any) -> dict[str, str]:
        if self.fail:
            raise RuntimeError("Throttling")
        self.emails.append(request)
        return {"MessageId": "ses-1"}

    def send_whatsapp_message(self, **request: Any) -> dict[str, str]:
        self.whatsapp.append({**request, "message": json.loads(request["message"])})
        return {"messageId": "wamid.out1"}


@pytest.fixture(autouse=True)
def fakes(monkeypatch: pytest.MonkeyPatch) -> Iterator[Fakes]:
    for name, value in {
        "AWS_DEFAULT_REGION": "eu-west-1",
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "TABLE_PREFIX": "suppliagent-test-",
        "EVENT_BUS_NAME": "suppliagent-test-events",
        "WA_PHONE_NUMBER_ID_PARAM": "/suppliagent/test/waPhoneNumberId",
        "SES_FROM_PARAM": "/suppliagent/test/sesFromAddress",
        "SES_CONFIGURATION_SET_PARAM": "/suppliagent/test/sesConfigurationSet",
        "SANDBOX_PARAM": SANDBOX_PARAM,
        "DOCUMENTS_BUCKET": BUCKET,
    }.items():
        monkeypatch.setenv(name, value)
    fake = Fakes()
    monkeypatch.setattr(notifier, "_social", lambda: fake)
    monkeypatch.setattr(notifier, "_ses", lambda: fake)
    with mock_aws():
        reset_clients()
        notifier._s3.cache_clear()
        parameters.clear_caches()  # type: ignore[no-untyped-call]
        db: Any = boto3.resource("dynamodb")
        for spec in (
            table_spec("orders", "orderId"),
            table_spec("contacts", "contactId"),
            table_spec("channel-identities", "channelAddress", "contactId"),
            table_spec("customers", "customerId"),
            table_spec("sales-reps", "repId"),
            table_spec("conversations", "conversationId"),
            table_spec("turn-buffer", "conversationId"),
        ):
            db.create_table(**spec)
        db.create_table(
            TableName="suppliagent-test-messages",
            KeySchema=[
                {"AttributeName": "conversationId", "KeyType": "HASH"},
                {"AttributeName": "tsMessageId", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "conversationId", "AttributeType": "S"},
                {"AttributeName": "tsMessageId", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        db.Table("suppliagent-test-orders").put_item(Item=ORDER)
        db.Table("suppliagent-test-customers").put_item(
            Item={"customerId": "cus_001", "venueName": "Pizzeria Il Forno Antico"}
        )
        db.Table("suppliagent-test-contacts").put_item(
            Item={"contactId": "con_001", "language": "it", "orderEmail": "luca@example.org"}
        )
        db.Table("suppliagent-test-contacts").put_item(
            Item={"contactId": "con_004", "language": "en"}
        )
        db.Table("suppliagent-test-sales-reps").put_item(
            Item={"repId": "rep_001", "language": "it"}
        )
        db.Table("suppliagent-test-channel-identities").put_item(
            Item={
                "channelAddress": "EMAIL#marco.rinaldi@example.com",
                "channel": "EMAIL",
                "contactId": "rep_001",
                "verified": True,
            }
        )
        db.Table("suppliagent-test-conversations").put_item(
            Item={
                "conversationId": CONV,
                "lastInboundChannel": "WHATSAPP",
                "lastInboundFrom": "+393330000001",
                "lastWhatsappInboundAt": RECENT,
            }
        )
        s3 = boto3.client("s3")
        s3.create_bucket(
            Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": "eu-west-1"}
        )
        s3.put_object(Bucket=BUCKET, Key="orders/ord_abc123.pdf", Body=PDF)
        boto3.client("events").create_event_bus(Name="suppliagent-test-events")
        ssm = boto3.client("ssm")
        for name, value in {
            "sesFromAddress": "ordine@ordini.example.com",
            "sesConfigurationSet": "suppliagent-test-cs",
            "waPhoneNumberId": "phone-1",
        }.items():
            ssm.put_parameter(Name=f"/suppliagent/test/{name}", Value=value, Type="String")
        yield fake
        reset_clients()
        notifier._s3.cache_clear()
        parameters.clear_caches()  # type: ignore[no-untyped-call]


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    sent: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(notifier, "put_event", lambda _s, kind, detail: sent.append((kind, detail)))
    return sent


def live() -> None:
    parameters.clear_caches()  # type: ignore[no-untyped-call]
    boto3.client("ssm").put_parameter(
        Name=SANDBOX_PARAM, Value="false", Type="String", Overwrite=True
    )


def pdf_ready(order_id: str = "ord_abc123", reason: str = "confirmed") -> dict[str, Any]:
    return {
        "source": "suppliagent.order-pdf",
        "detail-type": "order.pdf_ready",
        "detail": {"orderId": order_id, "reason": reason, "revision": 0},
    }


def update_order(**fields: Any) -> None:
    boto3.resource("dynamodb").Table("suppliagent-test-orders").put_item(Item={**ORDER, **fields})


def outgoing() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = (
        boto3.resource("dynamodb").Table("suppliagent-test-messages").scan()["Items"]
    )
    return [i for i in items if i["direction"] == "OUTBOUND"]


# --- the email ---------------------------------------------------------------------------


def test_confirmed_order_email_with_pdf_goes_to_the_contact(fakes: Fakes, events: Any) -> None:
    live()
    assert notifier.handler(pdf_ready(), None) == {"status": "SENT"}

    [email] = fakes.emails
    assert email["FromEmailAddress"] == "ordine@ordini.example.com"
    assert email["Destination"] == {"ToAddresses": ["luca@example.org"]}
    assert email["ReplyToAddresses"] == ["ordine+ord_abc123@ordini.example.com"]
    assert email["ConfigurationSetName"] == "suppliagent-test-cs"
    simple = email["Content"]["Simple"]
    assert simple["Subject"]["Data"] == "Conferma ordine ord_abc123 - consegna gio 29/10/2026"
    [attachment] = simple["Attachments"]
    assert attachment["RawContent"] == PDF and attachment["FileName"] == "ord_abc123.pdf"
    assert attachment["ContentType"] == "application/pdf"
    html = simple["Body"]["Html"]["Data"]
    assert "Pizzeria Il Forno Antico" in html and "Fior di latte (1 kg)" in html
    assert "€ 1.256,50" in html and "Citofono &lt;rotto&gt;" in html  # escaped
    assert "Burro tolto" not in html  # removed lines are not part of the order
    assert "Fior di latte (1 kg)" in simple["Body"]["Text"]["Data"]
    assert {"Name": "orderId", "Value": "ord_abc123"} in email["EmailTags"]
    [record] = outgoing()
    assert (record["conversationId"], record["channel"], record["status"]) == (
        CONV,
        "EMAIL",
        "SENT",
    )
    assert record["orderId"] == "ord_abc123" and "luca@" not in record["text"]
    assert events == [
        (
            "notification.sent",
            {
                "orderId": "ord_abc123",
                "channel": "EMAIL",
                "template": "order_confirmation",
                "sandbox": False,
            },
        )
    ]


def test_in_sandbox_the_email_is_only_recorded(fakes: Fakes) -> None:
    assert notifier.handler(pdf_ready(), None) == {"status": "SANDBOX"}
    assert fakes.emails == []
    assert outgoing()[0]["status"] == "SANDBOX"


def test_one_email_per_order_revision(fakes: Fakes) -> None:
    live()
    notifier.handler(pdf_ready(), None)
    assert notifier.handler(pdf_ready(), None) == {"status": "DUPLICATE"}
    assert len(fakes.emails) == 1

    update_order(revision=1, status="SUBMITTED")  # F-08.C2: changed before the cut-off
    updated = pdf_ready(reason="updated")
    updated["detail"]["revision"] = 1
    assert notifier.handler(updated, None) == {"status": "SENT"}
    subject = fakes.emails[-1]["Content"]["Simple"]["Subject"]["Data"]
    assert subject.startswith("Ordine aggiornato ord_abc123")


def test_a_late_event_for_an_older_revision_sends_nothing(fakes: Fakes) -> None:
    live()
    update_order(revision=1, status="SUBMITTED")  # changed before the confirmed event arrived
    assert notifier.handler(pdf_ready(), None) == {"status": "SUPERSEDED"}
    event = pdf_ready(reason="updated")
    event["detail"]["revision"] = 1
    assert notifier.handler(event, None) == {"status": "SENT"}
    [email] = fakes.emails
    assert email["Content"]["Simple"]["Subject"]["Data"].startswith("Ordine aggiornato")


def test_a_failed_send_can_be_retried(fakes: Fakes, events: Any) -> None:
    live()
    fakes.fail = True
    with pytest.raises(RuntimeError):
        notifier.handler(pdf_ready(), None)
    assert events[-1][0] == "notification.failed"
    fakes.fail = False
    assert notifier.handler(pdf_ready(), None) == {"status": "SENT"}


def test_without_an_email_nothing_is_sent(fakes: Fakes, events: Any) -> None:  # F-07.C7
    live()
    update_order(confirmedBy="con_004", createdBy="con_004")
    assert notifier.handler(pdf_ready(), None) == {"status": "NO_EMAIL"}
    assert fakes.emails == [] and outgoing() == []
    assert events[0][0] == "notification.skipped" and events[0][1]["reason"] == "NO_EMAIL"


def test_english_contact_gets_the_english_email(fakes: Fakes, aws_contact_en: None) -> None:
    live()
    notifier.handler(pdf_ready(), None)
    simple = fakes.emails[0]["Content"]["Simple"]
    assert simple["Subject"]["Data"] == "Order confirmation ord_abc123 - delivery Thu 29 Oct 2026"
    assert "€ 1,256.50" in simple["Body"]["Html"]["Data"]


@pytest.fixture
def aws_contact_en() -> None:
    boto3.resource("dynamodb").Table("suppliagent-test-contacts").put_item(
        Item={"contactId": "con_004", "language": "en", "orderEmail": "sarah@example.co.uk"}
    )
    update_order(confirmedBy="con_004", createdBy="con_004")


def test_order_confirmed_by_a_sales_rep_goes_to_the_rep(fakes: Fakes) -> None:  # F-10.D
    live()
    update_order(confirmedBy="rep_001", createdBy="rep_001")
    notifier.handler(pdf_ready(), None)
    assert fakes.emails[0]["Destination"] == {"ToAddresses": ["marco.rinaldi@example.com"]}


@pytest.mark.parametrize("status", ["CANCELLED", "EXPIRED", "PENDING_CONFIRMATION", "DRAFT"])
def test_no_email_for_an_order_that_is_not_confirmed(fakes: Fakes, status: str) -> None:
    live()
    update_order(status=status)
    assert notifier.handler(pdf_ready(), None) == {"status": "SKIPPED"}
    assert fakes.emails == []


def test_unknown_or_malformed_order(fakes: Fakes) -> None:
    with pytest.raises(NotFoundError):
        notifier.handler(pdf_ready("ord_nope"), None)
    with pytest.raises(InvalidInputError):
        notifier.handler(pdf_ready("../x"), None)


def test_dates_and_languages() -> None:
    assert format_date("2026-11-02", "it") == "lun 02/11/2026"
    assert format_date(None, "en") == "-"
    email = render({**ORDER, "erpOrderNumber": "ERP-abc123"}, "Venue", "en-GB")
    assert "Order number" in email.text and "ERP-abc123" in email.html
    assert 'name="viewport"' in email.html and "max-width:600px" in email.html


# --- bounces ------------------------------------------------------------------------------


def ses_event(event_type: str = "Bounce", bounce_type: str = "Permanent") -> dict[str, Any]:
    message = {
        "eventType": event_type,
        "bounce": {
            "bounceType": bounce_type,
            "bouncedRecipients": [{"emailAddress": "Luca@example.org"}],
        },
        "mail": {
            "messageId": "ses-1",
            "tags": {
                "template": ["order_confirmation"],
                "orderId": ["ord_abc123"],
                "contactId": ["con_001"],
                "ses:configuration-set": ["suppliagent-test-cs"],
            },
        },
    }
    return {"Records": [{"EventSource": "aws:sns", "Sns": {"Message": json.dumps(message)}}]}


def contact(contact_id: str = "con_001") -> dict[str, Any]:
    item: dict[str, Any] = (
        boto3.resource("dynamodb")
        .Table("suppliagent-test-contacts")
        .get_item(Key={"contactId": contact_id})["Item"]
    )
    return item


def test_hard_bounce_clears_the_address_and_asks_for_a_new_one(fakes: Fakes, events: Any) -> None:
    live()
    assert notifier.handler(ses_event(), None) == {"status": "OK", "bounces": "1"}

    stored = contact()
    assert "orderEmail" not in stored and "orderEmailBouncedAt" in stored
    [message] = fakes.whatsapp
    assert message["message"]["to"] == "+393330000001"
    assert "ord_abc123" in message["message"]["text"]["body"]
    failed = [d for kind, d in events if kind == "notification.failed"]
    assert failed == [
        {
            "orderId": "ord_abc123",
            "channel": "EMAIL",
            "template": "order_confirmation",
            "sandbox": False,
            "reason": "BOUNCED",
        }
    ]
    assert notifier.handler(ses_event(), None)["bounces"] == "1"  # SNS redelivery
    assert len(fakes.whatsapp) == 1  # asked once


def test_a_newer_address_survives_an_old_bounce(fakes: Fakes) -> None:
    boto3.resource("dynamodb").Table("suppliagent-test-contacts").put_item(
        Item={"contactId": "con_001", "language": "it", "orderEmail": "new@example.org"}
    )
    notifier.handler(ses_event(), None)
    assert contact()["orderEmail"] == "new@example.org"


@pytest.mark.parametrize(
    ("event_type", "bounce_type"), [("Delivery", "Permanent"), ("Bounce", "Transient")]
)
def test_other_ses_events_change_nothing(fakes: Fakes, event_type: str, bounce_type: str) -> None:
    assert notifier.handler(ses_event(event_type, bounce_type), None)["bounces"] == "0"
    assert contact()["orderEmail"] == "luca@example.org" and fakes.whatsapp == []


def test_a_bounce_to_a_sales_rep_asks_nothing(fakes: Fakes, events: Any) -> None:
    live()
    message = json.loads(ses_event()["Records"][0]["Sns"]["Message"])
    message["mail"]["tags"]["contactId"] = ["rep_001"]
    event = {"Records": [{"Sns": {"Message": json.dumps(message)}}]}
    assert notifier.handler(event, None)["bounces"] == "1"
    assert fakes.whatsapp == []  # the rep cannot set an order email: the back office fixes it
    assert [kind for kind, _ in events] == ["notification.failed"]
