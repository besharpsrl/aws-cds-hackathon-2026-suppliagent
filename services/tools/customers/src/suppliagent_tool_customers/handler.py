"""Lambda entry point for the AgentCore Gateway target `customers`."""

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from aws_lambda_powertools import Logger
from pydantic import ValidationError
from suppliagent_shared.errors import SuppliAgentError

from suppliagent_tool_customers.customers import (
    GetCustomerProfileInput,
    IdentifyContactInput,
    ToolInput,
    UpdatePrivacyInput,
    get_customer_profile,
    identify_contact,
    update_privacy,
)

logger = Logger(service="tool-customers")

TOOLS: dict[str, tuple[type[ToolInput], Callable[[Any], dict[str, Any]]]] = {
    "identify_contact": (IdentifyContactInput, identify_contact),
    "get_customer_profile": (GetCustomerProfileInput, get_customer_profile),
    "update_privacy": (UpdatePrivacyInput, update_privacy),
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
        # never let a stack trace (paths, table names) reach the model through the Gateway
        logger.exception("tool failed")
        return {"error": "INTERNAL_ERROR"}
    logger.info("tool ok")
    output: dict[str, Any] = json.loads(json.dumps(result, default=_number))
    return output


def _number(value: Any) -> int | float:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(type(value).__name__)
