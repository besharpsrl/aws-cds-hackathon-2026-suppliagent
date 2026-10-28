"""Live conversations and handoff actions for the back office (FN-24, FN-28, F-14).

Read: `backoffice` and `judge` (a `sales_rep` is refused: conversations are not scoped to a
portfolio). Write (*Take over*, *Reply*, *Release*): `backoffice` only. Every function returns
`(status, body)`; the handler turns it into the HTTP response. The reply goes out through the
Notifier, the only sender (AGENTS §8.7), on the channel the contact last used: the console never
picks an address.

Environment: `TABLE_PREFIX`, `EVENT_BUS_NAME`, `NOTIFIER_FUNCTION_NAME`.
"""

import json
import logging
import os
import re
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from suppliagent_shared.aws import table
from suppliagent_shared.errors import NotFoundError
from suppliagent_shared.handoff import HandoffReason, release_handoff, start_handoff

logger = logging.getLogger("console_api")
Result = tuple[int, dict[str, Any]]
SOURCE = "suppliagent.console-api"
BY = "BACKOFFICE"
TAKEOVER_SUMMARY = "Back office took over from the console."
PAGE_SIZE = (
    100  # ponytail: one page, no pagination; add LastEvaluatedKey paging if the demo outgrows it.
)
MAX_REPLY_CHARS = 1000
KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
SUMMARY_FIELDS = ("conversationId", "contactId", "role", "mode", "lastMessageAt")
NOTIFIER_ERRORS = {
    "AccessDeniedError": (409, "no_reply_address"),
    "ChannelUnavailableError": (409, "channel_unavailable"),
    "SendInProgressError": (503, "send_in_progress"),
}


def _batch_get(
    name: str, key: str, ids: set[str], projection: str, names: dict[str, str] | None = None
) -> dict[str, dict[str, Any]]:
    """Items by key, best effort: the UI falls back to the id when one is missing."""
    if not ids:
        return {}
    dynamodb: Any = boto3.resource("dynamodb")
    table_name = table(name).name
    request: dict[str, Any] = {
        "Keys": [{key: i} for i in sorted(ids)],
        "ProjectionExpression": projection,
    }
    if names:
        request["ExpressionAttributeNames"] = names
    res = dynamodb.batch_get_item(RequestItems={table_name: request})
    return {i[key]: i for i in res["Responses"].get(table_name, [])}


def _names(conversations: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """Contact name and venue, only for `con_…` contacts (a rep has no Contacts row)."""
    contact_ids = {
        c["contactId"] for c in conversations if str(c.get("contactId", "")).startswith("con_")
    }
    contacts = _batch_get(
        "contacts", "contactId", contact_ids, "contactId, #n, customerId", {"#n": "name"}
    )
    venues = _batch_get(
        "customers",
        "customerId",
        {c["customerId"] for c in contacts.values() if "customerId" in c},
        "customerId, venueName",
    )
    names: dict[str, dict[str, str]] = {}
    for contact_id, contact in contacts.items():
        names[contact_id] = {
            k: v
            for k, v in (
                ("contactName", contact.get("name")),
                ("customerName", venues.get(contact.get("customerId", ""), {}).get("venueName")),
            )
            if v
        }
    return names


def _summaries(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    names = _names(items)
    out = []
    for item in items:
        summary: dict[str, Any] = {k: item[k] for k in SUMMARY_FIELDS if k in item}
        summary["mode"] = item.get("mode", "AGENT")
        summary["channel"] = item.get("lastInboundChannel")
        if handoff := item.get("handoff"):
            summary["handoff"] = handoff
        summary.update(names.get(item.get("contactId", ""), {}))
        out.append(summary)
    return out


def list_conversations() -> Result:
    # ponytail: Scan of one page; the demo has a handful of conversations.
    items = table("conversations").scan(Limit=PAGE_SIZE)["Items"]
    conversations = _summaries(items)
    # The ones waiting for a human first, then the most recent.
    conversations.sort(key=lambda c: c.get("lastMessageAt", ""), reverse=True)
    conversations.sort(key=lambda c: c["mode"] != "HUMAN")
    return 200, {"conversations": conversations}


def _message_view(message: dict[str, Any]) -> dict[str, Any]:
    """A stored message for the console: text and attachment types only, never addresses or URIs."""
    view: dict[str, Any] = {
        "messageId": message.get("messageId"),
        "direction": message.get("direction"),
        "channel": message.get("channel"),
        "at": message.get("receivedAt") or message.get("sentAt"),
        "text": message.get("text"),
        "attachments": [a.get("type") for a in message.get("attachments") or []],
    }
    if reply := message.get("interactiveReply"):
        view["interactiveReply"] = reply.get("title")
    if message.get("status"):
        view["status"] = message["status"]
    if message.get("sentBy"):
        view["sentBy"] = message["sentBy"]
    return view


def get_conversation(conversation_id: str) -> Result:
    conversation = (
        table("conversations")
        .get_item(Key={"conversationId": conversation_id}, ConsistentRead=True)
        .get("Item")
    )
    if not conversation:
        return 404, {"error": "not_found"}
    # ponytail: the latest page of the history; page backwards if a chat outgrows it.
    messages = table("messages").query(
        KeyConditionExpression=Key("conversationId").eq(conversation_id),
        ScanIndexForward=False,
        Limit=PAGE_SIZE,
    )["Items"]
    messages.reverse()
    return 200, {
        "conversation": _summaries([conversation])[0],
        "messages": [_message_view(m) for m in messages],
    }


def _mode(conversation_id: str) -> str | None:
    item = (
        table("conversations")
        .get_item(Key={"conversationId": conversation_id}, ConsistentRead=True)
        .get("Item")
    )
    return None if item is None else str(item.get("mode", "AGENT"))


def take_over(conversation_id: str) -> Result:
    try:
        started = start_handoff(
            SOURCE, conversation_id, HandoffReason.OPERATOR_TAKEOVER, TAKEOVER_SUMMARY, by=BY
        )
    except NotFoundError:
        return 404, {"error": "not_found"}
    # False: already HUMAN (an agent handoff or another operator); the first reason is kept.
    return 200, {"mode": "HUMAN", "started": started}


def release(conversation_id: str) -> Result:
    if _mode(conversation_id) is None:
        return 404, {"error": "not_found"}
    released = release_handoff(SOURCE, conversation_id, by=BY)
    return 200, {"mode": "AGENT", "released": released}


def reply(conversation_id: str, raw_body: str | None) -> Result:
    """The operator's text to the contact. Only while the conversation is HUMAN: otherwise the
    agent could answer the same message too. Idempotent on the client's `idempotencyKey`."""
    try:
        body = json.loads(raw_body or "")
        text, key = body["text"], body["idempotencyKey"]
        if not (isinstance(text, str) and isinstance(key, str)):
            raise TypeError
        text = text.strip()
        if not text or len(text) > MAX_REPLY_CHARS or not KEY_PATTERN.match(key):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        return 400, {"error": "invalid_body"}
    mode = _mode(conversation_id)
    if mode is None:
        return 404, {"error": "not_found"}
    if mode != "HUMAN":
        return 409, {"error": "not_in_handoff"}
    payload = {
        "kind": "reply",
        "conversationId": conversation_id,
        "idempotencyKey": f"console#{conversation_id}#{key}",
        "text": text,
        "sentBy": "OPERATOR",
    }
    response = boto3.client("lambda").invoke(
        FunctionName=os.environ["NOTIFIER_FUNCTION_NAME"],
        Payload=json.dumps(payload).encode(),
    )
    result = json.loads(response["Payload"].read() or "{}")
    if response.get("FunctionError"):
        error_type = str(result.get("errorType", ""))
        logger.warning("reply failed", extra={"error": error_type})  # never the text
        status, error = NOTIFIER_ERRORS.get(error_type, (502, "send_failed"))
        return status, {"error": error}
    return 200, {"status": result.get("status", "SENT")}
