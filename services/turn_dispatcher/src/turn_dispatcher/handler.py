"""Turn Dispatcher (T-22, FN-26; TECHNICAL_FLOWS §3.3).

SQS `turn-flush` (batch of 1) -> debounce -> per-conversation lock in the TurnBuffer -> one agent
turn with every pending message, in order -> reply through the Notifier -> release, re-flushing if
messages arrived during the turn.

A flush is only a "look at this conversation" nudge: any number can be in flight, and all but the
one that finds the burst over and the lock free do nothing.

Environment: `TABLE_PREFIX`, `EVENT_BUS_NAME`, `TURN_FLUSH_QUEUE_URL`, `AGENT_RUNTIME_ARN`,
`NOTIFIER_FUNCTION_NAME`, `DEBOUNCE_TEXT_MS`, `DEBOUNCE_MEDIA_MS`, `DEBOUNCE_MAX_MS`,
`TURN_LOCK_TTL_MS`.
"""

import json
import math
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Any

import boto3
from aws_lambda_powertools import Logger
from botocore.config import Config
from botocore.exceptions import ClientError
from suppliagent_shared.aws import put_event, table
from suppliagent_shared.errors import SuppliAgentError

SOURCE = "suppliagent.turn-dispatcher"
WHATSAPP_WINDOW = timedelta(hours=24)
MEDIA_TYPES = {"image", "audio", "document"}
# Notifier errors that a retry cannot fix (typed errors of `suppliagent_shared.errors`).
PERMANENT_NOTIFIER_ERRORS = {"AccessDeniedError", "ChannelUnavailableError", "InvalidInputError"}
logger = Logger(service="turn-dispatcher")


class AgentTurnError(SuppliAgentError):
    """The Runtime refused the request or the invocation failed (E-05, E-12): retried by SQS."""

    code = "AGENT_TURN_FAILED"


@cache
def _sqs() -> Any:
    return boto3.client("sqs")


@cache
def _lambda() -> Any:
    return boto3.client("lambda")


@cache
def _agent() -> Any:
    # The turn can outlast botocore's 60 s default read timeout; the Lambda timeout bounds it.
    return boto3.client(
        "bedrock-agentcore", config=Config(read_timeout=110, retries={"max_attempts": 1})
    )


def handler(event: dict[str, Any], _context: Any) -> None:
    for record in event["Records"]:
        _flush(json.loads(record["body"])["conversationId"])


def _now_ms() -> int:
    return int(time.time() * 1000)


def _flush(conversation_id: str) -> None:
    logger.set_correlation_id(conversation_id)
    item = (
        table("turn-buffer")
        .get_item(Key={"conversationId": conversation_id}, ConsistentRead=True)
        .get("Item")
    )
    if not item or not item.get("pending"):
        return
    now = _now_ms()
    due = _due_at(item["pending"])
    if now < due:  # the burst may go on: look again when it would be over
        _enqueue(conversation_id, math.ceil((due - now) / 1000))
        return
    until = now + int(os.environ["TURN_LOCK_TTL_MS"])
    locked = _acquire(conversation_id, now, until)
    if locked is None:
        # Another turn runs and re-flushes when done; this covers a crashed holder (E-11).
        remaining = int(item.get("lockUntil", now)) - now
        _enqueue(conversation_id, max(1, math.ceil(remaining / 1000)) + 1)
        return
    pending = locked.get("pending", [])
    if not pending:
        _release(conversation_id, until, 0)
        return
    try:
        conversation = (
            table("conversations")
            .get_item(Key={"conversationId": conversation_id}, ConsistentRead=True)
            .get("Item", {})
        )
        if conversation.get("mode", "AGENT") != "AGENT":
            # A handoff began after the Router queued these (FN-24): the agent stays silent. They
            # are dropped from the buffer, the operator reads them in `Messages`.
            logger.info("conversation in human mode: no turn", messages=len(pending))
        else:
            _run_turn(conversation_id, locked, pending, conversation)
    except BaseException:
        try:
            _release(conversation_id, until, 0)  # keep the messages: SQS retries the flush
        except Exception:
            logger.exception("lock not released")  # it expires by itself; keep the real error
        raise
    after = _release(conversation_id, until, len(pending))
    if after and after.get("pending"):
        # Arrived during the turn (C3): one more turn for all of them, debounced as usual.
        _enqueue(conversation_id, math.ceil(int(os.environ["DEBOUNCE_TEXT_MS"]) / 1000))


def _due_at(pending: list[dict[str, Any]]) -> int:
    """End of the burst: quiet for the debounce, but never later than `debounceMaxMs` after its
    first message (C4). Media waits longer: the user is probably still sending (C2). Arrival times
    are per message, so messages left over from a turn keep their real age."""
    media = any(a.get("type") in MEDIA_TYPES for m in pending for a in m.get("attachments", []))
    debounce = int(os.environ["DEBOUNCE_MEDIA_MS" if media else "DEBOUNCE_TEXT_MS"])
    arrivals = [int(m["at"]) for m in pending]
    return min(max(arrivals) + debounce, min(arrivals) + int(os.environ["DEBOUNCE_MAX_MS"]))


def _enqueue(conversation_id: str, delay_seconds: int) -> None:
    _sqs().send_message(
        QueueUrl=os.environ["TURN_FLUSH_QUEUE_URL"],
        MessageBody=json.dumps({"conversationId": conversation_id}),
        DelaySeconds=min(900, delay_seconds),
    )


def _acquire(conversation_id: str, now: int, until: int) -> dict[str, Any] | None:
    """Takes the lock; returns the item as it was (the messages this turn owns) or None if held.
    A holder that crashed is overtaken once `lockUntil` has passed (C5). `afterTurn` is read here
    and cleared by the release of the turn that consumed it."""
    try:
        response = table("turn-buffer").update_item(
            Key={"conversationId": conversation_id},
            UpdateExpression="SET lockUntil = :until",
            ConditionExpression=(
                "attribute_exists(pending)"
                " AND (attribute_not_exists(lockUntil) OR lockUntil < :now)"
            ),
            ExpressionAttributeValues={":until": until, ":now": now},
            ReturnValues="ALL_OLD",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return None
        raise
    attributes: dict[str, Any] = response["Attributes"]
    return attributes


def _release(conversation_id: str, until: int, drained: int) -> dict[str, Any] | None:
    """Releases our lock. With `drained` > 0 the turn is over: its first messages are removed
    (appends only go to the end, so the indexes are stable). The release is one atomic update:
    if messages are left, `afterTurn` is set in it (C3). None if the lock is no longer ours (it
    expired mid-turn). With nothing drained (a failed turn) only the lock goes."""
    if not drained:
        return _release_update(conversation_id, until, "REMOVE lockUntil", "")
    removal = ", ".join(["lockUntil", "afterTurn"] + [f"pending[{i}]" for i in range(drained)])
    leftover = _release_update(
        conversation_id,
        until,
        "SET afterTurn = :true REMOVE "
        + ", ".join(["lockUntil"] + [f"pending[{i}]" for i in range(drained)]),
        "size(pending) > :n",
        {":true": True, ":n": drained},
    )
    if leftover is not None:
        return leftover
    # Nothing left (or the lock is gone): clear the flag too. If a message slipped in between the
    # two updates it stays pending and the caller re-flushes, only `afterTurn` is missed.
    done = _release_update(conversation_id, until, "REMOVE " + removal, "")
    if done is None:
        logger.warning("lock expired during the turn")
    return done


def _release_update(
    conversation_id: str,
    until: int,
    expression: str,
    extra_condition: str,
    extra_values: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    condition = "lockUntil = :until" + (f" AND {extra_condition}" if extra_condition else "")
    try:
        response = table("turn-buffer").update_item(
            Key={"conversationId": conversation_id},
            UpdateExpression=expression,
            ConditionExpression=condition,
            ExpressionAttributeValues={":until": until} | (extra_values or {}),
            ReturnValues="ALL_NEW",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return None
        raise
    attributes: dict[str, Any] = response["Attributes"]
    return attributes


def _run_turn(
    conversation_id: str,
    item: dict[str, Any],
    pending: list[dict[str, Any]],
    conversation: dict[str, Any],
) -> None:
    started = time.monotonic()
    messages = sorted(pending, key=lambda m: (m["ts"], m["messageId"]))
    reply = _invoke_agent(_turn_request(conversation_id, item, messages, conversation))
    if reply:
        _notify(conversation_id, messages, reply)
    put_event(
        SOURCE,
        "agent.turn",
        {"conversationId": conversation_id, "latencyMs": int((time.monotonic() - started) * 1000)},
    )
    logger.info("turn done", messages=len(messages), replied=bool(reply))


def _turn_request(
    conversation_id: str,
    item: dict[str, Any],
    messages: list[dict[str, Any]],
    conversation: dict[str, Any],
) -> dict[str, Any]:
    """02 §6.2. Identity and role come from the Router (never from the message text)."""
    caller = item["caller"]
    customer_ids = list(caller.get("customerIds", []))
    return {
        "conversationId": conversation_id,
        "contactId": caller.get("contactId"),
        "role": caller["role"],
        "channelAddress": f"{caller['channel']}#{caller['from']}",
        "customerIds": customer_ids,
        "activeCustomerId": customer_ids[0] if len(customer_ids) == 1 else None,
        "channel": caller["channel"],
        "locale": caller["locale"],
        "activeOrderId": next((m["orderId"] for m in reversed(messages) if m.get("orderId")), None),
        "whatsappWindowOpen": _window_open(conversation.get("lastWhatsappInboundAt")),
        "proactive": False,
        "messages": [
            {k: v for k, v in m.items() if k in {"messageId", "ts", "text", "attachments"}}
            | ({"interactiveReply": m["interactiveReply"]} if m.get("interactiveReply") else {})
            for m in messages
        ],
        "arrivedDuringPreviousTurn": bool(item.get("afterTurn")),
    }


def _window_open(last_inbound: str | None) -> bool:
    if not last_inbound:
        return False
    return datetime.now(UTC) - datetime.fromisoformat(last_inbound) < WHATSAPP_WINDOW


def _invoke_agent(turn: dict[str, Any]) -> str:
    session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"suppliagent:{turn['conversationId']}"))
    try:
        response = _agent().invoke_agent_runtime(
            agentRuntimeArn=os.environ["AGENT_RUNTIME_ARN"],
            runtimeSessionId=session_id,
            payload=json.dumps(turn).encode(),
        )
        result = json.loads(response["response"].read())
    except ClientError as e:
        raise AgentTurnError from e
    if "error" in result:
        raise AgentTurnError
    return str(result.get("reply") or "")


def _notify(conversation_id: str, messages: list[dict[str, Any]], reply: str) -> None:
    """The key comes from the turn's messages, so a retried turn cannot send a second reply."""
    key = f"turn#{messages[0]['messageId']}#{messages[-1]['messageId']}"
    response = _lambda().invoke(
        FunctionName=os.environ["NOTIFIER_FUNCTION_NAME"],
        Payload=json.dumps(
            {
                "kind": "reply",
                "conversationId": conversation_id,
                "idempotencyKey": key,
                "text": reply,
            }
        ).encode(),
    )
    if response.get("FunctionError"):
        error_type = json.loads(response["Payload"].read()).get("errorType")
        if error_type in PERMANENT_NOTIFIER_ERRORS:
            # Retrying would run the agent again for nothing (its tools have side effects): the
            # turn is over, the Notifier already recorded why nothing went out.
            logger.warning("reply not deliverable", error=error_type)
            return
        raise AgentTurnError
