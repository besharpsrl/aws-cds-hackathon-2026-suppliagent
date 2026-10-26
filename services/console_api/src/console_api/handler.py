"""Console REST API (T-60): read-only orders for the back-office console (FN-28).

Role comes from the Cognito authorizer claims, never from the request body (AGENTS.md §7).
`backoffice` and `judge` read everything; `sales_rep` is limited to its own portfolio (`repId`).
"""

import json
import os
import re
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

READ_ALL_ROLES = {"backoffice", "judge"}
WRITE_ROLES = {"backoffice", "sales_rep"}
SUMMARY_FIELDS = ("orderId", "customerId", "repId", "status", "createdAt", "updatedAt")
HEADERS = {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}
# ponytail: one page of 100, no pagination; add LastEvaluatedKey paging if the demo outgrows it.
PAGE_SIZE = 100


def _json_default(value: object) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(type(value))


def _response(status: int, body: dict[str, object]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": HEADERS,
        "body": json.dumps(body, default=_json_default),
    }


def _groups(claims: dict[str, str]) -> set[str]:
    # REST API authorizers render array claims as "[a b]" or "a,b".
    return {g for g in re.split(r"[\s,\[\]]+", claims.get("cognito:groups", "")) if g}


def _table() -> Any:
    return boto3.resource("dynamodb").Table(os.environ["ORDERS_TABLE"])


def _list_orders(groups: set[str], claims: dict[str, str], status: str | None) -> dict[str, Any]:
    table = _table()
    if groups & READ_ALL_ROLES:
        if status:
            res = table.query(
                IndexName="by-status",
                KeyConditionExpression=Key("status").eq(status),
                ScanIndexForward=False,
                Limit=PAGE_SIZE,
            )
        else:
            res = table.scan(Limit=PAGE_SIZE)
        items = res["Items"]
    else:
        rep_id = claims.get("custom:repId")
        if not rep_id:
            return _response(403, {"error": "forbidden"})
        res = table.query(
            IndexName="by-repId", KeyConditionExpression=Key("repId").eq(rep_id), Limit=PAGE_SIZE
        )
        items = [i for i in res["Items"] if not status or i.get("status") == status]
    orders = [{k: i[k] for k in SUMMARY_FIELDS if k in i} for i in items]
    orders.sort(key=lambda o: o.get("createdAt", ""), reverse=True)
    return _response(200, {"orders": orders})


def _image_url(order: dict[str, Any]) -> str | None:
    uri = order.get("imageS3Uri")
    if not uri:
        return None
    bucket, _, key = uri.removeprefix("s3://").partition("/")
    url: str = boto3.client("s3").generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=int(os.environ.get("IMAGE_URL_TTL_SECONDS", "300")),
    )
    return url


def _get_order(groups: set[str], claims: dict[str, str], order_id: str) -> dict[str, Any]:
    order = _table().get_item(Key={"orderId": order_id}).get("Item")
    rep_id = claims.get("custom:repId")
    allowed = bool(groups & READ_ALL_ROLES) or bool(
        rep_id and order and order.get("repId") == rep_id
    )
    # Same answer for "missing" and "not yours": do not reveal other reps' order ids.
    if not order or not allowed:
        return _response(404, {"error": "not_found"})
    return _response(200, {"order": order, "imageUrl": _image_url(order)})


def handler(event: dict[str, Any], _context: object) -> dict[str, Any]:
    claims: dict[str, str] = event["requestContext"]["authorizer"]["claims"]
    groups = _groups(claims)
    if not groups & (READ_ALL_ROLES | {"sales_rep"}):
        return _response(403, {"error": "forbidden"})
    if event["httpMethod"] != "GET":
        # `judge` is read-only (FN-28): refused before routing, no write endpoint can skip it.
        if not groups & WRITE_ROLES:
            return _response(403, {"error": "read_only"})
        return _response(405, {"error": "method_not_allowed"})
    resource = event["resource"]
    if resource == "/orders":
        query = event.get("queryStringParameters") or {}
        return _list_orders(groups, claims, query.get("status"))
    if resource == "/orders/{orderId}":
        return _get_order(groups, claims, event["pathParameters"]["orderId"])
    return _response(404, {"error": "not_found"})
