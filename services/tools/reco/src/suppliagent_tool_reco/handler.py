"""Lambda entry point for the AgentCore Gateway target `reco`."""

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from aws_lambda_powertools import Logger
from pydantic import ValidationError
from suppliagent_shared.errors import SuppliAgentError

from suppliagent_tool_reco.reco import (
    OutcomeInput,
    RecommendInput,
    ToolInput,
    recommend_products,
    record_suggestion_outcome,
)

logger = Logger(service="tool-reco")

TOOLS: dict[str, tuple[type[ToolInput], Callable[[Any], dict[str, Any]]]] = {
    "recommend_products": (RecommendInput, recommend_products),
    "record_suggestion_outcome": (OutcomeInput, record_suggestion_outcome),
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
