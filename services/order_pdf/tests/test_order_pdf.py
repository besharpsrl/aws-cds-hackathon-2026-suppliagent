"""Order PDF (T-07, FN-14): valid file with the order data, stable S3 key, EventBridge or direct."""

import re
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from moto import mock_aws
from order_pdf import handler as pdf_handler
from order_pdf.pdf import render_order_pdf
from suppliagent_shared.aws import reset_clients
from suppliagent_shared.errors import InvalidInputError, NotFoundError

BUCKET = "suppliagent-test-documents"

ORDER: dict[str, Any] = {
    "orderId": "ord_001",
    "customerId": "cus_001",
    "status": "CONFIRMED",
    "deliveryDate": "2026-10-29",
    "deliveryNotes": "Leave at the back (entrance on the left)",
    "lines": [
        {"sku": "LAT-0142", "name": "Mozzarella fior di latte 1 kg", "quantity": 3, "unit": "kg"},
        {"sku": "OLI-0007", "name": "Olio EVO è (5 L)", "quantity": 2, "unit": "pz"},
    ],
}


def check_structure(pdf: bytes) -> None:
    """Header, trailer and every xref offset points to its object."""
    assert pdf.startswith(b"%PDF-1.4")
    assert pdf.rstrip().endswith(b"%%EOF")
    xref_at = int(re.search(rb"startxref\n(\d+)\n%%EOF", pdf).group(1))  # type: ignore[union-attr]
    assert pdf[xref_at : xref_at + 4] == b"xref"
    entries = re.findall(rb"(\d{10}) 00000 n \n", pdf)
    assert entries
    for number, offset in enumerate(entries, start=1):
        assert pdf[int(offset) :].startswith(f"{number} 0 obj".encode())


def test_pdf_is_structurally_valid_and_carries_the_order() -> None:
    pdf = render_order_pdf(ORDER)
    check_structure(pdf)
    for text in (b"ord_001", b"2026-10-29", b"LAT-0142", b"Mozzarella", b"3 kg", b"Leave at"):
        assert text in pdf


def test_special_characters_are_escaped_and_encoded() -> None:
    pdf = render_order_pdf(ORDER)
    assert b"back \\(entrance on the left\\)" in pdf
    assert "è".encode("cp1252") in pdf


def test_unencodable_characters_become_question_marks() -> None:
    pdf = render_order_pdf({**ORDER, "deliveryNotes": "ring 中 twice"})
    assert b"ring ? twice" in pdf


def test_long_orders_paginate() -> None:
    lines = [{"sku": f"SKU-{i:04d}", "name": "x", "quantity": 1, "unit": "pz"} for i in range(120)]
    pdf = render_order_pdf({**ORDER, "lines": lines})
    check_structure(pdf)
    assert len(re.findall(rb"/Type /Page\b", pdf)) >= 3
    assert b"SKU-0119" in pdf


def test_line_without_name_falls_back_to_raw_text() -> None:
    pdf = render_order_pdf(
        {**ORDER, "lines": [{"sku": "X-1", "rawText": "mozz fdl", "quantity": 1, "unit": "kg"}]}
    )
    assert b"mozz fdl" in pdf


@pytest.fixture
def aws(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name, value in {
        "AWS_DEFAULT_REGION": "eu-west-1",
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "TABLE_PREFIX": "suppliagent-test-",
        "DOCUMENTS_BUCKET": BUCKET,
    }.items():
        monkeypatch.setenv(name, value)
    with mock_aws():
        reset_clients()
        pdf_handler._s3.cache_clear()
        resource: Any = boto3.resource("dynamodb")
        resource.create_table(
            TableName="suppliagent-test-orders",
            KeySchema=[{"AttributeName": "orderId", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "orderId", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        resource.Table("suppliagent-test-orders").put_item(Item=ORDER)
        boto3.client("s3").create_bucket(
            Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": "eu-west-1"}
        )
        yield


@pytest.mark.usefixtures("aws")
def test_direct_invocation_stores_the_pdf_under_a_stable_key() -> None:
    result = pdf_handler.handler({"orderId": "ord_001"}, None)
    assert result == {"s3Uri": f"s3://{BUCKET}/orders/ord_001.pdf"}
    body = boto3.client("s3").get_object(Bucket=BUCKET, Key="orders/ord_001.pdf")["Body"].read()
    check_structure(body)
    assert pdf_handler.handler({"orderId": "ord_001"}, None) == result  # regenerated in place


@pytest.mark.usefixtures("aws")
def test_eventbridge_order_confirmed_is_handled() -> None:
    event = {"detail-type": "order.confirmed", "detail": {"orderId": "ord_001"}}
    assert pdf_handler.handler(event, None)["s3Uri"].endswith("orders/ord_001.pdf")


@pytest.mark.usefixtures("aws")
def test_unknown_order_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        pdf_handler.handler({"orderId": "ord_nope"}, None)


@pytest.mark.usefixtures("aws")
@pytest.mark.parametrize("event", [{}, {"orderId": 5}, {"orderId": "../x"}])
def test_bad_request_is_rejected(event: dict[str, Any]) -> None:
    with pytest.raises(InvalidInputError):
        pdf_handler.handler(event, None)
