"""Notifier (T-24 base, FN-01, FN-14; INFRASTRUCTURE_DESIGN §5.5): the only caller of the CDS send
APIs (AGENTS §8.7).

Two kinds of request, invoked by Lambda (the Dispatcher, the Router):
- `reply`: a text to the contact of a conversation, on the channel of their last message. The
  address is never taken from the request: it is the verified one the Router stored on the
  conversation (`lastInbound*`), so a caller cannot make the Notifier write to an arbitrary number.
  Idempotent on `idempotencyKey`.
- `read_receipt`: WhatsApp "read" for an inbound message of that conversation.

Sandbox (SSM `notifierSandbox`, default on when the parameter is missing): nothing is sent, the
outgoing message is only recorded in `Messages`, so the pipeline runs without a WhatsApp number
or a verified SES identity (T-14).

Not in the base (T-24 complete, T-29): templates outside the 24 h window, SMS/RCS, quiet hours,
opt-out, channel fallback, order confirmation emails.

Environment: `TABLE_PREFIX`, `EVENT_BUS_NAME`, `WA_PHONE_NUMBER_ID_PARAM`, `SES_FROM_PARAM`,
`SES_CONFIGURATION_SET_PARAM`, `SANDBOX_PARAM`.
"""

import json
import os
import time
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities import parameters
from botocore.exceptions import ClientError
from pydantic import BaseModel, ConfigDict
from suppliagent_shared.aws import put_event, table
from suppliagent_shared.errors import (
    AccessDeniedError,
    ChannelUnavailableError,
    InvalidInputError,
    SuppliAgentError,
)

SOURCE = "suppliagent.notifier"
WHATSAPP_WINDOW = timedelta(hours=24)
WHATSAPP_TEXT_LIMIT = 4096
CLAIM_SECONDS = 120  # an unfinished send can be retried after this
DONE_SECONDS = 7 * 24 * 3600
SUBJECTS = {"it-IT": "La tua richiesta", "en-GB": "Your request"}
logger = Logger(service="notifier")


class SendInProgressError(SuppliAgentError):
    """Another attempt with the same key is sending; retried by the caller."""

    code = "SEND_IN_PROGRESS"


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["reply", "read_receipt"]
    conversationId: str  # noqa: N815 - wire name
    idempotencyKey: str | None = None  # noqa: N815
    text: str | None = None
    sentBy: Literal["OPERATOR"] | None = None  # noqa: N815 - set by the console: an operator's reply
    providerMessageId: str | None = None  # noqa: N815
    tsMessageId: str | None = None  # noqa: N815 - sort key of the received message


@cache
def _social() -> Any:
    return boto3.client("socialmessaging")


@cache
def _ses() -> Any:
    return boto3.client("sesv2")


def reset_clients() -> None:
    """For tests."""
    _social.cache_clear()
    _ses.cache_clear()


def handler(event: dict[str, Any], _context: Any) -> dict[str, str]:
    request = Request.model_validate(event)
    logger.set_correlation_id(request.conversationId)
    conversation = (
        table("conversations").get_item(Key={"conversationId": request.conversationId}).get("Item")
    )
    if not conversation:
        raise AccessDeniedError
    if request.kind == "read_receipt":
        return _read_receipt(request)
    return _reply(request, conversation)


def _param(env_name: str) -> str:
    value: str = parameters.get_parameter(os.environ[env_name], max_age=60)
    return value


def _sandbox() -> bool:
    try:
        return _param("SANDBOX_PARAM").lower() != "false"
    except parameters.exceptions.GetParameterError:
        return True  # fail safe: never send for real by accident


def _phone_number_id() -> str:
    value = _param("WA_PHONE_NUMBER_ID_PARAM")
    if value == "UNSET":
        raise ChannelUnavailableError
    return value


def _read_receipt(request: Request) -> dict[str, str]:
    """Only for a WhatsApp message actually received in this conversation (a direct, consistent
    read of the stored message: the GSI could lag behind the Router's write)."""
    if not request.providerMessageId or not request.tsMessageId:
        raise InvalidInputError
    item = (
        table("messages")
        .get_item(
            Key={"conversationId": request.conversationId, "tsMessageId": request.tsMessageId},
            ConsistentRead=True,
        )
        .get("Item")
    )
    if not (
        item
        and item["providerMessageId"] == request.providerMessageId
        and item["channel"] == "WHATSAPP"
        and item["direction"] == "INBOUND"
    ):
        raise AccessDeniedError
    if _sandbox():
        return {"status": "SANDBOX"}
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": request.providerMessageId,
    }
    _social().send_whatsapp_message(
        originationPhoneNumberId=_phone_number_id(),
        message=json.dumps(payload).encode(),
        metaApiVersion="v20.0",
    )
    return {"status": "SENT"}


def _reply(request: Request, conversation: dict[str, Any]) -> dict[str, str]:
    if not request.idempotencyKey or not request.text:
        raise InvalidInputError
    channel = conversation.get("lastInboundChannel")
    address = conversation.get("lastInboundFrom")
    if not channel or not address:  # no verified sender: nobody to answer (backscatter)
        raise AccessDeniedError
    if not _claim(request.idempotencyKey):
        if _is_done(request.idempotencyKey):
            logger.info("duplicate request ignored")
            return {"status": "DUPLICATE"}
        raise SendInProgressError  # a concurrent attempt may still fail: the caller retries
    sandbox = _sandbox()
    try:
        provider_id = None if sandbox else _send(channel, address, request.text, conversation)
    except Exception:
        _unclaim(request.idempotencyKey)
        _event("notification.failed", request.conversationId, channel, sandbox)
        raise
    # Sent: from here nothing may make a retry send again, so mark it before anything else.
    _done(request.idempotencyKey)
    status = "SANDBOX" if sandbox else "SENT"
    try:
        _record(request, channel, provider_id, status)
        _event("notification.sent", request.conversationId, channel, sandbox)
    except Exception:
        logger.exception("sent, but not recorded")  # losing the record beats a second message
    # Never log the text, the number or the address (AGENTS §7).
    logger.info("reply sent", channel=channel, sandbox=sandbox)
    return {"status": status}


def _event(detail_type: str, conversation_id: str, channel: str, sandbox: bool) -> None:
    put_event(
        SOURCE,
        detail_type,
        {
            "conversationId": conversation_id,
            "channel": channel,
            "template": None,
            "sandbox": sandbox,
        },
    )


def _send(channel: str, address: str, text: str, conversation: dict[str, Any]) -> str | None:
    if channel == "WHATSAPP":
        return _send_whatsapp(address, text, conversation.get("lastWhatsappInboundAt"))
    if channel == "EMAIL":
        _send_email(address, text, conversation.get("lastInboundLocale"))
        return None
    raise ChannelUnavailableError  # SMS/RCS arrive with T-27


def _send_whatsapp(address: str, text: str, last_inbound: str | None) -> str:
    # Free text only inside the 24 h window; templates arrive with T-29 (F-11.C2).
    if (
        not last_inbound
        or datetime.now(UTC) - datetime.fromisoformat(last_inbound) >= WHATSAPP_WINDOW
    ):
        raise ChannelUnavailableError
    payload = {
        "messaging_product": "whatsapp",
        "to": address,
        "type": "text",
        "text": {"body": text[:WHATSAPP_TEXT_LIMIT]},
    }
    response = _social().send_whatsapp_message(
        originationPhoneNumberId=_phone_number_id(),
        message=json.dumps(payload).encode(),
        metaApiVersion="v20.0",
    )
    return str(response.get("messageId", ""))  # an empty id is simply not stored


def _send_email(address: str, text: str, locale: str | None) -> None:
    sender = _param("SES_FROM_PARAM")
    if sender == "UNSET":
        raise ChannelUnavailableError
    _ses().send_email(
        FromEmailAddress=sender,
        Destination={"ToAddresses": [address]},
        Content={
            "Simple": {
                "Subject": {"Data": SUBJECTS.get(locale or "", SUBJECTS["it-IT"])},
                "Body": {"Text": {"Data": text}},
            }
        },
        ConfigurationSetName=_param("SES_CONFIGURATION_SET_PARAM"),
    )


def _record(request: Request, channel: str, provider_id: str | None, status: str) -> None:
    """The outgoing message in the conversation history (console, KPIs)."""
    message_id = "msg_" + uuid5(NAMESPACE_URL, f"out#{request.idempotencyKey}").hex
    sent_at = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    item: dict[str, Any] = {
        "conversationId": request.conversationId,
        "tsMessageId": f"{sent_at}#{message_id}",
        "messageId": message_id,
        "channel": channel,
        "direction": "OUTBOUND",
        "text": request.text,
        "sentAt": sent_at,
        "status": status,
    }
    if request.sentBy:
        item["sentBy"] = request.sentBy
    if provider_id:  # a GSI key: cannot be empty
        item["providerMessageId"] = provider_id
    table("messages").put_item(Item=item)


# Idempotency: a claim in the TurnBuffer table (TTL attribute `expiresAt`, like the Router's
# `dedup#` guards). Claimed while sending, so a retry during the send is refused; released on
# failure so the retry sends; kept for a week once sent. A crash mid-send lets the claim lapse
# after CLAIM_SECONDS: at-least-once rather than lost.
def _claim_key(key: str) -> dict[str, str]:
    return {"conversationId": f"dedup#out#{key}"}


def _claim(key: str) -> bool:
    now = int(time.time())
    try:
        table("turn-buffer").put_item(
            Item=_claim_key(key) | {"expiresAt": now + CLAIM_SECONDS},
            ConditionExpression="attribute_not_exists(conversationId) OR expiresAt < :now",
            ExpressionAttributeValues={":now": now},
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise
    return True


def _unclaim(key: str) -> None:
    table("turn-buffer").delete_item(Key=_claim_key(key))


def _done(key: str) -> None:
    table("turn-buffer").update_item(
        Key=_claim_key(key),
        UpdateExpression="SET expiresAt = :until, sent = :true",
        ExpressionAttributeValues={":until": int(time.time()) + DONE_SECONDS, ":true": True},
    )


def _is_done(key: str) -> bool:
    item = table("turn-buffer").get_item(Key=_claim_key(key), ConsistentRead=True).get("Item")
    return bool(item and item.get("sent"))
