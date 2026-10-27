"""Order PDF Lambda (T-07, FN-14): renders the order into `documents/orders/<orderId>.pdf`.

Invoked by EventBridge `order.confirmed` (so the PDF is ready for the email, T-26) and
`order.updated` (a change before the cut-off: the PDF is rewritten) or directly
with `{"orderId"}`. The order is read from `Orders`; the key is stable, so a repeat or a later
call after a change regenerates the file in place. Returns the `s3Uri` for the caller.

Environment: `TABLE_PREFIX`, `DOCUMENTS_BUCKET`.
"""

import os
from functools import cache
from typing import Any

import boto3
from aws_lambda_powertools import Logger
from suppliagent_shared.aws import table
from suppliagent_shared.errors import NotFoundError
from suppliagent_shared.models import parse_order_id

from order_pdf.pdf import render_order_pdf

logger = Logger(service="order-pdf")


@cache
def _s3() -> Any:
    return boto3.client("s3")


def handler(event: dict[str, Any], _context: Any) -> dict[str, str]:
    detail = (
        event["detail"]
        if event.get("detail-type") in ("order.confirmed", "order.updated")
        else event
    )
    order_id = parse_order_id(detail.get("orderId"))
    logger.set_correlation_id(order_id)
    order = table("orders").get_item(Key={"orderId": order_id}).get("Item")
    if not order:
        raise NotFoundError
    bucket = os.environ["DOCUMENTS_BUCKET"]
    key = f"orders/{order_id}.pdf"
    _s3().put_object(
        Bucket=bucket,
        Key=key,
        Body=render_order_pdf(order),
        ContentType="application/pdf",
        ServerSideEncryption="aws:kms",
    )
    return {"s3Uri": f"s3://{bucket}/{key}"}
