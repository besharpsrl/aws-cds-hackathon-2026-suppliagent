"""Notifier WhatsApp templates (T-52, F-13 reorder proposal; F-12 delivery day)."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import boto3
import pytest
from aws_lambda_powertools.utilities import parameters
from moto import mock_aws
from notifier import handler as notifier
from suppliagent_shared.aws import reset_clients

TEMPLATES = Path(__file__).parents[1] / "whatsapp_templates"
SANDBOX_PARAM = "/suppliagent/test/notifierSandbox"
CONV = "conv_con001"


class Fakes:
    def __init__(self) -> None:
        self.whatsapp: list[dict[str, Any]] = []

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
    }.items():
        monkeypatch.setenv(name, value)
    fake = Fakes()
    monkeypatch.setattr(notifier, "_social", lambda: fake)
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
        boto3.client("events").create_event_bus(Name="suppliagent-test-events")
        ssm = boto3.client("ssm")
        ssm.put_parameter(Name="/suppliagent/test/waPhoneNumberId", Value="pn-1", Type="String")
        ssm.put_parameter(Name=SANDBOX_PARAM, Value="false", Type="String")
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
    assert delivery.split()[0] in notifier.DAYS["it"]
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
