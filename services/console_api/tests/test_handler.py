import json
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from console_api import handler as h
from moto import mock_aws

ORDERS: list[dict[str, Any]] = [
    {"orderId": "ord_1", "customerId": "cus_1", "repId": "rep_1", "status": "DRAFT",
     "createdAt": "2026-10-20T07:41:00Z", "updatedAt": "2026-10-20T07:42:00Z",
     "imageS3Uri": "s3://media-bucket/con_1/m1.jpg", "lines": [{"lineId": "l1"}]},
    {"orderId": "ord_2", "customerId": "cus_2", "repId": "rep_2", "status": "CONFIRMED",
     "createdAt": "2026-10-21T07:41:00Z", "updatedAt": "2026-10-21T07:42:00Z", "lines": []},
]  # fmt: skip


@pytest.fixture(autouse=True)
def aws(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("ORDERS_TABLE", "orders")
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
        yield


def call(
    path: str,
    groups: str | None,
    *,
    rep_id: str | None = None,
    query: dict[str, str] | None = None,
    order_id: str | None = None,
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
        "pathParameters": {"orderId": order_id} if order_id else None,
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
    assert ids(body) == ["ord_1", "ord_2"]


def test_list_filters_by_status() -> None:
    _, body = call("/orders", "backoffice", query={"status": "CONFIRMED"})
    assert ids(body) == ["ord_2"]


def test_list_is_a_summary_without_lines() -> None:
    _, body = call("/orders", "backoffice")
    assert all("lines" not in o for o in body["orders"])  # type: ignore[attr-defined]


def test_sales_rep_sees_only_own_portfolio() -> None:
    _, body = call("/orders", "sales_rep", rep_id="rep_1")
    assert ids(body) == ["ord_1"]


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
