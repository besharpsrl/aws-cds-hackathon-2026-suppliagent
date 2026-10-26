"""Inbound Router (T-21, FN-01, FN-03; INFRASTRUCTURE_DESIGN §5.2).

SQS `inbound` (SNS envelope, batch of 1) -> normalize -> identity and role -> conversation ->
`Messages`. Appending to the TurnBuffer and the handoff check (`mode = HUMAN`) arrive with T-22,
the read receipt with the Notifier (T-24: every send goes through it, AGENTS §8.7), media with T-23.

Environment: `TABLE_PREFIX`, `EVENT_BUS_NAME`, `INBOUND_MAIL_BUCKET`.
"""

import hashlib
import json
import os
from datetime import UTC, datetime
from functools import cache
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import boto3
from aws_lambda_powertools import Logger
from botocore.exceptions import ClientError
from suppliagent_shared.aws import put_event, table
from suppliagent_shared.errors import InvalidInputError
from suppliagent_shared.messages import NormalizedMessage

from inbound_router.identity import UNKNOWN, Identity, resolve
from inbound_router.normalize import (
    RawMessage,
    email_message,
    is_email,
    is_whatsapp,
    whatsapp_messages,
)

SOURCE = "suppliagent.inbound-router"
LOCALES = {"it": "it-IT", "en": "en-GB"}
logger = Logger(service="inbound-router")


@cache
def _s3() -> Any:
    return boto3.client("s3")


def handler(event: dict[str, Any], _context: Any) -> None:
    for record in event["Records"]:
        message = json.loads(json.loads(record["body"])["Message"])
        for raw in _raw_messages(message):
            _store(raw)


def _raw_messages(event: dict[str, Any]) -> list[RawMessage]:
    if is_whatsapp(event):
        return whatsapp_messages(event)
    if is_email(event):
        return [email_message(event, _read_mail(event))]
    raise InvalidInputError  # retried, then in the DLQ


def _read_mail(notification: dict[str, Any]) -> bytes:
    action = notification["receipt"]["action"]
    if action["bucketName"] != os.environ["INBOUND_MAIL_BUCKET"]:
        raise InvalidInputError
    body: bytes = (
        _s3().get_object(Bucket=action["bucketName"], Key=action["objectKey"])["Body"].read()
    )
    return body


def _store(raw: RawMessage) -> None:
    identity = resolve(raw.channel, raw.sender) if raw.sender_verified else UNKNOWN
    conversation_id = _conversation_id(identity, raw)
    logger.set_correlation_id(conversation_id)
    if _touch_conversation(conversation_id, identity):
        put_event(
            SOURCE,
            "conversation.started",
            {"contactId": identity.contact_id, "role": identity.role, "channel": raw.channel},
        )
    # A dict: the wire name `from` is a Python keyword, mypy only knows the alias.
    message = NormalizedMessage.model_validate(
        {
            "messageId": "msg_" + uuid5(NAMESPACE_URL, raw.provider_message_id).hex,
            "providerMessageId": raw.provider_message_id,
            "channel": raw.channel,
            "contactId": identity.contact_id,
            "role": identity.role,
            "customerIds": list(identity.customer_ids),
            "conversationId": conversation_id,
            "orderId": raw.order_id,
            "from": raw.sender,
            "text": raw.text,
            "attachments": list(raw.attachments),
            "interactiveReply": raw.interactive_reply,
            "receivedAt": raw.received_at,
            "locale": LOCALES[identity.language],
        }
    )
    if _put_message(message):
        # Never log message content, numbers or addresses (AGENTS §7).
        logger.info("message stored", channel=raw.channel, role=identity.role)
    else:
        logger.info("duplicate delivery ignored", channel=raw.channel)
    # T-22: append to the TurnBuffer here, idempotently (a retry lands in the duplicate branch).


def _conversation_id(identity: Identity, raw: RawMessage) -> str:
    """One conversation per contact across channels (F-15); unknown senders get one per address.
    Deterministic, so concurrent first messages cannot create two."""
    if identity.contact_id:
        return "conv_" + identity.contact_id.replace("_", "")
    digest = hashlib.sha256(f"{raw.channel}#{raw.sender}".encode()).hexdigest()
    return f"conv_u{digest[:16]}"


def _touch_conversation(conversation_id: str, identity: Identity) -> bool:
    """Creates the conversation or updates it, keeping `mode` (handoff) and the identification
    attempts the tools keep on the same item. True when it did not exist."""
    sets = ["#role = :role", "#mode = if_not_exists(#mode, :agent)", "lastMessageAt = :now"]
    values: dict[str, Any] = {
        ":role": identity.role,
        ":agent": "AGENT",
        ":now": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }
    if identity.contact_id:  # `by-contactId` is a GSI key: it cannot be empty
        sets.append("contactId = :contact")
        values[":contact"] = identity.contact_id
    response = table("conversations").update_item(
        Key={"conversationId": conversation_id},
        UpdateExpression="SET " + ", ".join(sets),
        ExpressionAttributeNames={"#role": "role", "#mode": "mode"},
        ExpressionAttributeValues=values,
        ReturnValues="ALL_OLD",
    )
    return "Attributes" not in response


def _put_message(message: NormalizedMessage) -> bool:
    """False if already stored (id and sort key come from the event: a redelivery repeats them)."""
    item = message.model_dump(by_alias=True, exclude_none=True, mode="json")
    item["tsMessageId"] = f"{message.receivedAt}#{message.messageId}"
    try:
        table("messages").put_item(
            Item=item, ConditionExpression="attribute_not_exists(tsMessageId)"
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        return False
    return True
