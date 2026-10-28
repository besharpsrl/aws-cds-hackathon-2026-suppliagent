"""Inbound Router (T-21, FN-01, FN-03; INFRASTRUCTURE_DESIGN §5.2).

SQS `inbound` (SNS envelope, batch of 1) -> normalize -> identity and role -> media to S3 (T-23)
-> conversation -> `Messages` + TurnBuffer (T-22, one transaction) -> `turn-flush` (Dispatcher).
`mode = HUMAN` (handoff) and unverified senders store the message only. The WhatsApp read receipt
goes through the Notifier (T-24: the only sender, AGENTS §8.7).

Environment: `TABLE_PREFIX`, `EVENT_BUS_NAME`, `INBOUND_MAIL_BUCKET`, `ORDER_DOMAIN` (SES domain,
empty = no order correlation), `TURN_FLUSH_QUEUE_URL`, `NOTIFIER_FUNCTION_NAME`,
`DEBOUNCE_TEXT_MS`, `DEBOUNCE_MEDIA_MS`, plus those of `media`.
"""

import hashlib
import json
import math
import os
import time
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

from inbound_router import media
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
DEDUP_TTL_SECONDS = 7 * 24 * 3600
logger = Logger(service="inbound-router")


@cache
def _s3() -> Any:
    return boto3.client("s3")


@cache
def _sqs() -> Any:
    return boto3.client("sqs")


@cache
def _lambda() -> Any:
    return boto3.client("lambda")


def handler(event: dict[str, Any], _context: Any) -> None:
    for record in event["Records"]:
        message = json.loads(json.loads(record["body"])["Message"])
        for raw in _raw_messages(message):
            _store(raw)


def _raw_messages(event: dict[str, Any]) -> list[RawMessage]:
    if is_whatsapp(event):
        return whatsapp_messages(event)
    if is_email(event):
        order_domain = os.environ.get("ORDER_DOMAIN", "").lower()
        return [email_message(event, _read_mail(event), order_domain)]
    raise InvalidInputError  # retried, then in the DLQ


def _read_mail(notification: dict[str, Any]) -> bytes:
    action = notification["receipt"]["action"]
    expected_key = f"mail/{notification['mail']['messageId']}"  # receipt rule prefix + SES id
    if (
        action["bucketName"] != os.environ["INBOUND_MAIL_BUCKET"]
        or action["objectKey"] != expected_key
    ):
        raise InvalidInputError
    body: bytes = (
        _s3().get_object(Bucket=action["bucketName"], Key=action["objectKey"])["Body"].read()
    )
    return body


def _store(raw: RawMessage) -> None:
    identity = resolve(raw.channel, raw.sender) if raw.sender_verified else UNKNOWN
    conversation_id = _conversation_id(identity, raw)
    logger.set_correlation_id(conversation_id)
    message_id = "msg_" + uuid5(NAMESPACE_URL, raw.provider_message_id).hex
    # Before any write: a failed download is retried with nothing half-stored.
    attachments = media.store(raw, identity.contact_id or conversation_id, message_id)
    created, mode = _touch_conversation(conversation_id, identity)
    _record_inbound(conversation_id, identity, raw)
    if created:
        put_event(
            SOURCE,
            "conversation.started",
            {"contactId": identity.contact_id, "role": identity.role, "channel": raw.channel},
        )
    # A dict: the wire name `from` is a Python keyword, mypy only knows the alias.
    message = NormalizedMessage.model_validate(
        {
            "messageId": message_id,
            "providerMessageId": raw.provider_message_id,
            "channel": raw.channel,
            "contactId": identity.contact_id,
            "role": identity.role,
            "customerIds": list(identity.customer_ids),
            "conversationId": conversation_id,
            "orderId": raw.order_id,
            "from": raw.sender,
            "senderVerified": raw.sender_verified,
            "text": raw.text,
            "attachments": list(attachments),
            "interactiveReply": raw.interactive_reply,
            "receivedAt": raw.received_at,
            "locale": LOCALES[identity.language],
        }
    )
    # HUMAN: the agent stays silent (FN-24). Unverified sender: never answered (backscatter, T-24).
    buffered = mode == "AGENT" and raw.sender_verified
    if _put_message(message, buffered):
        # Never log message content, numbers or addresses (AGENTS §7).
        logger.info("message stored", channel=raw.channel, role=identity.role)
        if raw.channel == "WHATSAPP":
            _read_receipt(
                conversation_id, raw.provider_message_id, f"{message.receivedAt}#{message_id}"
            )
    else:
        logger.info("duplicate delivery ignored", channel=raw.channel)
    # Also on a duplicate: a crash between the transaction and this send would leave the message
    # in the buffer with no flush; an extra flush is a no-op for the Dispatcher.
    if buffered:
        _schedule_flush(conversation_id, bool(attachments))


def _schedule_flush(conversation_id: str, has_media: bool) -> None:
    ms = int(os.environ["DEBOUNCE_MEDIA_MS" if has_media else "DEBOUNCE_TEXT_MS"])
    _sqs().send_message(
        QueueUrl=os.environ["TURN_FLUSH_QUEUE_URL"],
        MessageBody=json.dumps({"conversationId": conversation_id}),
        DelaySeconds=min(900, math.ceil(ms / 1000)),
    )


def _read_receipt(conversation_id: str, provider_message_id: str, ts_message_id: str) -> None:
    """Best effort: a failed receipt must not fail (and so redeliver) the message."""
    try:
        _lambda().invoke(
            FunctionName=os.environ["NOTIFIER_FUNCTION_NAME"],
            InvocationType="Event",
            Payload=json.dumps(
                {
                    "kind": "read_receipt",
                    "conversationId": conversation_id,
                    "providerMessageId": provider_message_id,
                    "tsMessageId": ts_message_id,
                }
            ).encode(),
        )
    except Exception:
        logger.exception("read receipt not requested")


def _conversation_id(identity: Identity, raw: RawMessage) -> str:
    """One conversation per contact across channels (F-15), or the one the address was identified
    in; unknown senders get one per address, and an unverified email sender one apart from the
    address owner's. Deterministic, so concurrent first messages cannot create two."""
    if identity.conversation_id:
        return identity.conversation_id
    if identity.contact_id:
        return "conv_" + identity.contact_id.replace("_", "")
    unverified = "" if raw.sender_verified else "#unverified"
    digest = hashlib.sha256(f"{raw.channel}#{raw.sender}{unverified}".encode()).hexdigest()
    return f"conv_u{digest[:16]}"


def _touch_conversation(conversation_id: str, identity: Identity) -> tuple[bool, str]:
    """Creates the conversation or updates it, keeping `mode` (handoff) and the identification
    attempts the tools keep on the same item. Returns (it did not exist, its `mode`)."""
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
    old = response.get("Attributes")
    return old is None, (old or {}).get("mode", "AGENT")


def _record_inbound(conversation_id: str, identity: Identity, raw: RawMessage) -> None:
    """Where to answer (`lastInbound*`, the only address the Notifier uses; for an email also the
    thread, `lastEmail*`) and, on WhatsApp, the
    start of the 24 h window. Verified senders only, and only if this message is newer than what
    is stored: a redelivery or a redriven old message must not move them back. ponytail: the two
    updates are not atomic with each other; a crash between them leaves the older window start,
    corrected by the next message."""
    if not raw.sender_verified:
        return

    def newer(attribute: str, sets: list[str], values: dict[str, Any]) -> None:
        try:
            table("conversations").update_item(
                Key={"conversationId": conversation_id},
                UpdateExpression="SET " + ", ".join(sets),
                ConditionExpression=f"attribute_not_exists({attribute}) OR {attribute} < :at",
                ExpressionAttributeValues={":at": raw.received_at} | values,
            )
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise

    sets = [
        "lastInboundAt = :at",
        "lastInboundChannel = :channel",
        "lastInboundFrom = :from",
        "lastInboundLocale = :locale",
    ]
    values = {":channel": raw.channel, ":from": raw.sender, ":locale": LOCALES[identity.language]}
    if raw.channel == "EMAIL":
        # The Notifier answers in this thread; empty when missing, so an older one is not reused.
        sets += ["lastEmailSubject = :subject", "lastEmailMessageId = :mid"]
        values |= {":subject": raw.email_subject or "", ":mid": raw.email_message_id or ""}
    newer("lastInboundAt", sets, values)
    if raw.channel == "WHATSAPP":
        newer("lastWhatsappInboundAt", ["lastWhatsappInboundAt = :at"], {})


def _put_message(message: NormalizedMessage, buffered: bool) -> bool:
    """False if this provider message was already stored. The guard item keyed by `messageId`
    (derived from `providerMessageId`) catches a redelivery even with a new timestamp or in
    another conversation (E-01); it expires through the TurnBuffer TTL. With `buffered` the message
    is appended to the conversation's TurnBuffer in the same transaction (T-22), so a redelivery
    cannot append it twice nor lose it."""
    item = message.model_dump(by_alias=True, exclude_none=True, mode="json")
    item["tsMessageId"] = f"{message.receivedAt}#{message.messageId}"
    guard = {
        "conversationId": f"dedup#{message.messageId}",
        "expiresAt": int(time.time()) + DEDUP_TTL_SECONDS,
    }
    messages = table("messages")
    transaction = [
        {
            "Put": {
                "TableName": messages.name,
                "Item": item,
                "ConditionExpression": "attribute_not_exists(tsMessageId)",
            }
        },
        {
            "Put": {
                "TableName": table("turn-buffer").name,
                "Item": guard,
                "ConditionExpression": "attribute_not_exists(conversationId)",
            }
        },
    ]
    if buffered:
        transaction.append(_buffer_append(message))
    try:
        # The resource's client takes plain Python values, like the Table API.
        messages.meta.client.transact_write_items(TransactItems=transaction)
    except ClientError as e:
        reasons = e.response.get("CancellationReasons", [])
        if any(r.get("Code") == "ConditionalCheckFailed" for r in reasons):
            return False
        raise  # e.g. a conflicting concurrent duplicate: retried, then a duplicate
    return True


def _buffer_append(message: NormalizedMessage) -> dict[str, Any]:
    """The TurnBuffer update that queues a message for the next turn (02 §3.3). `caller` is the
    latest sender: the turn is answered on that channel. The item outlives the burst by a day."""
    entry = message.model_dump(
        by_alias=True,
        exclude_none=True,
        mode="json",
        include={"messageId", "text", "attachments", "interactiveReply", "orderId"},
    )
    entry["ts"] = message.receivedAt
    now_ms = int(time.time() * 1000)
    entry["at"] = now_ms  # when we got it: what the debounce counts from (ts is the provider's)
    caller = message.model_dump(
        by_alias=True,
        exclude_none=True,
        mode="json",
        include={"channel", "from_", "role", "contactId", "customerIds", "locale"},
    )
    return {
        "Update": {
            "TableName": table("turn-buffer").name,
            "Key": {"conversationId": message.conversationId},
            "UpdateExpression": (
                "SET pending = list_append(if_not_exists(pending, :none), :entry),"
                " #caller = :caller, expiresAt = :expires"
            ),
            "ExpressionAttributeNames": {"#caller": "caller"},
            "ExpressionAttributeValues": {
                ":none": [],
                ":entry": [entry],
                ":caller": caller,
                ":expires": now_ms // 1000 + 24 * 3600,
            },
        }
    }
