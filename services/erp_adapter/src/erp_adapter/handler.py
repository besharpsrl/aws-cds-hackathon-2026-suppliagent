"""ERP adapter Lambda (T-07, FN-13). Two kinds of request:
- EventBridge `order.confirmed` (`detail.orderId`): submits the order. The order is read from
  `Orders`, never taken from the event. ERP down (E-08) raises: the order stays CONFIRMED and
  Lambda's async retries then the DLQ take over.
- `{"action": "advance", "orderId", "to"}`: demo/test trigger for the mock delivery progress
  (SCHEDULED -> OUT_FOR_DELIVERY -> DELIVERED); invoked by hand, no schedule.
"""

from typing import Any

from aws_lambda_powertools import Logger
from suppliagent_shared.errors import InvalidInputError
from suppliagent_shared.models import parse_order_id

from erp_adapter.adapter import MockErpAdapter, _get_order

logger = Logger(service="erp-adapter")


def handler(event: dict[str, Any], _context: Any) -> dict[str, str]:
    adapter = MockErpAdapter()
    if event.get("detail-type") == "order.confirmed":
        order_id = parse_order_id(event.get("detail", {}).get("orderId"))
        logger.set_correlation_id(order_id)
        result = adapter.submit_order(_get_order(order_id))
        return {"orderId": order_id, "erpOrderNumber": result.erpOrderNumber}
    if event.get("action") == "advance":
        order_id = parse_order_id(event.get("orderId"))
        logger.set_correlation_id(order_id)
        to = event.get("to")
        if not isinstance(to, str):
            raise InvalidInputError
        adapter.advance(order_id, to)
        return {"orderId": order_id, "status": to}
    raise InvalidInputError
