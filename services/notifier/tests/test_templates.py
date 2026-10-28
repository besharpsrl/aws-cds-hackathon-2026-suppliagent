"""Notifier WhatsApp templates (T-52, F-13 reorder proposal; F-12 delivery day) and SMS/RCS
(T-27, FN-15, FN-18)."""

import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import boto3
import pytest
from aws_lambda_powertools.utilities import parameters
from botocore.exceptions import ClientError
from moto import mock_aws
from notifier import handler as notifier
from pydantic import ValidationError
from suppliagent_shared.aws import reset_clients
from suppliagent_shared.delivery import DAYS, ROME
from suppliagent_shared.errors import ChannelUnavailableError

TEMPLATES = Path(__file__).parents[1] / "whatsapp_templates"
SANDBOX_PARAM = "/suppliagent/test/notifierSandbox"
QUIET = notifier._quiet  # before the fixture replaces it
CONV = "conv_con001"
RCS_AGENT = "arn:aws:sms-voice:eu-west-1:111111111111:rcs-agent/rcs-test"
SENDER_ID = "arn:aws:sms-voice:eu-west-1:111111111111:sender-id/SUPPLIAGENT/IT"


class Fakes:
    def __init__(self) -> None:
        self.whatsapp: list[dict[str, Any]] = []
        self.rcs: list[dict[str, Any]] = []
        self.sms: list[dict[str, Any]] = []
        self.refuse_rcs = False
        self.refuse_sms = False

    def send_text_message(self, **request: Any) -> dict[str, str]:
        if self.refuse_sms:
            error = {"Error": {"Code": "ValidationException", "Message": "sandbox"}}
            raise ClientError(error, "SendTextMessage")  # type: ignore[arg-type]
        self.sms.append(request)
        return {"MessageId": f"sms-{len(self.sms)}"}

    def send_rcs_message(self, **request: Any) -> dict[str, str]:
        if self.refuse_rcs:
            error = {"Error": {"Code": "ValidationException", "Message": "not a tester"}}
            raise ClientError(error, "SendRcsMessage")  # type: ignore[arg-type]
        self.rcs.append(request)
        return {"MessageId": f"rcs-{len(self.rcs)}"}

    def send_whatsapp_message(self, **request: Any) -> dict[str, str]:
        self.whatsapp.append(json.loads(request["message"]))
        return {"messageId": f"wamid.t{len(self.whatsapp)}"}


def _table(resource: Any, name: str, *keys: str, index: str | None = None) -> None:
    schema = [
        {"AttributeName": k, "KeyType": t} for k, t in zip(keys, ("HASH", "RANGE"), strict=False)
    ]
    attrs = {k for k in keys} | ({index} if index else set())
    extra: dict[str, Any] = {}
    if index:
        extra["GlobalSecondaryIndexes"] = [
            {
                "IndexName": f"by-{index}",
                "KeySchema": [{"AttributeName": index, "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }
        ]
    resource.create_table(
        TableName=f"suppliagent-test-{name}",
        KeySchema=schema,
        AttributeDefinitions=[{"AttributeName": a, "AttributeType": "S"} for a in sorted(attrs)],
        BillingMode="PAY_PER_REQUEST",
        **extra,
    )


def put(name: str, item: dict[str, Any]) -> None:
    boto3.resource("dynamodb").Table(f"suppliagent-test-{name}").put_item(Item=item)


@pytest.fixture(autouse=True)
def fakes(monkeypatch: pytest.MonkeyPatch) -> Iterator[Fakes]:
    for name, value in {
        "AWS_DEFAULT_REGION": "eu-west-1",
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "TABLE_PREFIX": "suppliagent-test-",
        "EVENT_BUS_NAME": "suppliagent-test-events",
        "WA_PHONE_NUMBER_ID_PARAM": "/suppliagent/test/waPhoneNumberId",
        "SANDBOX_PARAM": SANDBOX_PARAM,
        "DELIVERY_CUTOFF": "18:00",
        "RCS_AGENT_PARAM": "/suppliagent/test/rcsAgentArn",
        "SMS_SENDER_PARAM": "/suppliagent/test/smsSenderId",
        "SMS_CONFIGURATION_SET_PARAM": "/suppliagent/test/smsConfigurationSet",
    }.items():
        monkeypatch.setenv(name, value)
    fake = Fakes()
    monkeypatch.setattr(notifier, "_social", lambda: fake)
    monkeypatch.setattr(notifier, "_sms", lambda: fake)
    monkeypatch.setattr(notifier, "_quiet", lambda: False)  # tests run at any hour
    with mock_aws():
        reset_clients()
        parameters.clear_caches()  # type: ignore[no-untyped-call]
        resource: Any = boto3.resource("dynamodb")
        _table(resource, "conversations", "conversationId", index="contactId")
        _table(resource, "turn-buffer", "conversationId")
        _table(resource, "messages", "conversationId", "tsMessageId")
        _table(resource, "customers", "customerId")
        _table(resource, "contacts", "contactId")
        _table(resource, "products", "sku")
        _table(resource, "order-history", "customerId", "dateOrderId")
        _table(resource, "delivery-calendar", "zone", "date")
        _table(resource, "orders", "orderId")
        _table(resource, "deliveries", "orderId")
        _table(resource, "channel-identities", "channelAddress", index="contactId")
        boto3.client("events").create_event_bus(Name="suppliagent-test-events")
        ssm = boto3.client("ssm")
        ssm.put_parameter(Name="/suppliagent/test/waPhoneNumberId", Value="pn-1", Type="String")
        ssm.put_parameter(Name=SANDBOX_PARAM, Value="false", Type="String")
        for name, value in {
            "rcsAgentArn": RCS_AGENT,
            "smsSenderId": SENDER_ID,
            "smsConfigurationSet": "suppliagent-test-sms",
        }.items():
            ssm.put_parameter(Name=f"/suppliagent/test/{name}", Value=value, Type="String")
        put(
            "customers",
            {
                "customerId": "cus_001",
                "venueName": "Pizzeria Test",
                "zone": "MI",
                "deliveryDays": ["MON", "TUE", "WED", "THU", "FRI", "SAT"],
            },
        )
        put(
            "contacts",
            {
                "contactId": "con_001",
                "name": "Luca Bianchi",
                "customerId": "cus_001",
                "customerIds": ["cus_001"],
                "language": "it",
                "status": "VERIFIED",
                "proactiveConsent": True,
            },
        )
        put("products", {"sku": "FDL-1KG", "name": "Fior di latte 1 kg"})
        put("products", {"sku": "PELATI", "name": "Pelati 2,5 kg"})
        put(
            "order-history",
            {"customerId": "cus_001", "dateOrderId": "2026-10-20#ord_h1", "date": "2026-10-20"},
        )
        put(
            "conversations",
            {
                "conversationId": CONV,
                "contactId": "con_001",
                "lastInboundChannel": "WHATSAPP",
                "lastInboundFrom": "+393330000001",
                "lastMessageAt": "2026-10-01T10:00:00.000Z",
                "mode": "AGENT",
            },
        )
        yield fake
        reset_clients()
        parameters.clear_caches()  # type: ignore[no-untyped-call]


def reorder_event(contacts: list[str] | None = None) -> dict[str, Any]:
    return {
        "detail-type": "reorder.due",
        "detail": {
            "customerId": "cus_001",
            "contactIds": contacts or ["con_001"],
            "skus": ["FDL-1KG", "PELATI"],
        },
    }


def delivery_event(to: str = "OUT_FOR_DELIVERY") -> dict[str, Any]:
    return {
        "detail-type": "order.status_changed",
        "detail": {"orderId": "ord_1", "from": "SCHEDULED", "to": to},
    }


def outgoing() -> list[dict[str, Any]]:
    table: Any = boto3.resource("dynamodb").Table("suppliagent-test-messages")
    return list(table.scan()["Items"])


def test_button_ids_and_labels_match_the_approved_templates() -> None:
    for name, languages in notifier.TEMPLATE_BUTTONS.items():
        for language, buttons in languages.items():
            spec = json.loads((TEMPLATES / f"{name}.{language}.json").read_text())
            [component] = [c for c in spec["components"] if c["type"] == "BUTTONS"]
            assert [b["text"] for b in component["buttons"]] == [t for _, t in buttons]


def test_reorder_due_sends_the_template_with_our_quick_reply_payloads(fakes: Fakes) -> None:
    assert notifier.handler(reorder_event(), None) == {"status": "SENT"}

    [message] = fakes.whatsapp
    assert message["to"] == "+393330000001" and message["type"] == "template"
    template = message["template"]
    assert template["name"] == "reorder_suggestion" and template["language"] == {"code": "it"}
    body, *buttons = template["components"]
    name, products, last, delivery = (p["text"] for p in body["parameters"])
    assert (name, products, last) == ("Luca", "fior di latte 1 kg e pelati 2,5 kg", "20 ottobre")
    assert delivery.split()[0] in DAYS["it"]
    assert [b["parameters"][0]["payload"] for b in buttons] == [
        "reorder_same",
        "reorder_modify",
        "reorder_no",
        "reorder_stop",
    ]
    [item] = outgoing()
    assert item["template"] == "reorder_suggestion" and item["providerMessageId"] == "wamid.t1"
    assert item["interactive"]["options"][0] == {"id": "reorder_same", "title": "Riordina uguale"}


def test_reorder_due_is_sent_once(fakes: Fakes) -> None:
    notifier.handler(reorder_event(), None)
    assert notifier.handler(reorder_event(), None) == {"status": "DUPLICATE"}
    assert len(fakes.whatsapp) == 1


def test_no_proposal_without_consent_or_for_another_venue(fakes: Fakes) -> None:
    put(
        "contacts",
        {
            "contactId": "con_002",
            "customerId": "cus_009",
            "customerIds": ["cus_009"],
            "language": "it",
            "status": "VERIFIED",
            "proactiveConsent": True,
        },
    )
    put(
        "contacts",
        {
            "contactId": "con_003",
            "customerId": "cus_001",
            "customerIds": ["cus_001"],
            "language": "it",
            "status": "VERIFIED",
            "proactiveConsent": False,
        },
    )
    result = notifier.handler(reorder_event(["con_002", "con_003"]), None)

    assert result == {"status": "NO_CONSENT,NO_CONSENT"}
    assert fakes.whatsapp == [] and outgoing() == []


def test_no_proposal_off_whatsapp_or_during_a_handoff(fakes: Fakes) -> None:
    base = {"conversationId": CONV, "contactId": "con_001", "lastInboundFrom": "+39333"}
    put("conversations", base | {"mode": "HUMAN", "lastInboundChannel": "WHATSAPP"})
    assert notifier.handler(reorder_event(), None) == {"status": "HANDOFF"}
    put("conversations", base | {"lastInboundChannel": "EMAIL"})
    assert notifier.handler(reorder_event(), None) == {"status": "NO_WHATSAPP"}
    assert fakes.whatsapp == []


def test_sandbox_records_the_template_without_sending(fakes: Fakes) -> None:
    parameters.clear_caches()  # type: ignore[no-untyped-call]
    boto3.client("ssm").put_parameter(
        Name=SANDBOX_PARAM, Value="true", Type="String", Overwrite=True
    )
    assert notifier.handler(reorder_event(), None) == {"status": "SANDBOX"}
    assert fakes.whatsapp == []
    [item] = outgoing()
    assert item["status"] == "SANDBOX" and item["providerMessageId"].startswith("wamid.sandbox_")


def _order(created_by: str = "con_001") -> None:
    put(
        "orders",
        {
            "orderId": "ord_1",
            "customerId": "cus_001",
            "conversationId": CONV,
            "status": "OUT_FOR_DELIVERY",
            "createdBy": created_by,
        },
    )
    put("deliveries", {"orderId": "ord_1", "window": "08:00-12:00", "customerId": "cus_001"})


def test_out_for_delivery_sends_the_delivery_template(fakes: Fakes) -> None:
    _order()
    assert notifier.handler(delivery_event(), None) == {"status": "SENT"}

    [message] = fakes.whatsapp
    body, *buttons = message["template"]["components"]
    assert message["template"]["name"] == "delivery_update"
    assert [p["text"] for p in body["parameters"]] == ["Luca", "ord_1", "08:00", "12:00"]
    assert [b["parameters"][0]["payload"] for b in buttons] == [
        "delivery_received",
        "delivery_issue",
    ]
    assert notifier.handler(delivery_event(), None) == {"status": "DUPLICATE"}


def test_other_status_changes_and_rep_orders_send_nothing(fakes: Fakes) -> None:
    _order(created_by="rep_001")
    assert notifier.handler(delivery_event("SCHEDULED"), None) == {"status": "SKIPPED"}
    assert notifier.handler(delivery_event(), None) == {"status": "NO_CONTACT"}
    assert fakes.whatsapp == []


def sms_identity(verified: bool = True) -> None:
    put(
        "channel-identities",
        {
            "channelAddress": "SMS#+393470000001",
            "channel": "SMS",
            "contactId": "con_001",
            "role": "CUSTOMER_CONTACT",
            "verified": verified,
        },
    )


def test_out_for_delivery_goes_on_rcs_for_a_contact_with_an_sms_identity(fakes: Fakes) -> None:
    _order()
    sms_identity()

    assert notifier.handler(delivery_event(), None) == {"status": "SENT"}

    assert fakes.whatsapp == []
    [call] = fakes.rcs
    assert call["DestinationPhoneNumber"] == "+393470000001"
    assert call["OriginationIdentity"] == RCS_AGENT
    assert call["FallbackConfiguration"]["Channel"] == "SMS"
    assert call["FallbackConfiguration"]["OriginationIdentity"] == SENDER_ID
    assert "08:00" in call["RcsMessageContent"]["Content"]["TextMessage"]["Body"]
    assert [s["Reply"]["PostbackData"] for s in call["RcsMessageContent"]["Suggestions"]] == [
        "delivery_received",
        "delivery_issue",
    ]
    [item] = outgoing()
    assert (item["channel"], item["providerMessageId"]) == ("SMS", "rcs-1")
    assert notifier.handler(delivery_event(), None) == {"status": "DUPLICATE"}


def test_unverified_sms_identity_or_refused_rcs_falls_back_to_whatsapp(fakes: Fakes) -> None:
    _order()
    sms_identity(verified=False)
    assert notifier.handler(delivery_event(), None) == {"status": "SENT"}
    assert fakes.rcs == [] and len(fakes.whatsapp) == 1


def test_rcs_refused_sends_a_plain_sms_without_options(fakes: Fakes) -> None:
    _order()
    sms_identity()
    fakes.refuse_rcs = True
    assert notifier.handler(delivery_event(), None) == {"status": "SENT"}
    [call] = fakes.sms
    assert call["OriginationIdentity"] == SENDER_ID and "08:00" in call["MessageBody"]
    assert fakes.whatsapp == []
    [item] = outgoing()
    assert "interactive" not in item  # one-way: nothing to tap


def test_rcs_and_sms_refused_sends_the_whatsapp_template(fakes: Fakes) -> None:
    _order()
    sms_identity()
    fakes.refuse_rcs = fakes.refuse_sms = True
    assert notifier.handler(delivery_event(), None) == {"status": "SENT"}
    assert len(fakes.whatsapp) == 1


def test_a_reply_on_the_sms_channel_goes_out_on_rcs_with_suggested_replies(fakes: Fakes) -> None:
    put(
        "conversations",
        {
            "conversationId": CONV,
            "contactId": "con_001",
            "lastInboundChannel": "SMS",
            "lastInboundFrom": "+393470000001",
            "mode": "AGENT",
        },
    )
    request = {
        "kind": "reply",
        "conversationId": CONV,
        "idempotencyKey": "turn#1",
        "text": "Che tipo di problema?",
        "interactive": {
            "kind": "CHOICE",
            "options": [{"id": "opt_1", "title": "Mancante"}, {"id": "opt_2", "title": "Rotto"}],
        },
    }
    assert notifier.handler(request, None) == {"status": "SENT"}
    [call] = fakes.rcs
    assert [s["Reply"]["Text"] for s in call["RcsMessageContent"]["Suggestions"]] == [
        "Mancante",
        "Rotto",
    ]


def test_rcs_not_configured_is_channel_unavailable(fakes: Fakes) -> None:
    parameters.clear_caches()  # type: ignore[no-untyped-call]
    boto3.client("ssm").put_parameter(
        Name="/suppliagent/test/rcsAgentArn", Value="UNSET", Type="String", Overwrite=True
    )
    put(
        "conversations",
        {"conversationId": CONV, "lastInboundChannel": "SMS", "lastInboundFrom": "+3934700"},
    )
    request = {"kind": "reply", "conversationId": CONV, "idempotencyKey": "k", "text": "Ciao"}
    with pytest.raises(ChannelUnavailableError):
        notifier.handler(request, None)
    assert fakes.rcs == []


def test_order_confirmation_sms_next_to_the_email(fakes: Fakes) -> None:
    sms_identity()
    put(
        "orders",
        {
            "orderId": "ord_1",
            "customerId": "cus_001",
            "conversationId": CONV,
            "status": "SUBMITTED",
            "confirmedBy": "con_001",
            "deliveryDate": "2026-10-29",
            "revision": 0,
        },
    )
    notifier._order_sms({"orderId": "ord_1", "reason": "confirmed", "revision": 0})
    notifier._order_sms({"orderId": "ord_1", "reason": "confirmed", "revision": 0})

    [call] = fakes.rcs
    body = call["RcsMessageContent"]["Content"]["TextMessage"]["Body"]
    assert "ord_1" in body and "giovedì 29 ottobre" in body
    assert "Suggestions" not in call["RcsMessageContent"]


def test_no_order_sms_without_an_sms_identity(fakes: Fakes) -> None:
    put(
        "orders",
        {
            "orderId": "ord_1",
            "customerId": "cus_001",
            "status": "SUBMITTED",
            "confirmedBy": "con_001",
            "deliveryDate": "2026-10-29",
        },
    )
    notifier._order_sms({"orderId": "ord_1", "reason": "confirmed"})
    assert fakes.rcs == []


def test_no_reorder_suggestion_in_the_quiet_hours(
    fakes: Fakes, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(notifier, "_quiet", lambda: True)
    assert notifier.handler(reorder_event(), None) == {"status": "QUIET"}
    assert fakes.whatsapp == []


def test_quiet_hours_cross_midnight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUIET_HOURS", "21:00-07:00")
    for hour, quiet in ((22, True), (3, True), (7, False), (12, False), (20, False)):
        moment = datetime(2026, 10, 28, hour, 30, tzinfo=ROME)
        monkeypatch.setattr(notifier, "rome", lambda m=moment: m)
        assert QUIET() is quiet


# --- T-24: templates outside the 24 h window, channel fallback, retries, opt-out -------------

OLD = "2020-01-01T00:00:00.000Z"  # the WhatsApp window closed long ago


def whatsapp_conversation(last_inbound: str = OLD) -> None:
    put(
        "conversations",
        {
            "conversationId": CONV,
            "contactId": "con_001",
            "lastInboundChannel": "WHATSAPP",
            "lastInboundFrom": "+393330000001",
            "lastWhatsappInboundAt": last_inbound,
            "lastInboundLocale": "it-IT",
            "mode": "AGENT",
        },
    )


def reminder(**extra: Any) -> dict[str, Any]:
    return {
        "kind": "reply",
        "conversationId": CONV,
        "idempotencyKey": "reminder#ord_1#t",
        "text": "Il riepilogo del tuo ordine è ancora in attesa di conferma.",
        **extra,
    }


TEMPLATE = {"name": "order_pending_reminder", "params": ["12", "giovedì 29 ottobre", "oggi 18:00"]}


def test_outside_the_window_the_named_template_goes_out(fakes: Fakes) -> None:
    whatsapp_conversation()
    assert notifier.handler(reminder(template=TEMPLATE), None) == {"status": "SENT"}

    [message] = fakes.whatsapp
    assert message["type"] == "template"
    body, *buttons = message["template"]["components"]
    assert [p["text"] for p in body["parameters"]] == [
        "Luca",
        "12",
        "giovedì 29 ottobre",
        "oggi 18:00",
    ]
    assert [b["parameters"][0]["payload"] for b in buttons] == [
        "order_show_summary",
        "order_cancel_draft",
    ]
    [item] = outgoing()
    assert item["template"] == "order_pending_reminder"


def test_inside_the_window_the_text_goes_out_even_with_a_template(fakes: Fakes) -> None:
    whatsapp_conversation("2099-01-01T00:00:00.000Z")
    notifier.handler(reminder(template=TEMPLATE), None)
    assert [m["type"] for m in fakes.whatsapp] == ["text"]


def test_outside_the_window_without_template_the_reply_goes_on_rcs(fakes: Fakes) -> None:
    whatsapp_conversation()
    sms_identity()
    assert notifier.handler(reminder(), None) == {"status": "SENT"}
    assert fakes.whatsapp == []
    [call] = fakes.rcs
    assert call["DestinationPhoneNumber"] == "+393470000001"
    [item] = outgoing()
    assert item["channel"] == "SMS"


def test_outside_the_window_with_no_other_channel_is_unavailable(fakes: Fakes) -> None:
    whatsapp_conversation()
    with pytest.raises(ChannelUnavailableError):
        notifier.handler(reminder(), None)
    assert outgoing() == []


def test_an_unknown_template_is_refused(fakes: Fakes) -> None:
    whatsapp_conversation()
    with pytest.raises(ValidationError):
        notifier.handler(reminder(template={"name": "promo", "params": ["x"]}), None)


def test_transient_errors_are_retried_then_the_reply_goes_out(
    fakes: Fakes, monkeypatch: pytest.MonkeyPatch
) -> None:
    whatsapp_conversation("2099-01-01T00:00:00.000Z")
    monkeypatch.setattr(notifier, "RETRY_BASE_SECONDS", 0)
    calls = {"n": 0}
    send = fakes.send_whatsapp_message

    def flaky(**request: Any) -> dict[str, str]:
        calls["n"] += 1
        if calls["n"] < 3:
            error = {"Error": {"Code": "ThrottlingException", "Message": "slow down"}}
            raise ClientError(error, "SendWhatsAppMessage")  # type: ignore[arg-type]
        return send(**request)

    monkeypatch.setattr(fakes, "send_whatsapp_message", flaky)
    assert notifier.handler(reminder(), None) == {"status": "SENT"}
    assert calls["n"] == 3


def test_whatsapp_still_failing_after_the_retries_is_not_resent_elsewhere(
    fakes: Fakes, monkeypatch: pytest.MonkeyPatch
) -> None:
    whatsapp_conversation("2099-01-01T00:00:00.000Z")
    sms_identity()
    monkeypatch.setattr(notifier, "RETRY_BASE_SECONDS", 0)
    calls = {"n": 0}

    def down(**_request: Any) -> dict[str, str]:
        calls["n"] += 1
        error = {"Error": {"Code": "InternalServerException", "Message": "down"}}
        raise ClientError(error, "SendWhatsAppMessage")  # type: ignore[arg-type]

    monkeypatch.setattr(fakes, "send_whatsapp_message", down)
    # it may have been delivered: the caller retries with the same key, never a second channel
    with pytest.raises(ClientError):
        notifier.handler(reminder(), None)
    assert calls["n"] == notifier.SEND_ATTEMPTS and fakes.rcs == []


def test_whatsapp_refusing_the_message_falls_back_to_rcs(
    fakes: Fakes, monkeypatch: pytest.MonkeyPatch
) -> None:
    whatsapp_conversation("2099-01-01T00:00:00.000Z")
    sms_identity()

    def refused(**_request: Any) -> dict[str, str]:
        error = {"Error": {"Code": "ValidationException", "Message": "not on WhatsApp"}}
        raise ClientError(error, "SendWhatsAppMessage")  # type: ignore[arg-type]

    monkeypatch.setattr(fakes, "send_whatsapp_message", refused)
    assert notifier.handler(reminder(), None) == {"status": "SENT"}
    assert len(fakes.rcs) == 1


def test_whatsapp_not_configured_inside_the_window_goes_on_rcs_not_template(
    fakes: Fakes,
) -> None:
    parameters.clear_caches()  # type: ignore[no-untyped-call]
    boto3.client("ssm").put_parameter(
        Name="/suppliagent/test/waPhoneNumberId", Value="UNSET", Type="String", Overwrite=True
    )
    whatsapp_conversation("2099-01-01T00:00:00.000Z")
    sms_identity()
    assert notifier.handler(reminder(template=TEMPLATE), None) == {"status": "SENT"}
    assert fakes.whatsapp == [] and len(fakes.rcs) == 1


def test_the_rcs_fallback_skips_a_number_that_sent_stop(fakes: Fakes) -> None:
    whatsapp_conversation()
    put(
        "channel-identities",
        {
            "channelAddress": "SMS#+393470000001",
            "channel": "SMS",
            "contactId": "con_001",
            "role": "CUSTOMER_CONTACT",
            "verified": True,
            "optedOutAt": "2026-10-28T10:00:00Z",
        },
    )
    with pytest.raises(ChannelUnavailableError):
        notifier.handler(reminder(), None)
    assert fakes.rcs == [] and fakes.sms == []


def test_an_rcs_server_error_is_not_resent_as_sms(
    fakes: Fakes, monkeypatch: pytest.MonkeyPatch
) -> None:
    _order()
    sms_identity()
    monkeypatch.setattr(notifier, "RETRY_BASE_SECONDS", 0)

    def down(**_request: Any) -> dict[str, str]:
        error = {"Error": {"Code": "ThrottlingException", "Message": "slow"}}
        raise ClientError(error, "SendRcsMessage")  # type: ignore[arg-type]

    monkeypatch.setattr(fakes, "send_rcs_message", down)
    # the delivery message then goes on the WhatsApp template (its own channel decision)
    notifier.handler(delivery_event(), None)
    assert fakes.sms == []


def test_validation_errors_are_not_retried(fakes: Fakes, monkeypatch: pytest.MonkeyPatch) -> None:
    whatsapp_conversation("2099-01-01T00:00:00.000Z")
    calls = {"n": 0}

    def invalid(**_request: Any) -> dict[str, str]:
        calls["n"] += 1
        error = {"Error": {"Code": "ValidationException", "Message": "bad"}}
        raise ClientError(error, "SendWhatsAppMessage")  # type: ignore[arg-type]

    monkeypatch.setattr(fakes, "send_whatsapp_message", invalid)
    with pytest.raises(ClientError):
        notifier.handler(reminder(), None)
    assert calls["n"] == 1


def test_no_rcs_to_a_number_that_sent_stop(fakes: Fakes) -> None:
    _order()
    put(
        "channel-identities",
        {
            "channelAddress": "SMS#+393470000001",
            "channel": "SMS",
            "contactId": "con_001",
            "role": "CUSTOMER_CONTACT",
            "verified": True,
            "optedOutAt": "2026-10-28T10:00:00Z",
        },
    )
    assert notifier.handler(delivery_event(), None) == {"status": "SENT"}
    assert fakes.rcs == [] and len(fakes.whatsapp) == 1  # the WhatsApp template instead
    put(
        "conversations",
        {"conversationId": CONV, "lastInboundChannel": "SMS", "lastInboundFrom": "+393470000001"},
    )
    with pytest.raises(ChannelUnavailableError):
        notifier.handler(
            {"kind": "reply", "conversationId": CONV, "idempotencyKey": "k2", "text": "ok"}, None
        )
