"""Lambda entry point for the AgentCore Gateway target `inventory-pricing`."""

import json
from collections.abc import Callable
from typing import Any

from aws_lambda_powertools import Logger
from pydantic import ValidationError
from suppliagent_shared.errors import SuppliAgentError

from suppliagent_tool_inventory_pricing.inventory import (
    CheckAvailabilityInput,
    DeliveryOptionsInput,
    GetPricesInput,
    ToolInput,
    check_availability,
    get_delivery_options,
    get_prices,
)

logger = Logger(service="tool-inventory-pricing")

TOOLS: dict[str, tuple[type[ToolInput], Callable[[Any], dict[str, Any]]]] = {
    "check_availability": (CheckAvailabilityInput, check_availability),
    "get_prices": (GetPricesInput, get_prices),
    "get_delivery_options": (DeliveryOptionsInput, get_delivery_options),
}


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
    output: dict[str, Any] = json.loads(json.dumps(result))
    return output
