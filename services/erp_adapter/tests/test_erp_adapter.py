"""ERP adapter mock (T-07, FN-13, F-07.C6, E-08): numbering, idempotency, retry, delivery."""

from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from aws_lambda_powertools.utilities import parameters
from erp_adapter import handler as erp
from erp_adapter.adapter import ErpAdapter, MockErpAdapter, erp_number
from moto import mock_aws
from suppliagent_shared.aws import reset_clients
from suppliagent_shared.errors import ErpUnavailableError, InvalidInputError, NotFoundError

FAILURE_PARAM = "/suppliagent/test/erpMockFailure"


class Bus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def put_event(self, _source: str, detail_type: str, detail: dict[str, Any]) -> None:
        self.events.append((detail_type, detail))


@pytest.fixture(autouse=True)
def aws(monkeypatch: pytest.MonkeyPatch) -> Iterator[Bus]:
    for name, value in {
        "AWS_DEFAULT_REGION": "eu-west-1",
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "TABLE_PREFIX": "suppliagent-test-",
        "EVENT_BUS_NAME": "suppliagent-test-events",
        "ERP_FAILURE_PARAM": FAILURE_PARAM,
    }.items():
        monkeypatch.setenv(name, value)
    bus = Bus()
    monkeypatch.setattr("erp_adapter.adapter.put_event", bus.put_event)
    with mock_aws():
        reset_clients()
        parameters.clear_caches()  # type: ignore[no-untyped-call]
        resource: Any = boto3.resource("dynamodb")
        for name in ("orders", "deliveries"):
            resource.create_table(
                TableName=f"suppliagent-test-{name}",
                KeySchema=[{"AttributeName": "orderId", "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": "orderId", "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
            )
        yield bus


def put_order(order_id: str = "ord_001", status: str = "CONFIRMED") -> None:
    resource: Any = boto3.resource("dynamodb")
    resource.Table("suppliagent-test-orders").put_item(
        Item={
            "orderId": order_id,
            "customerId": "cus_001",
            "status": status,
            "deliveryDate": "2026-10-29",
            "lines": [{"sku": "LAT-0142", "quantity": 3, "unit": "kg"}],
        }
    )


def order(order_id: str = "ord_001") -> dict[str, Any]:
    resource: Any = boto3.resource("dynamodb")
    item: dict[str, Any] = resource.Table("suppliagent-test-orders").get_item(
        Key={"orderId": order_id}
    )["Item"]
    return item


def set_failure(value: str) -> None:
    boto3.client("ssm").put_parameter(
        Name=FAILURE_PARAM, Value=value, Type="String", Overwrite=True
    )
    parameters.clear_caches()  # type: ignore[no-untyped-call]


def confirmed_event(order_id: str = "ord_001") -> dict[str, Any]:
    return {"detail-type": "order.confirmed", "detail": {"orderId": order_id}}


def test_mock_implements_the_interface() -> None:
    assert isinstance(MockErpAdapter(), ErpAdapter)


def test_confirmed_order_is_submitted_with_an_erp_number(aws: Bus) -> None:
    put_order()
    result = erp.handler(confirmed_event(), None)
    item = order()
    assert item["status"] == "SUBMITTED"
    assert item["erpOrderNumber"] == result["erpOrderNumber"]
    assert result["erpOrderNumber"].startswith("ERP-")
    assert ("erp.submitted", {"orderId": "ord_001", "erpOrderNumber": item["erpOrderNumber"]}) in (
        aws.events
    )
    assert any(
        t == "order.status_changed" and d["from"] == "CONFIRMED" and d["to"] == "SUBMITTED"
        for t, d in aws.events
    )


def test_number_is_stable_per_order_and_distinct_across_orders() -> None:
    put_order("ord_001")
    put_order("ord_002")
    a = erp.handler(confirmed_event("ord_001"), None)["erpOrderNumber"]
    b = erp.handler(confirmed_event("ord_002"), None)["erpOrderNumber"]
    assert a != b
    assert erp_number("ord_001") == a


def test_duplicate_event_does_not_submit_twice(aws: Bus) -> None:
    put_order()
    first = erp.handler(confirmed_event(), None)
    aws.events.clear()
    second = erp.handler(confirmed_event(), None)
    assert second["erpOrderNumber"] == first["erpOrderNumber"]
    assert aws.events == []  # no second erp.submitted / status change


def test_erp_down_keeps_order_confirmed_and_raises_for_retry(aws: Bus) -> None:
    put_order()
    set_failure("true")
    with pytest.raises(ErpUnavailableError):
        erp.handler(confirmed_event(), None)
    assert order()["status"] == "CONFIRMED"
    assert "erpOrderNumber" not in order()
    assert [t for t, _ in aws.events] == ["erp.failed"]
    assert aws.events[0][1] == {"orderId": "ord_001", "error": "ERP_UNAVAILABLE"}


def test_retry_after_the_erp_is_back_submits() -> None:
    put_order()
    set_failure("true")
    with pytest.raises(ErpUnavailableError):
        erp.handler(confirmed_event(), None)
    set_failure("false")
    erp.handler(confirmed_event(), None)
    assert order()["status"] == "SUBMITTED"


def test_missing_failure_parameter_means_erp_up() -> None:
    put_order()
    erp.handler(confirmed_event(), None)
    assert order()["status"] == "SUBMITTED"


@pytest.mark.parametrize("status", ["DRAFT", "PENDING_CONFIRMATION", "CANCELLED", "EXPIRED"])
def test_only_confirmed_orders_are_submitted(status: str, aws: Bus) -> None:
    put_order(status=status)
    with pytest.raises(InvalidInputError):
        erp.handler(confirmed_event(), None)
    assert order()["status"] == status
    assert aws.events == []


def test_unknown_order_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        erp.handler(confirmed_event("ord_nope"), None)


def test_delivery_progress_writes_deliveries_and_events(aws: Bus) -> None:
    put_order()
    erp.handler(confirmed_event(), None)
    aws.events.clear()
    for target in ("SCHEDULED", "OUT_FOR_DELIVERY", "DELIVERED"):
        erp.handler({"action": "advance", "orderId": "ord_001", "to": target}, None)
        assert order()["status"] == target
    resource: Any = boto3.resource("dynamodb")
    delivery = resource.Table("suppliagent-test-deliveries").get_item(Key={"orderId": "ord_001"})
    assert delivery["Item"]["date"] == "2026-10-29"
    assert delivery["Item"]["window"]
    assert [d["to"] for t, d in aws.events if t == "order.status_changed"] == [
        "SCHEDULED",
        "OUT_FOR_DELIVERY",
        "DELIVERED",
    ]


def test_delivery_cannot_skip_a_step() -> None:
    put_order()
    erp.handler(confirmed_event(), None)
    with pytest.raises(InvalidInputError):
        erp.handler({"action": "advance", "orderId": "ord_001", "to": "DELIVERED"}, None)
    assert order()["status"] == "SUBMITTED"


def test_get_order_status_by_erp_number() -> None:
    put_order()
    number = erp.handler(confirmed_event(), None)["erpOrderNumber"]
    assert MockErpAdapter().get_order_status(number) == "SUBMITTED"
    with pytest.raises(NotFoundError):
        MockErpAdapter().get_order_status("ERP-UNKNOWN")


def test_cancel_before_scheduling_and_not_after() -> None:
    put_order()
    erp.handler(confirmed_event(), None)
    MockErpAdapter().cancel_order("ord_001")
    assert order()["status"] == "CANCELLED"
    put_order("ord_002")
    erp.handler(confirmed_event("ord_002"), None)
    erp.handler({"action": "advance", "orderId": "ord_002", "to": "SCHEDULED"}, None)
    with pytest.raises(InvalidInputError):
        MockErpAdapter().cancel_order("ord_002")


def test_update_resubmits_a_submitted_order_with_the_same_number() -> None:
    put_order()
    number = erp.handler(confirmed_event(), None)["erpOrderNumber"]
    assert MockErpAdapter().update_order("ord_001").erpOrderNumber == number
    assert order()["status"] == "SUBMITTED"


def test_order_updated_resubmits_a_submitted_order_and_ignores_a_confirmed_one() -> None:
    event = {"detail-type": "order.updated", "detail": {"orderId": "ord_001"}}
    put_order()
    assert erp.handler(event, None) == {"orderId": "ord_001"}  # still CONFIRMED: nothing to do
    assert order()["status"] == "CONFIRMED"
    number = erp.handler(confirmed_event(), None)["erpOrderNumber"]
    assert erp.handler(event, None) == {"orderId": "ord_001", "erpOrderNumber": number}
    erp.handler({"action": "advance", "orderId": "ord_001", "to": "SCHEDULED"}, None)
    with pytest.raises(InvalidInputError):  # planned: no longer changeable
        erp.handler(event, None)


def test_unknown_request_is_rejected() -> None:
    with pytest.raises(InvalidInputError):
        erp.handler({"foo": "bar"}, None)
