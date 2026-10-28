"""Notifier (T-24 base, FN-01, FN-14; INFRASTRUCTURE_DESIGN §5.5): the only caller of the CDS send
APIs (AGENTS §8.7).

Two kinds of request, invoked by Lambda (the Dispatcher, the Router):
- `reply`: a text to the contact of a conversation, on the channel of their last message. The
  address is never taken from the request: it is the verified one the Router stored on the
  conversation (`lastInbound*`), so a caller cannot make the Notifier write to an arbitrary number.
  Idempotent on `idempotencyKey`.
  With `interactive` (T-25, FN-08, FN-12) the text goes out on WhatsApp as a message with reply
  buttons (up to 3 short options) or a list (up to 10); on other channels the options are already
  in the text. For an order summary (`ORDER_SUMMARY`) the id of the sent message is stored in
  `Orders.summaryMessageId`: `confirm_order` accepts a tap only as a reply to that message.
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
from pydantic import BaseModel, ConfigDict, Field
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
# WhatsApp interactive limits (Cloud API): body 1024, button title 20 (max 3 buttons), list row
# title 24 (max 10 rows), list button label 20.
INTERACTIVE_BODY_LIMIT = 1024
BUTTON_TITLE_LIMIT = 20
MAX_BUTTONS = 3
ROW_TITLE_LIMIT = 24
# Body of the interactive message when the text is too long for it and goes out first on its own.
SHORT_BODY = {
    "ORDER_SUMMARY": {"it": "Confermi l'ordine?", "en": "Do you confirm the order?"},
    "CHOICE": {"it": "Scegli un'opzione:", "en": "Choose an option:"},
}
LIST_BUTTON = {"it": "Scegli", "en": "Choose"}
logger = Logger(service="notifier")


class SendInProgressError(SuppliAgentError):
    """Another attempt with the same key is sending; retried by the caller."""

    code = "SEND_IN_PROGRESS"


class Option(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9_]{1,40}$")
    title: str = Field(min_length=1, max_length=ROW_TITLE_LIMIT)


class Interactive(BaseModel):
    """Options of the reply (T-25): an order summary's Confirm / Change, or one question's
    choices. Built by the agent's code, not by the model."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["ORDER_SUMMARY", "CHOICE"]
    options: list[Option] = Field(min_length=1, max_length=10)
    orderId: str | None = Field(None, pattern=r"^ord_[A-Za-z0-9]{1,40}$")  # noqa: N815


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["reply", "read_receipt"]
    conversationId: str  # noqa: N815 - wire name
    idempotencyKey: str | None = None  # noqa: N815
    text: str | None = None
    sentBy: Literal["OPERATOR"] | None = None  # noqa: N815 - set by the console: an operator's reply
    providerMessageId: str | None = None  # noqa: N815
    tsMessageId: str | None = None  # noqa: N815 - sort key of the received message
    interactive: Interactive | None = None


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
    interactive = request.interactive if channel == "WHATSAPP" else None
    try:
        if sandbox:
            # A recorded id lets the simulator tap the buttons (scripts/simulate_channel.py --tap).
            provider_id = _sandbox_id(request.idempotencyKey) if interactive else None
        else:
            provider_id = _send(channel, address, request.text, conversation, interactive)
    except Exception:
        _unclaim(request.idempotencyKey)
        _event("notification.failed", request.conversationId, channel, sandbox)
        raise
    # Sent: from here nothing may make a retry send again, so mark it before anything else.
    _done(request.idempotencyKey)
    status = "SANDBOX" if sandbox else "SENT"
    try:
        _record(request, channel, provider_id, status, interactive)
        _event("notification.sent", request.conversationId, channel, sandbox)
    except Exception:
        logger.exception("sent, but not recorded")  # losing the record beats a second message
    if interactive and interactive.kind == "ORDER_SUMMARY" and interactive.orderId and provider_id:
        _remember_summary(interactive.orderId, request.conversationId, provider_id)
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


def _sandbox_id(key: str) -> str:
    return "wamid.sandbox_" + uuid5(NAMESPACE_URL, f"out#{key}").hex


def _remember_summary(order_id: str, conversation_id: str, provider_id: str) -> None:
    """Only on an order of this conversation still waiting for the answer: a summary message sent
    for another conversation's order, or after the order moved on, changes nothing. A failure only
    costs the tap (`CONFIRMATION_MISMATCH`, the customer confirms in words): logged, not raised."""
    try:
        table("orders").update_item(
            Key={"orderId": order_id},
            UpdateExpression="SET summaryMessageId = :m",
            ConditionExpression="conversationId = :c AND #status = :pending",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":m": provider_id,
                ":c": conversation_id,
                ":pending": "PENDING_CONFIRMATION",
            },
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            logger.exception("summary message not stored on the order")
        else:
            logger.warning("summary for an order not pending in this conversation")
    except Exception:
        logger.exception("summary message not stored on the order")


def _send(
    channel: str,
    address: str,
    text: str,
    conversation: dict[str, Any],
    interactive: Interactive | None = None,
) -> str | None:
    if channel == "WHATSAPP":
        last_inbound = conversation.get("lastWhatsappInboundAt")
        if interactive:
            return _send_whatsapp_interactive(
                address, text, last_inbound, interactive, conversation.get("lastInboundLocale")
            )
        return _send_whatsapp(address, text, last_inbound)
    if channel == "EMAIL":
        _send_email(address, text, conversation.get("lastInboundLocale"))
        return None
    raise ChannelUnavailableError  # SMS/RCS arrive with T-27


def _check_window(last_inbound: str | None) -> None:
    # Free text only inside the 24 h window; templates arrive with T-29 (F-11.C2).
    if (
        not last_inbound
        or datetime.now(UTC) - datetime.fromisoformat(last_inbound) >= WHATSAPP_WINDOW
    ):
        raise ChannelUnavailableError


def _send_whatsapp(address: str, text: str, last_inbound: str | None) -> str:
    _check_window(last_inbound)
    return _whatsapp({"to": address, "type": "text", "text": {"body": text[:WHATSAPP_TEXT_LIMIT]}})


def _send_whatsapp_interactive(
    address: str,
    text: str,
    last_inbound: str | None,
    interactive: Interactive,
    locale: str | None,
) -> str:
    """Buttons when the options fit (at most 3, short titles), a list otherwise. A text longer
    than the interactive body goes out first as a plain message; the buttons follow with a short
    question. The id returned is the interactive message's: the one a tap replies to."""
    _check_window(last_inbound)
    language = "en" if (locale or "").lower().startswith("en") else "it"
    body = text
    if len(text) > INTERACTIVE_BODY_LIMIT:
        _whatsapp({"to": address, "type": "text", "text": {"body": text[:WHATSAPP_TEXT_LIMIT]}})
        body = SHORT_BODY[interactive.kind][language]
    options = interactive.options
    if len(options) <= MAX_BUTTONS and all(len(o.title) <= BUTTON_TITLE_LIMIT for o in options):
        content: dict[str, Any] = {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": o.id, "title": o.title}} for o in options
                ]
            },
        }
    else:
        content = {
            "type": "list",
            "body": {"text": body},
            "action": {
                "button": LIST_BUTTON[language],
                "sections": [
                    {"rows": [{"id": o.id, "title": o.title} for o in options]},
                ],
            },
        }
    return _whatsapp({"to": address, "type": "interactive", "interactive": content})


def _whatsapp(message: dict[str, Any]) -> str:
    response = _social().send_whatsapp_message(
        originationPhoneNumberId=_phone_number_id(),
        message=json.dumps({"messaging_product": "whatsapp", **message}).encode(),
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


def _record(
    request: Request,
    channel: str,
    provider_id: str | None,
    status: str,
    interactive: Interactive | None = None,
) -> None:
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
    if interactive:  # what the contact could tap (console, simulator)
        item["interactive"] = interactive.model_dump(exclude_none=True)
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
