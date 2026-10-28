"""Handoff to the back office (FN-24, F-14): `Conversations.mode` AGENT <-> HUMAN.

The agent starts it with the `handoff_to_human` tool, an operator with *Take over* (T-63); only
*Release* from the console gives the conversation back to the agent. The Router never changes the
mode and the Dispatcher runs no turn while it is HUMAN (INFRASTRUCTURE_DESIGN §5.2, step 6).
"""

import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from botocore.exceptions import ClientError

from suppliagent_shared.aws import put_event, table
from suppliagent_shared.errors import NotFoundError

logger = logging.getLogger(__name__)


class HandoffReason(StrEnum):
    CUSTOMER_REQUEST = "CUSTOMER_REQUEST"
    IDENTIFICATION_FAILED = "IDENTIFICATION_FAILED"
    NEW_CUSTOMER = "NEW_CUSTOMER"
    UNRESOLVED_LINES = "UNRESOLVED_LINES"
    ORDER_LOCKED = "ORDER_LOCKED"
    DELIVERY_ISSUE = "DELIVERY_ISSUE"
    NEGATIVE_SENTIMENT = "NEGATIVE_SENTIMENT"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    OPERATOR_TAKEOVER = "OPERATOR_TAKEOVER"  # console only


AGENT = "AGENT"
HUMAN = "HUMAN"
NAMES = {"#mode": "mode", "#handoff": "handoff"}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _event(source: str, detail_type: str, detail: dict[str, Any]) -> None:
    """Best effort: the mode is already written, a failed event must not turn into a retry."""
    try:
        put_event(source, detail_type, detail)
    except Exception:
        logger.exception("handoff event not sent")


def start_handoff(
    source: str, conversation_id: str, reason: HandoffReason, summary: str, by: str
) -> bool:
    """Moves the conversation to HUMAN with the reason and summary shown in the console. False if
    it already was HUMAN (the first handoff is kept); `NotFoundError` if it does not exist."""
    try:
        table("conversations").update_item(
            Key={"conversationId": conversation_id},
            UpdateExpression="SET #mode = :human, #handoff = :handoff",
            ConditionExpression=(
                "attribute_exists(conversationId)"
                " AND (attribute_not_exists(#mode) OR #mode <> :human)"
            ),
            ExpressionAttributeNames=NAMES,
            ExpressionAttributeValues={
                ":human": HUMAN,
                ":handoff": {"reason": reason, "summary": summary, "by": by, "at": _now()},
            },
            ReturnValuesOnConditionCheckFailure="ALL_OLD",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        if "Item" not in e.response:
            raise NotFoundError from e
        return False
    _event(
        source,
        "handoff.started",
        {"conversationId": conversation_id, "reason": reason, "by": by},
    )
    return True


def release_handoff(source: str, conversation_id: str, by: str) -> bool:
    """*Release*: back to AGENT. False if the conversation was not HUMAN."""
    try:
        response = table("conversations").update_item(
            Key={"conversationId": conversation_id},
            UpdateExpression="SET #mode = :agent, releasedAt = :now REMOVE #handoff",
            ConditionExpression="#mode = :human",
            ExpressionAttributeNames=NAMES,
            ExpressionAttributeValues={":agent": AGENT, ":human": HUMAN, ":now": _now()},
            ReturnValues="ALL_OLD",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        return False
    old: dict[str, Any] = response["Attributes"].get("handoff", {})
    _event(
        source,
        "handoff.released",
        {"conversationId": conversation_id, "reason": old.get("reason"), "by": by},
    )
    return True
