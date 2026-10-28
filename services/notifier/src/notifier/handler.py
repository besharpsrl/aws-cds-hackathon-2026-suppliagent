"""Notifier (T-24 base, FN-01, FN-14; INFRASTRUCTURE_DESIGN §5.5): the only caller of the CDS send
APIs (AGENTS §8.7).

Two kinds of request, invoked by Lambda (the Dispatcher, the Router):
- `reply`: a text to the contact of a conversation, on the channel of their last message. The
  address is never taken from the request: it is the verified one the Router stored on the
  conversation (`lastInbound*`), so a caller cannot make the Notifier write to an arbitrary number.
  Idempotent on `idempotencyKey`.
- `read_receipt`: WhatsApp "read" for an inbound message of that conversation.

And two events (T-26, FN-14):
- EventBridge `order.pdf_ready` (Order PDF, after `order.confirmed` / `order.updated`): the order
  confirmation email with the PDF, to the contact who confirmed (`suppliagent_shared.contacts`),
  in their language, Reply-To `ordine+<orderId>@`. Once per order revision. No address: skipped
  (F-07.C7, the assistant asks for one before the confirmation).
- SNS from the SES configuration set: a permanent bounce of a confirmation email clears the
  contact's `orderEmail` and asks for a new address in the order's conversation (F-11.C7).

Sandbox (SSM `notifierSandbox`, default on when the parameter is missing): nothing is sent, the
outgoing message is only recorded in `Messages`, so the pipeline runs without a WhatsApp number
or a verified SES identity (T-14).

Not in the base (T-24 complete, T-29): templates outside the 24 h window, SMS/RCS, quiet hours,
opt-out, channel fallback.

Environment: `TABLE_PREFIX`, `EVENT_BUS_NAME`, `WA_PHONE_NUMBER_ID_PARAM`, `SES_FROM_PARAM`,
`SES_CONFIGURATION_SET_PARAM`, `SANDBOX_PARAM`, `DOCUMENTS_BUCKET`.
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
from suppliagent_shared.contacts import order_email
from suppliagent_shared.errors import (
    AccessDeniedError,
    ChannelUnavailableError,
    InvalidInputError,
    NotFoundError,
    SuppliAgentError,
)
from suppliagent_shared.models import parse_order_id
from suppliagent_shared.orders import AFTER_CONFIRMATION

from notifier.order_email import Email, render

SOURCE = "suppliagent.notifier"
WHATSAPP_WINDOW = timedelta(hours=24)
WHATSAPP_TEXT_LIMIT = 4096
CLAIM_SECONDS = 120  # an unfinished send can be retried after this
DONE_SECONDS = 7 * 24 * 3600
SUBJECTS = {"it-IT": "La tua richiesta", "en-GB": "Your request"}
ORDER_TEMPLATE = "order_confirmation"
# The email follows the order through the ERP; a cancelled or expired order gets none.
EMAILED_STATUSES = AFTER_CONFIRMATION | {"SCHEDULED", "OUT_FOR_DELIVERY"}
BOUNCE_TEXT = {
    "it": "Non riesco a consegnare l'email di conferma dell'ordine {order}: l'indirizzo non "
    "risulta valido. Mi scrivi un altro indirizzo email per le conferme d'ordine?",
    "en": "I could not deliver the confirmation email for order {order}: the address does not "
    "seem to work. Could you send me another email address for order confirmations?",
}
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


@cache
def _s3() -> Any:
    return boto3.client("s3")


def reset_clients() -> None:
    """For tests."""
    _social.cache_clear()
    _ses.cache_clear()
    _s3.cache_clear()


def handler(event: dict[str, Any], _context: Any) -> dict[str, str]:
    if event.get("detail-type") == "order.pdf_ready":
        return _order_confirmation(event.get("detail") or {})
    if "Records" in event:
        return _email_events(event["Records"])
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
    extra: dict[str, str] = {"sentBy": request.sentBy} if request.sentBy else {}
    _store(
        request.conversationId,
        str(request.idempotencyKey),
        channel,
        str(request.text),
        provider_id,
        status,
        extra,
    )


def _store(
    conversation_id: str,
    key: str,
    channel: str,
    text: str,
    provider_id: str | None,
    status: str,
    extra: dict[str, str],
) -> None:
    message_id = "msg_" + uuid5(NAMESPACE_URL, f"out#{key}").hex
    sent_at = _now()
    item: dict[str, Any] = {
        "conversationId": conversation_id,
        "tsMessageId": f"{sent_at}#{message_id}",
        "messageId": message_id,
        "channel": channel,
        "direction": "OUTBOUND",
        "text": text,
        "sentAt": sent_at,
        "status": status,
        **extra,
    }
    if provider_id:  # a GSI key: cannot be empty
        item["providerMessageId"] = provider_id
    table("messages").put_item(Item=item)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# --- order confirmation email (T-26, FN-14) ------------------------------------------------


def _order_confirmation(detail: dict[str, Any]) -> dict[str, str]:
    order_id = parse_order_id(detail.get("orderId"))
    logger.set_correlation_id(order_id)
    order = table("orders").get_item(Key={"orderId": order_id}, ConsistentRead=True).get("Item")
    if not order:
        raise NotFoundError
    if order["status"] not in EMAILED_STATUSES:
        logger.info("order not confirmed: no email", status=order["status"])
        return {"status": "SKIPPED"}
    # The contact who confirmed (a sales rep for an order placed for a customer, F-10.D).
    contact_id = str(order.get("confirmedBy") or order.get("createdBy") or "")
    address = order_email(contact_id)
    if not address:  # F-07.C7: WhatsApp and SMS only; the assistant asked for an address
        _order_event("notification.skipped", order_id, sandbox=_sandbox(), reason="NO_EMAIL")
        return {"status": "NO_EMAIL"}
    current = int(order.get("revision", 0))
    revision = int(detail.get("revision", current))
    if revision < current:  # changed since: the newer `order.pdf_ready` sends the right email
        logger.info("order email superseded by a newer revision")
        return {"status": "SUPERSEDED"}
    key = f"order-email#{order_id}#{revision}"
    if not _claim(key):
        if _is_done(key):
            logger.info("duplicate order email ignored")
            return {"status": "DUPLICATE"}
        raise SendInProgressError
    sandbox = _sandbox()
    try:
        email = render(
            order,
            _venue(str(order["customerId"])),
            _language(contact_id),
            updated=detail.get("reason") == "updated",
        )
        pdf = (
            _s3()
            .get_object(Bucket=os.environ["DOCUMENTS_BUCKET"], Key=f"orders/{order_id}.pdf")["Body"]
            .read()
        )
        if not sandbox:
            _send_order_email(address, email, pdf, order_id, contact_id)
    except Exception:
        _unclaim(key)
        _order_event("notification.failed", order_id, sandbox=sandbox)
        raise
    _done(key)
    status = "SANDBOX" if sandbox else "SENT"
    try:
        if conversation_id := order.get("conversationId"):
            _store(
                str(conversation_id),
                key,
                "EMAIL",
                email.subject,
                None,
                status,
                {"orderId": order_id, "template": ORDER_TEMPLATE},
            )
        _order_event("notification.sent", order_id, sandbox=sandbox)
    except Exception:
        logger.exception("sent, but not recorded")
    logger.info("order email sent", sandbox=sandbox)  # never the address (AGENTS §7)
    return {"status": status}


def _venue(customer_id: str) -> str:
    customer = table("customers").get_item(Key={"customerId": customer_id}).get("Item") or {}
    return str(customer.get("venueName", ""))


def _language(contact_id: str) -> str:
    name, key = (
        ("sales-reps", "repId") if contact_id.startswith("rep_") else ("contacts", "contactId")
    )
    item = table(name).get_item(Key={key: contact_id}).get("Item") or {}
    return str(item.get("language", "it"))


def _send_order_email(
    address: str, email: Email, pdf: bytes, order_id: str, contact_id: str
) -> None:
    sender = _param("SES_FROM_PARAM")
    if sender == "UNSET":
        raise ChannelUnavailableError
    local, domain = sender.rsplit("@", 1)
    _ses().send_email(
        FromEmailAddress=sender,
        Destination={"ToAddresses": [address]},
        # Answers reach the Router with the order (F-15.C3): `ordine+<orderId>@` on our domain.
        ReplyToAddresses=[f"{local}+{order_id}@{domain}"],
        Content={
            "Simple": {
                "Subject": {"Data": email.subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": email.text, "Charset": "UTF-8"},
                    "Html": {"Data": email.html, "Charset": "UTF-8"},
                },
                "Attachments": [
                    {
                        "RawContent": pdf,
                        "FileName": f"{order_id}.pdf",
                        "ContentType": "application/pdf",
                        "ContentDisposition": "ATTACHMENT",
                    }
                ],
            }
        },
        # Echoed in the SES events: the bounce handler finds the order and the contact.
        EmailTags=[
            {"Name": "template", "Value": ORDER_TEMPLATE},
            {"Name": "orderId", "Value": order_id},
            {"Name": "contactId", "Value": contact_id},
        ],
        ConfigurationSetName=_param("SES_CONFIGURATION_SET_PARAM"),
    )


def _order_event(detail_type: str, order_id: str, *, sandbox: bool, reason: str = "") -> None:
    detail: dict[str, Any] = {
        "orderId": order_id,
        "channel": "EMAIL",
        "template": ORDER_TEMPLATE,
        "sandbox": sandbox,
    }
    if reason:
        detail["reason"] = reason
    put_event(SOURCE, detail_type, detail)


# --- SES events: bounces of the confirmation email (F-11.C7) -------------------------------


def _email_events(records: list[dict[str, Any]]) -> dict[str, str]:
    handled = 0
    for record in records:
        event = json.loads(record.get("Sns", {}).get("Message") or "{}")
        bounce = event.get("bounce", {})
        tags = event.get("mail", {}).get("tags", {})
        if (
            event.get("eventType") != "Bounce"
            or bounce.get("bounceType") != "Permanent"
            or tags.get("template") != [ORDER_TEMPLATE]
        ):
            continue  # deliveries, opens, transient bounces: only metrics
        _order_email_bounced(
            parse_order_id((tags.get("orderId") or [None])[0]),
            str((tags.get("contactId") or [""])[0]),
            {str(r.get("emailAddress", "")).lower() for r in bounce.get("bouncedRecipients", [])},
            str(event["mail"]["messageId"]),
        )
        handled += 1
    return {"status": "OK", "bounces": str(handled)}


def _order_email_bounced(
    order_id: str, contact_id: str, bounced: set[str], ses_message_id: str
) -> None:
    logger.set_correlation_id(order_id)
    _order_event("notification.failed", order_id, sandbox=False, reason="BOUNCED")
    if contact_id.startswith("con_") and bounced:
        try:  # only if it is still the address that bounced: a newer one is kept
            table("contacts").update_item(
                Key={"contactId": contact_id},
                UpdateExpression="SET orderEmailBouncedAt = :now REMOVE orderEmail",
                ConditionExpression="orderEmail IN ("
                + ", ".join(f":b{i}" for i in range(len(bounced)))
                + ")",
                ExpressionAttributeValues={
                    ":now": _now(),
                    **{f":b{i}": email for i, email in enumerate(sorted(bounced))},
                },
            )
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
    order = table("orders").get_item(Key={"orderId": order_id}).get("Item") or {}
    conversation_id = order.get("conversationId")
    conversation = (
        table("conversations").get_item(Key={"conversationId": conversation_id}).get("Item")
        if conversation_id
        else None
    )
    if not contact_id.startswith("con_"):
        return  # a sales rep's address is their channel identity: the back office fixes it
    if not conversation or (
        conversation.get("lastInboundChannel") == "EMAIL"
        and str(conversation.get("lastInboundFrom", "")).lower() in bounced
    ):
        logger.info("bounce: no channel to ask for a new address")
        return
    language = "en" if _language(contact_id).startswith("en") else "it"
    request = Request(
        kind="reply",
        conversationId=str(conversation_id),
        idempotencyKey=f"bounce#{ses_message_id}",
        text=BOUNCE_TEXT[language].format(order=order_id),
    )
    try:
        _reply(request, conversation)
    except ChannelUnavailableError:  # outside the WhatsApp window: no template for this yet
        logger.info("bounce: channel unavailable, nobody asked")


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
