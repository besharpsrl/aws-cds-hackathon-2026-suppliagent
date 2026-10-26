"""Notifier (T-24 base): FN-01 replies on the contact's channel, sandbox, idempotency, authz."""

import json
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from aws_lambda_powertools.utilities import parameters
from moto import mock_aws
from notifier import handler as notifier
from pydantic import ValidationError
from suppliagent_shared.aws import reset_clients
from suppliagent_shared.errors import (
    AccessDeniedError,
    ChannelUnavailableError,
    InvalidInputError,
)

CONV = "conv_con001"
OTHER = "conv_con002"
PHONE_ID = "phone-number-id-0123456789abcdef"
SANDBOX_PARAM = "/suppliagent/test/notifierSandbox"


def clear_parameter_cache() -> None:
    parameters.clear_caches()  # type: ignore[no-untyped-call]  # Powertools caches per process


RECENT = "2099-01-01T00:00:00.000Z"  # inside the 24 h window for any `now`


class Fakes:
    def __init__(self) -> None:
        self.whatsapp: list[dict[str, Any]] = []
        self.emails: list[dict[str, Any]] = []
        self.fail = False

    def send_whatsapp_message(self, **request: Any) -> dict[str, str]:
        if self.fail:
            raise RuntimeError("ThrottlingException")
        self.whatsapp.append({**request, "message": json.loads(request["message"])})
        return {"messageId": "wamid.out1"}

    def send_email(self, **request: Any) -> dict[str, str]:
        self.emails.append(request)
        return {"MessageId": "ses-1"}


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
    }.items():
        monkeypatch.setenv(name, value)
    fake = Fakes()
    monkeypatch.setattr(notifier, "_social", lambda: fake)
    monkeypatch.setattr(notifier, "_ses", lambda: fake)
    with mock_aws():
        reset_clients()
        clear_parameter_cache()  # Powertools caches parameters per process
        resource: Any = boto3.resource("dynamodb")
        resource.create_table(
            TableName="suppliagent-test-conversations",
            KeySchema=[{"AttributeName": "conversationId", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "conversationId", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        resource.create_table(
            TableName="suppliagent-test-turn-buffer",
            KeySchema=[{"AttributeName": "conversationId", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "conversationId", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        resource.create_table(
            TableName="suppliagent-test-messages",
            KeySchema=[
                {"AttributeName": "conversationId", "KeyType": "HASH"},
                {"AttributeName": "tsMessageId", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "conversationId", "AttributeType": "S"},
                {"AttributeName": "tsMessageId", "AttributeType": "S"},
                {"AttributeName": "providerMessageId", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "by-providerMessageId",
                    "KeySchema": [{"AttributeName": "providerMessageId", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        boto3.client("events").create_event_bus(Name="suppliagent-test-events")
        ssm = boto3.client("ssm")
        for name, value in {
            "waPhoneNumberId": PHONE_ID,
            "sesFromAddress": "ordine@ordini.example.com",
            "sesConfigurationSet": "suppliagent-test",
        }.items():
            ssm.put_parameter(Name=f"/suppliagent/test/{name}", Value=value, Type="String")
        conversation(CONV)
        yield fake
        reset_clients()
        clear_parameter_cache()


def conversation(conversation_id: str, **extra: Any) -> None:
    item = {
        "conversationId": conversation_id,
        "lastInboundChannel": "WHATSAPP",
        "lastInboundFrom": "+393330000001",
        "lastWhatsappInboundAt": RECENT,
        "lastInboundLocale": "it-IT",
    } | extra
    table: Any = boto3.resource("dynamodb").Table("suppliagent-test-conversations")
    table.put_item(Item={k: v for k, v in item.items() if v is not None})


def sandbox(value: str) -> None:
    clear_parameter_cache()
    boto3.client("ssm").put_parameter(
        Name=SANDBOX_PARAM, Value=value, Type="String", Overwrite=True
    )


def reply(key: str = "turn#a#b", text: str = "Ciao Anna!", conv: str = CONV) -> dict[str, Any]:
    return {"kind": "reply", "conversationId": conv, "idempotencyKey": key, "text": text}


def outgoing(conv: str = CONV) -> list[dict[str, Any]]:
    table: Any = boto3.resource("dynamodb").Table("suppliagent-test-messages")
    items: list[dict[str, Any]] = table.scan()["Items"]
    return [i for i in items if i["conversationId"] == conv and i["direction"] == "OUTBOUND"]


def ts_id(provider_id: str) -> str:
    return f"2026-10-26T10:00:00.000Z#{provider_id}"


def receipt(provider_id: str, conv: str = CONV) -> dict[str, Any]:
    return {
        "kind": "read_receipt",
        "conversationId": conv,
        "providerMessageId": provider_id,
        "tsMessageId": ts_id(provider_id),
    }


def inbound(provider_id: str, conv: str = CONV, channel: str = "WHATSAPP") -> None:
    table: Any = boto3.resource("dynamodb").Table("suppliagent-test-messages")
    table.put_item(
        Item={
            "conversationId": conv,
            "tsMessageId": ts_id(provider_id),
            "providerMessageId": provider_id,
            "channel": channel,
            "direction": "INBOUND",
        }
    )


def test_without_the_sandbox_parameter_nothing_is_sent_but_the_reply_is_recorded(
    fakes: Fakes,
) -> None:
    result = notifier.handler(reply(), None)  # fail safe: a missing parameter means sandbox

    assert result == {"status": "SANDBOX"}
    assert fakes.whatsapp == [] and fakes.emails == []
    [item] = outgoing()
    assert (item["text"], item["channel"], item["status"]) == ("Ciao Anna!", "WHATSAPP", "SANDBOX")
    assert "providerMessageId" not in item


def test_whatsapp_reply_goes_to_the_address_of_the_last_inbound_message(fakes: Fakes) -> None:
    sandbox("false")

    assert notifier.handler(reply(), None) == {"status": "SENT"}

    [call] = fakes.whatsapp
    assert call["originationPhoneNumberId"] == PHONE_ID
    assert call["message"] == {
        "messaging_product": "whatsapp",
        "to": "+393330000001",
        "type": "text",
        "text": {"body": "Ciao Anna!"},
    }
    [item] = outgoing()
    assert (item["status"], item["providerMessageId"]) == ("SENT", "wamid.out1")


def test_long_whatsapp_text_is_cut_to_the_provider_limit(fakes: Fakes) -> None:
    sandbox("false")

    notifier.handler(reply(text="x" * 5000), None)

    assert len(fakes.whatsapp[0]["message"]["text"]["body"]) == 4096


def test_same_idempotency_key_sends_once(fakes: Fakes) -> None:
    sandbox("false")

    results = [notifier.handler(reply(), None) for _ in range(2)]

    assert [r["status"] for r in results] == ["SENT", "DUPLICATE"]
    assert len(fakes.whatsapp) == 1 and len(outgoing()) == 1


def test_failed_send_can_be_retried_with_the_same_key(fakes: Fakes) -> None:
    sandbox("false")
    fakes.fail = True
    with pytest.raises(RuntimeError):
        notifier.handler(reply(), None)
    assert outgoing() == []

    fakes.fail = False
    assert notifier.handler(reply(), None) == {"status": "SENT"}  # E-09: retry, no duplicate record
    assert len(outgoing()) == 1


def test_whatsapp_text_outside_the_24h_window_is_refused(fakes: Fakes) -> None:
    sandbox("false")
    conversation(CONV, lastWhatsappInboundAt="2020-01-01T00:00:00.000Z")

    with pytest.raises(ChannelUnavailableError):  # templates arrive with T-29 (F-11.C2)
        notifier.handler(reply(), None)

    assert fakes.whatsapp == [] and outgoing() == []


def test_unset_phone_number_is_a_channel_error(fakes: Fakes) -> None:
    sandbox("false")
    boto3.client("ssm").put_parameter(
        Name="/suppliagent/test/waPhoneNumberId", Value="UNSET", Type="String", Overwrite=True
    )

    with pytest.raises(ChannelUnavailableError):
        notifier.handler(reply(), None)


def test_email_conversation_is_answered_by_email_in_the_contacts_language(fakes: Fakes) -> None:
    sandbox("false")
    conversation(
        CONV,
        lastInboundChannel="EMAIL",
        lastInboundFrom="ordini@forno.example.com",
        lastInboundLocale="en-GB",
        lastWhatsappInboundAt=None,
    )

    notifier.handler(reply(), None)

    [email] = fakes.emails
    assert email["FromEmailAddress"] == "ordine@ordini.example.com"
    assert email["Destination"] == {"ToAddresses": ["ordini@forno.example.com"]}
    assert email["Content"]["Simple"]["Subject"]["Data"] == "Your request"
    assert email["Content"]["Simple"]["Body"]["Text"]["Data"] == "Ciao Anna!"
    assert email["ConfigurationSetName"] == "suppliagent-test"
    assert fakes.whatsapp == []


def test_conversation_without_a_verified_sender_gets_no_reply(fakes: Fakes) -> None:
    sandbox("false")
    conversation(OTHER, lastInboundChannel=None, lastInboundFrom=None)  # unverified email only

    with pytest.raises(AccessDeniedError):
        notifier.handler(reply(conv=OTHER), None)

    with pytest.raises(AccessDeniedError):  # unknown conversation
        notifier.handler(reply(conv="conv_nobody"), None)
    assert fakes.whatsapp == [] and fakes.emails == []


def test_the_recipient_cannot_be_chosen_by_the_caller(fakes: Fakes) -> None:
    sandbox("false")

    with pytest.raises(ValidationError):  # negative authorization: no `to` in the contract
        notifier.handler(reply() | {"to": "+390000000000"}, None)

    assert fakes.whatsapp == []


def test_reply_needs_a_key_and_a_text(fakes: Fakes) -> None:
    with pytest.raises(InvalidInputError):
        notifier.handler({"kind": "reply", "conversationId": CONV}, None)


def test_read_receipt_marks_the_message_as_read(fakes: Fakes) -> None:
    sandbox("false")
    inbound("wamid.in1")

    result = notifier.handler(receipt("wamid.in1"), None)

    assert result == {"status": "SENT"}
    assert fakes.whatsapp[0]["message"] == {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": "wamid.in1",
    }


def test_read_receipt_for_a_message_of_another_conversation_is_denied(fakes: Fakes) -> None:
    sandbox("false")
    conversation(OTHER)
    inbound("wamid.other", conv=OTHER)

    with pytest.raises(AccessDeniedError):  # negative authorization: its key, my conversation
        notifier.handler(receipt("wamid.other") | {"tsMessageId": ts_id("wamid.other")}, None)
    with pytest.raises(AccessDeniedError):  # right key shape, nothing stored
        notifier.handler(receipt("wamid.nope"), None)
    with pytest.raises(AccessDeniedError):  # a real message id with someone else's key
        inbound("wamid.mine")
        notifier.handler(receipt("wamid.mine") | {"providerMessageId": "wamid.other"}, None)
    assert fakes.whatsapp == []


def test_read_receipt_in_sandbox_sends_nothing(fakes: Fakes) -> None:
    inbound("wamid.in1")

    result = notifier.handler(receipt("wamid.in1"), None)

    assert result == {"status": "SANDBOX"} and fakes.whatsapp == []


def test_logs_carry_neither_the_text_nor_the_address(
    fakes: Fakes, caplog: pytest.LogCaptureFixture
) -> None:
    sandbox("false")

    notifier.handler(reply(text="segreto ordine"), None)

    logs = caplog.text
    assert "reply sent" in logs
    assert "segreto ordine" not in logs and "393330000001" not in logs


def test_a_send_in_progress_is_retried_not_reported_as_duplicate(fakes: Fakes) -> None:
    sandbox("false")
    notifier._claim("turn#a#b")  # another attempt claimed the key and has not finished

    with pytest.raises(notifier.SendInProgressError):
        notifier.handler(reply(), None)

    assert fakes.whatsapp == []


def test_a_recording_failure_after_the_send_never_causes_a_second_send(
    fakes: Fakes, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox("false")

    def broken(*_args: Any) -> None:
        raise OSError("DynamoDB down")

    monkeypatch.setattr(notifier, "_record", broken)

    assert notifier.handler(reply(), None) == {"status": "SENT"}  # no exception: it did go out
    assert notifier.handler(reply(), None) == {"status": "DUPLICATE"}
    assert len(fakes.whatsapp) == 1
