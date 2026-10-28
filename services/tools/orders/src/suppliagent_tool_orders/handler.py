"""Lambda entry point for the AgentCore Gateway target `orders`."""

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from aws_lambda_powertools import Logger
from pydantic import ValidationError
from suppliagent_shared.errors import SuppliAgentError

from suppliagent_tool_orders.handoff import HandoffInput, handoff_to_human
from suppliagent_tool_orders.orders import (
    CancelOrderInput,
    ConfirmOrderInput,
    CreateOrderDraftInput,
    GetOrderStatusInput,
    ReportDeliveryIssueInput,
    RequestConfirmationInput,
    ToolInput,
    UpdateOrderDraftInput,
    cancel_order,
    confirm_order,
    create_order_draft,
    get_order_status,
    report_delivery_issue,
    request_order_confirmation,
    update_order_draft,
)

logger = Logger(service="tool-orders")

TOOLS: dict[str, tuple[type[ToolInput], Callable[[Any], dict[str, Any]]]] = {
    "create_order_draft": (CreateOrderDraftInput, create_order_draft),
    "update_order_draft": (UpdateOrderDraftInput, update_order_draft),
    "request_order_confirmation": (RequestConfirmationInput, request_order_confirmation),
    "confirm_order": (ConfirmOrderInput, confirm_order),
    "cancel_order": (CancelOrderInput, cancel_order),
    "get_order_status": (GetOrderStatusInput, get_order_status),
    "report_delivery_issue": (ReportDeliveryIssueInput, report_delivery_issue),
    "handoff_to_human": (HandoffInput, handoff_to_human),
}


def _number(value: object) -> float:
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(type(value))


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    try:
        # Gateway passes the tool arguments as the event, `<target>___<tool>` in the client context.
        name = context.client_context.custom["bedrockAgentCoreToolName"].split("___", 1)[-1]
        if name not in TOOLS:
            logger.warning("unknown tool", extra={"tool": name})
            return {"error": "UNKNOWN_TOOL"}
        model, run = TOOLS[name]
        args = model.model_validate(event)
        logger.set_correlation_id(args.caller.conversationId)
        logger.append_keys(tool=name, role=args.caller.role, contactId=args.caller.contactId)
        result = run(args)
    except ValidationError as e:
        # error locations only: the messages echo the input, which may hold PII
        logger.warning("invalid input", extra={"fields": [err["loc"] for err in e.errors()]})
        return {"error": "INVALID_INPUT"}
    except SuppliAgentError as e:
        logger.warning("tool error", extra={"code": e.code})
        return {"error": e.code}
    except Exception:
        # never let a stack trace (paths, ARNs) reach the model through the Gateway
        logger.exception("tool failed")
        return {"error": "INTERNAL_ERROR"}
    logger.info("tool ok")
    # DynamoDB numbers are Decimal: plain JSON numbers for the Gateway
    output: dict[str, Any] = json.loads(json.dumps(result, default=_number))
    return output
