"""`handoff_to_human` (FN-24, F-14): the agent hands its conversation to the back office."""

from typing import Any

from pydantic import Field
from suppliagent_shared.errors import InvalidInputError
from suppliagent_shared.handoff import HandoffReason, start_handoff

from suppliagent_tool_orders.orders import ToolInput

SOURCE = "suppliagent.tool-orders"
AGENT_REASONS = frozenset(HandoffReason) - {HandoffReason.OPERATOR_TAKEOVER}


class HandoffInput(ToolInput):
    reason: HandoffReason
    summary: str = Field(min_length=1, max_length=1000)


def handoff_to_human(args: HandoffInput) -> dict[str, Any]:
    """Any role, UNKNOWN included (F-02.C3/C4): the conversation is the caller's, set by the agent
    code, never chosen by the model."""
    if args.reason not in AGENT_REASONS or not args.caller.conversationId:
        raise InvalidInputError
    started = start_handoff(
        SOURCE, args.caller.conversationId, args.reason, args.summary.strip(), by="AGENT"
    )
    return {"status": "HANDED_OFF" if started else "ALREADY_HANDED_OFF"}
