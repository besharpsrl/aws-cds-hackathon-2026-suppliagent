import json
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import boto3
import pytest
from console_api import handler as h
from moto import mock_aws

CANDIDATES = [{"sku": "PAN-0100", "name": "Pane 6 pz"}, {"sku": "PAN-0101", "name": "Pane XL"}]
ORDERS: list[dict[str, Any]] = [
    {"orderId": "ord_1", "customerId": "cus_1", "repId": "rep_1", "status": "NEEDS_CLARIFICATION",
     "createdAt": "2026-10-20T07:41:00Z", "updatedAt": "2026-10-20T07:42:00Z",
     "imageS3Uri": "s3://media-bucket/con_1/m1.jpg", "conversationId": "conv_1", "version": 0,
     "total": Decimal("10.00"),
     "lines": [
         {"lineId": "l1", "status": "MATCHED", "rawText": "burro", "sku": "BUR-1",
          "name": "Burro", "quantity": Decimal(2), "unit": "kg",
          "unitPrice": Decimal("5.00"), "lineTotal": Decimal("10.00")},
         {"lineId": "l2", "status": "AMBIGUOUS", "rawText": "pane", "quantity": Decimal(20),
          "candidates": CANDIDATES},
         {"lineId": "l3", "status": "UNMATCHED", "rawText": "???", "candidates": []},
         {"lineId": "l4", "status": "REMOVED", "rawText": "old"},
     ]},
    {"orderId": "ord_2", "customerId": "cus_2", "repId": "rep_2", "status": "CONFIRMED",
     "createdAt": "2026-10-21T07:41:00Z", "updatedAt": "2026-10-21T07:42:00Z", "lines": [],
     "version": 3},
    {"orderId": "ord_3", "customerId": "cus_1", "repId": "rep_1", "status": "NEEDS_CLARIFICATION",
     "createdAt": "2026-10-22T07:41:00Z", "updatedAt": "2026-10-22T07:42:00Z", "version": 0,
     "conversationId": "conv_3", "total": Decimal(0),
     "lines": [{"lineId": "l1", "status": "AMBIGUOUS", "candidates": CANDIDATES}]},
]  # fmt: skip
MESSAGES: list[dict[str, Any]] = [
    {"conversationId": "conv_3", "tsMessageId": "2026-10-22T07:40:00.000Z#m0", "messageId": "m0",
     "direction": "INBOUND", "attachments": [{"type": "audio", "s3Uri": "s3://media-bucket/a.ogg"}]},
    {"conversationId": "conv_3", "tsMessageId": "2026-10-22T07:41:00.000Z#m1", "messageId": "m1",
     "direction": "INBOUND", "attachments": [{"type": "image", "s3Uri": "s3://media-bucket/b.jpg"}]},
]  # fmt: skip


KEY_TYPES = ("HASH", "RANGE")


def _create(ddb: Any, name: str, keys: tuple[str, ...], index: str | None = None) -> Any:
    attrs = {*keys, *([index] if index else [])}
    return ddb.create_table(
        TableName=name,
        BillingMode="PAY_PER_REQUEST",
        KeySchema=[
            {"AttributeName": k, "KeyType": t} for k, t in zip(keys, KEY_TYPES, strict=False)
        ],
        AttributeDefinitions=[{"AttributeName": a, "AttributeType": "S"} for a in attrs],
        **(
            {
                "GlobalSecondaryIndexes": [
                    {"IndexName": f"by-{index}", "Projection": {"ProjectionType": "ALL"},
                     "KeySchema": [{"AttributeName": index, "KeyType": "HASH"}]}
                ]
            }
            if index
            else {}
        ),
    )  # fmt: skip


@pytest.fixture(autouse=True)
def aws(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    for env, name in (
        ("ORDERS_TABLE", "orders"),
        ("CUSTOMERS_TABLE", "customers"),
        ("CONVERSATIONS_TABLE", "conversations"),
        ("MESSAGES_TABLE", "messages"),
        ("PRODUCTS_TABLE", "products"),
        ("PRICE_LISTS_TABLE", "price-lists"),
        ("PROMOTIONS_TABLE", "promotions"),
    ):
        monkeypatch.setenv(env, name)
    monkeypatch.setenv("EVENT_BUS_NAME", "bus")
    monkeypatch.setenv("IMAGE_URL_TTL_SECONDS", "300")
    with mock_aws():
        ddb = boto3.resource("dynamodb")
        table = ddb.create_table(
            TableName="orders",
            BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "orderId", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": n, "AttributeType": "S"}
                for n in ("orderId", "status", "updatedAt", "repId")
            ],
            GlobalSecondaryIndexes=[
                {"IndexName": "by-status", "Projection": {"ProjectionType": "ALL"},
                 "KeySchema": [{"AttributeName": "status", "KeyType": "HASH"},
                               {"AttributeName": "updatedAt", "KeyType": "RANGE"}]},
                {"IndexName": "by-repId", "Projection": {"ProjectionType": "ALL"},
                 "KeySchema": [{"AttributeName": "repId", "KeyType": "HASH"}]},
            ],
        )  # fmt: skip
        for order in ORDERS:
            table.put_item(Item=order)
        customers = _create(ddb, "customers", ("customerId",))
        customers.put_item(Item={"customerId": "cus_1", "venueName": "Pizzeria Uno",
                                 "priceListId": "LIST"})  # fmt: skip
        _create(ddb, "conversations", ("conversationId",)).put_item(
            Item={"conversationId": "conv_1", "mode": "HUMAN"}
        )
        messages = _create(ddb, "messages", ("conversationId", "tsMessageId"))
        for message in MESSAGES:
            messages.put_item(Item=message)
        products = _create(ddb, "products", ("sku",))
        products.put_item(
            Item={"sku": "PAN-0100", "name": "Pane 6 pz", "unit": "pz", "active": True}
        )
        products.put_item(
            Item={"sku": "PAN-0101", "name": "Pane XL", "unit": "pz", "active": False}
        )
        _create(ddb, "price-lists", ("priceListId", "sku")).put_item(
            Item={"priceListId": "LIST", "sku": "PAN-0100", "price": "2.00"}
        )
        promotions = _create(ddb, "promotions", ("promoId",), index="sku")
        promotions.put_item(Item={"promoId": "p1", "sku": "PAN-0100", "promoPrice": "1.50",
                                  "validFrom": "2000-01-01", "validTo": "2999-12-31"})  # fmt: skip
        promotions.put_item(Item={"promoId": "p2", "sku": "PAN-0100", "promoPrice": "0.10",
                                  "validFrom": "2000-01-01", "validTo": "2000-12-31"})  # fmt: skip
        yield


def call(
    path: str,
    groups: str | None,
    *,
    rep_id: str | None = None,
    query: dict[str, str] | None = None,
    order_id: str | None = None,
    line_id: str | None = None,
    body: object = None,
    method: str = "GET",
) -> tuple[int, dict[str, object]]:
    claims: dict[str, str] = {}
    if groups is not None:
        claims["cognito:groups"] = groups
    if rep_id:
        claims["custom:repId"] = rep_id
    event = {
        "httpMethod": method,
        "resource": path,
        "pathParameters": (
            {"orderId": order_id, **({"lineId": line_id} if line_id else {})} if order_id else None
        ),
        "body": json.dumps(body) if body is not None else None,
        "queryStringParameters": query,
        "requestContext": {"authorizer": {"claims": claims}},
    }
    res = h.handler(event, None)
    return res["statusCode"], json.loads(res["body"])


def ids(body: dict[str, object]) -> list[str]:
    return sorted(o["orderId"] for o in body["orders"])  # type: ignore[attr-defined]


@pytest.mark.parametrize("group", ["backoffice", "judge", "[judge backoffice]"])
def test_backoffice_and_judge_list_all_orders(group: str) -> None:
    status, body = call("/orders", group)
    assert status == 200
    assert ids(body) == ["ord_1", "ord_2", "ord_3"]


def test_list_filters_by_status() -> None:
    _, body = call("/orders", "backoffice", query={"status": "CONFIRMED"})
    assert ids(body) == ["ord_2"]


def test_list_is_a_summary_without_lines() -> None:
    _, body = call("/orders", "backoffice")
    assert all("lines" not in o for o in body["orders"])  # type: ignore[attr-defined]


def test_sales_rep_sees_only_own_portfolio() -> None:
    _, body = call("/orders", "sales_rep", rep_id="rep_1")
    assert ids(body) == ["ord_1", "ord_3"]


def test_sales_rep_cannot_read_another_reps_order() -> None:
    status, _ = call("/orders/{orderId}", "sales_rep", rep_id="rep_1", order_id="ord_2")
    assert status == 404


def test_sales_rep_without_rep_id_is_denied() -> None:
    assert call("/orders", "sales_rep")[0] == 403


@pytest.mark.parametrize("groups", [None, "", "other"])
def test_unknown_role_is_denied(groups: str | None) -> None:
    assert call("/orders", groups)[0] == 403
    assert call("/orders/{orderId}", groups, order_id="ord_1")[0] == 403


def test_detail_returns_presigned_image_url() -> None:
    status, body = call("/orders/{orderId}", "judge", order_id="ord_1")
    assert status == 200
    assert body["order"]["orderId"] == "ord_1"  # type: ignore[index]
    assert "media-bucket" in str(body["imageUrl"]) and "Signature" in str(body["imageUrl"])


def test_detail_without_image_has_null_url() -> None:
    _, body = call("/orders/{orderId}", "backoffice", order_id="ord_2")
    assert body["imageUrl"] is None


def test_missing_order_is_404() -> None:
    assert call("/orders/{orderId}", "backoffice", order_id="ord_x")[0] == 404


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_judge_is_read_only_whatever_the_endpoint(method: str) -> None:
    # FN-28/FN-31: the judge role never writes; denied before routing, so future write endpoints
    # (T-46 corrections) cannot forget the check.
    for path, order_id in (("/orders", None), ("/orders/{orderId}", "ord_1")):
        assert call(path, "judge", order_id=order_id, method=method)[0] == 403


def test_judge_with_a_write_group_is_not_read_only() -> None:
    # Groups are additive: a user who is also backoffice is not blocked by the judge rule.
    assert call("/orders", "[judge backoffice]", method="POST")[0] == 405


def test_non_get_is_not_allowed_for_other_roles_yet() -> None:
    assert call("/orders", "backoffice", method="PATCH")[0] == 405


LINE = "/orders/{orderId}/lines/{lineId}"


def order_of(body: dict[str, Any]) -> dict[str, Any]:
    order: dict[str, Any] = body["order"]
    return order


def stored(order_id: str) -> dict[str, Any]:
    item: dict[str, Any] = (
        boto3.resource("dynamodb").Table("orders").get_item(Key={"orderId": order_id})["Item"]
    )
    return item


def correct(
    groups: str, order_id: str = "ord_1", line_id: str = "l2", **kwargs: Any
) -> tuple[int, dict[str, Any]]:
    status, body = call(LINE, groups, order_id=order_id, line_id=line_id, method="PATCH", **kwargs)
    return status, body


def test_list_has_customer_name_uncertain_lines_and_handoff() -> None:
    _, body = call("/orders", "backoffice")
    by_id = {o["orderId"]: o for o in body["orders"]}  # type: ignore[attr-defined]
    assert by_id["ord_1"]["customerName"] == "Pizzeria Uno"
    assert by_id["ord_1"]["uncertainLines"] == 2  # REMOVED and MATCHED lines do not count
    assert by_id["ord_1"]["handoff"] is True
    assert by_id["ord_3"]["handoff"] is False
    assert "customerName" not in by_id["ord_2"]  # customer not found: UI falls back to the id


def test_detail_lines_follow_the_console_contract() -> None:
    _, body = call("/orders/{orderId}", "judge", order_id="ord_1")
    order = order_of(body)
    assert order["customerName"] == "Pizzeria Uno"
    assert order["source"] == "text"
    assert [x["lineId"] for x in order["lines"]] == ["l1", "l2", "l3"]  # REMOVED hidden
    ambiguous = order["lines"][1]
    assert ambiguous["imageRegion"] is None and ambiguous["correctedBy"] is None
    assert ambiguous["candidates"][0] == {
        "sku": "PAN-0100", "name": "Pane 6 pz", "confidence": 0, "boughtBefore": False,
    }  # fmt: skip


def test_detail_image_comes_from_the_conversation_when_the_order_has_none() -> None:
    _, body = call("/orders/{orderId}", "backoffice", order_id="ord_3")
    url = str(body["imageUrl"])  # the image, not the earlier voice note
    assert "media-bucket.s3" in url and "/b.jpg?" in url
    assert "X-Amz-Algorithm=AWS4-HMAC-SHA256" in url  # SSE-KMS objects need SigV4


def test_correction_matches_the_line_prices_it_and_updates_the_order() -> None:
    status, body = correct("backoffice", body={"sku": "PAN-0100"})
    assert status == 200
    line = order_of(body)["lines"][1]
    assert (line["status"], line["sku"], line["name"], line["correctedBy"]) == (
        "MATCHED", "PAN-0100", "Pane 6 pz", "backoffice",
    )  # fmt: skip
    item = stored("ord_1")
    saved = item["lines"][1]
    assert (saved["quantity"], saved["unitPrice"], saved["lineTotal"]) == (20, Decimal("1.50"), 30)
    assert item["total"] == Decimal("40.00")  # 10.00 + 30.00: only the valid promotion counts
    assert item["status"] == "NEEDS_CLARIFICATION"  # l3 is still UNMATCHED
    assert item["version"] == 1 and item["updatedAt"] > "2026-10-20T07:42:00Z"


def test_correcting_the_last_uncertain_line_moves_the_order_to_draft() -> None:
    assert correct("backoffice", "ord_3", "l1", body={"sku": "PAN-0100", "quantity": 3})[0] == 200
    item = stored("ord_3")
    assert (item["status"], item["total"]) == ("DRAFT", Decimal("4.50"))


def test_correction_needs_a_quantity() -> None:
    status, body = correct("backoffice", "ord_3", "l1", body={"sku": "PAN-0100"})
    assert (status, body["error"]) == (400, "quantity_required")


@pytest.mark.parametrize("quantity", [0, -1, "3", True, 100001])
def test_correction_rejects_a_bad_quantity(quantity: object) -> None:
    status, body = correct(
        "backoffice", "ord_3", "l1", body={"sku": "PAN-0100", "quantity": quantity}
    )
    assert (status, body["error"]) == (400, "invalid_body")


@pytest.mark.parametrize("sku", ["PAN-9999", "BUR-1", "PAN-0101"])
def test_correction_only_accepts_active_candidates_of_the_line(sku: str) -> None:
    # not a candidate, a SKU of another line, a candidate that is no longer active
    status, body = correct("backoffice", body={"sku": sku})
    assert (status, body["error"]) == (400, "invalid_sku")
    assert stored("ord_1")["version"] == 0


@pytest.mark.parametrize("payload", [None, "x", {}, {"sku": 3}])
def test_correction_rejects_a_bad_body(payload: object) -> None:
    status, body = correct("backoffice", body=payload)
    assert (status, body["error"]) == (400, "invalid_body")


def test_correction_of_a_confirmed_order_is_refused() -> None:
    assert correct("backoffice", "ord_2", "l1", body={"sku": "PAN-0100"})[0] == 409


def test_correction_of_a_missing_line_or_order_is_404() -> None:
    assert correct("backoffice", line_id="l9", body={"sku": "PAN-0100"})[0] == 404
    assert correct("backoffice", line_id="l4", body={"sku": "PAN-0100"})[0] == 404  # REMOVED
    assert correct("backoffice", "ord_x", body={"sku": "PAN-0100"})[0] == 404


def test_correction_loses_against_a_concurrent_change(monkeypatch: pytest.MonkeyPatch) -> None:
    stale = stored("ord_1")
    boto3.resource("dynamodb").Table("orders").update_item(
        Key={"orderId": "ord_1"},
        UpdateExpression="SET version = :v",
        ExpressionAttributeValues={":v": 1},
    )
    monkeypatch.setattr(h, "_visible_order", lambda *_, **__: stale)  # read before the other write
    status, body = correct("backoffice", body={"sku": "PAN-0100"})
    assert (status, body["error"]) == (409, "conflict")
    assert stored("ord_1")["lines"][1]["status"] == "AMBIGUOUS"


def test_judge_cannot_correct() -> None:
    assert correct("judge", body={"sku": "PAN-0100"})[0] == 403
    assert stored("ord_1")["lines"][1]["status"] == "AMBIGUOUS"


def test_sales_rep_corrects_only_own_portfolio() -> None:
    assert correct("sales_rep", rep_id="rep_2", body={"sku": "PAN-0100"})[0] == 404
    assert stored("ord_1")["version"] == 0
    status, body = correct("sales_rep", rep_id="rep_1", body={"sku": "PAN-0100"})
    assert status == 200
    assert order_of(body)["lines"][1]["correctedBy"] == "rep"


def test_sales_rep_without_rep_id_cannot_correct() -> None:
    assert correct("sales_rep", body={"sku": "PAN-0100"})[0] == 404


def test_other_methods_on_the_line_are_not_allowed() -> None:
    status, _ = call(LINE, "backoffice", order_id="ord_1", line_id="l2", method="DELETE")
    assert status == 405


def test_judge_who_is_also_sales_rep_writes_only_in_own_portfolio() -> None:
    # Reading all orders is the judge's; writing is not: groups are additive but not for this.
    assert correct("[judge sales_rep]", rep_id="rep_2", body={"sku": "PAN-0100"})[0] == 404
    assert stored("ord_1")["version"] == 0
    assert correct("[judge sales_rep]", rep_id="rep_1", body={"sku": "PAN-0100"})[0] == 200
