"""Notifier (T-24 base, FN-01, FN-14; INFRASTRUCTURE_DESIGN §5.5): the only caller of the CDS send
APIs (AGENTS §8.7).

Two kinds of request, invoked by Lambda (the Dispatcher, the Router):
- `reply`: a text to the contact of a conversation, on the channel of their last message. The
  address is never taken from the request: it is the verified one the Router stored on the
  conversation (`lastInbound*`), so a caller cannot make the Notifier write to an arbitrary number.
  An email reply goes out in the contact's thread (`lastEmail*`: "Re: <subject>", In-Reply-To).
  Idempotent on `idempotencyKey`.
  With `interactive` (T-25, FN-08, FN-12) the text goes out on WhatsApp as a message with reply
  buttons (up to 3 short options) or a list (up to 10); on other channels the options are already
  in the text. For an order summary (`ORDER_SUMMARY`) the id of the sent message is stored in
  `Orders.summaryMessageId`: `confirm_order` accepts a tap only as a reply to that message.
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

And two WhatsApp templates (T-29 approved them; T-52, F-13 / F-12):
- EventBridge `reorder.due` (Proactive Trigger, morning window, consent and cooldown checked
  there): `reorder_suggestion` to each consenting contact of the venue whose conversation is on
  WhatsApp, with quick replies `reorder_same` / `reorder_modify` / `reorder_no` / `reorder_stop`.
- EventBridge `order.status_changed` to `OUT_FOR_DELIVERY` (ERP mock `advance`): `delivery_update`
  with the delivery window, quick replies `delivery_received` / `delivery_issue`.
A template goes out also outside the 24 h window; the taps reach the agent as `interactiveReply`.

And SMS/RCS (T-27, FN-15, FN-18; AWS End User Messaging SMS v2, `SendRcsMessage` with the SMS
fallback of the sender ID): replies on the `SMS` channel (suggested replies for the options), the
short order confirmation next to the email, and the delivery message with *Received / Report a
problem* for a contact who has a verified `SMS#` identity (otherwise the WhatsApp template).

Not yet (T-24 complete): other templates outside the window, opt-out, channel fallback.

Environment: `TABLE_PREFIX`, `EVENT_BUS_NAME`, `WA_PHONE_NUMBER_ID_PARAM`, `SES_FROM_PARAM`,
`SES_CONFIGURATION_SET_PARAM`, `SANDBOX_PARAM`, `DOCUMENTS_BUCKET`, `DELIVERY_CUTOFF`,
`RCS_AGENT_PARAM`, `SMS_SENDER_PARAM`, `SMS_CONFIGURATION_SET_PARAM`.
"""

import json
import os
import re
import time
from datetime import UTC, date, datetime, timedelta
from functools import cache
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

import boto3
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities import parameters
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from pydantic import BaseModel, ConfigDict, Field, model_validator
from suppliagent_shared.aws import put_event, table
from suppliagent_shared.contacts import order_email
from suppliagent_shared.delivery import calendar_closed, delivery_dates, parse_cutoff
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
_MD_HEADING = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t]*$", re.MULTILINE)
_MD_BOLD = re.compile(r"\*\*(?!\s)(.+?)(?<!\s)\*\*")
CLAIM_SECONDS = 120  # an unfinished send can be retried after this
DONE_SECONDS = 7 * 24 * 3600
SUBJECTS = {"it-IT": "La tua richiesta", "en-GB": "Your request"}
# An email subject that already says it is a reply (Router normalize.REPLY_SUBJECT).
REPLY_SUBJECT = re.compile(r"^\s*(re|r|rif|aw|sv)\s*:", re.IGNORECASE)
ORDER_TEMPLATE = "order_confirmation"
# The email follows the order through the ERP; a cancelled or expired order gets none.
EMAILED_STATUSES = AFTER_CONFIRMATION | {"SCHEDULED", "OUT_FOR_DELIVERY"}
BOUNCE_TEXT = {
    "it": "Non riesco a consegnare l'email di conferma dell'ordine {order}: l'indirizzo non "
    "risulta valido. Mi scrivi un altro indirizzo email per le conferme d'ordine?",
    "en": "I could not deliver the confirmation email for order {order}: the address does not "
    "seem to work. Could you send me another email address for order confirmations?",
}
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

    @model_validator(mode="after")
    def _distinct(self) -> "Interactive":
        # WhatsApp refuses buttons or rows with the same id or title.
        ids = [o.id for o in self.options]
        titles = [o.title.casefold() for o in self.options]
        if len(set(ids)) != len(ids) or len(set(titles)) != len(titles):
            raise ValueError("options must have distinct ids and titles")
        return self


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
def _sms() -> Any:
    return boto3.client("pinpoint-sms-voice-v2")


@cache
def _ses() -> Any:
    return boto3.client("sesv2")


@cache
def _s3() -> Any:
    return boto3.client("s3")


def reset_clients() -> None:
    """For tests."""
    _social.cache_clear()
    _sms.cache_clear()
    _ses.cache_clear()
    _s3.cache_clear()


def handler(event: dict[str, Any], _context: Any) -> dict[str, str]:
    if event.get("detail-type") == "order.pdf_ready":
        _order_sms(event.get("detail") or {})
        return _order_confirmation(event.get("detail") or {})
    if event.get("detail-type") == "reorder.due":
        return _reorder_due(event.get("detail") or {})
    if event.get("detail-type") == "order.status_changed":
        return _delivery_update(event.get("detail") or {})
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
    interactive = request.interactive if channel in ("WHATSAPP", "SMS") else None
    try:
        if sandbox:
            # A recorded id lets the simulator tap the buttons (scripts/simulate_channel.py --tap).
            provider_id = _sandbox_id(request.idempotencyKey) if interactive else None
        else:
            provider_id, shown = _send(channel, address, request.text, conversation, interactive)
            interactive = interactive if shown else None
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


def _event(
    detail_type: str,
    conversation_id: str,
    channel: str,
    sandbox: bool,
    template: str | None = None,
) -> None:
    put_event(
        SOURCE,
        detail_type,
        {
            "conversationId": conversation_id,
            "channel": channel,
            "template": template,
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
) -> tuple[str | None, bool]:
    """Provider id of the message sent, and whether the options went out with it."""
    if channel == "WHATSAPP":
        text = whatsapp_markup(text)
        last_inbound = conversation.get("lastWhatsappInboundAt")
        if interactive:
            return _send_whatsapp_interactive(
                address, text, last_inbound, interactive, conversation.get("lastInboundLocale")
            )
        return _send_whatsapp(address, text, last_inbound), False
    if channel == "EMAIL":
        _send_email(address, text, conversation)
        return None, False
    if channel == "SMS":
        options = [(o.id, o.title) for o in interactive.options] if interactive else []
        return _send_rcs(address, text, options), bool(options)
    raise ChannelUnavailableError


def whatsapp_markup(text: str) -> str:
    """Markdown the model writes (`**bold**`, `# heading`) as WhatsApp bold (`*bold*`), T-68."""
    text = _MD_HEADING.sub(lambda m: "*" + m.group(1).replace("*", "") + "*", text)
    return _MD_BOLD.sub(r"*\1*", text)


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
) -> tuple[str, bool]:
    """Buttons when the options fit (at most 3, short titles), a list otherwise. A text longer
    than the interactive body goes out first as a plain message; the buttons follow with a short
    question. The id returned is the interactive message's: the one a tap replies to.

    If the interactive message fails, the reply still goes out once, without the options (the
    contact answers in words): the text already sent, or the text alone. Never raised after a part
    of the reply went out, so a retry cannot send it twice."""
    _check_window(last_inbound)
    language = "en" if (locale or "").lower().startswith("en") else "it"
    body = text
    text_id = None
    if len(text) > INTERACTIVE_BODY_LIMIT:
        text_id = _whatsapp(
            {"to": address, "type": "text", "text": {"body": text[:WHATSAPP_TEXT_LIMIT]}}
        )
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
    try:
        return _whatsapp({"to": address, "type": "interactive", "interactive": content}), True
    except Exception as e:
        if text_id is None and not isinstance(e, ClientError):
            raise  # nothing went out (e.g. a timeout): the caller retries the whole reply
        code = e.response["Error"]["Code"] if isinstance(e, ClientError) else type(e).__name__
        logger.warning("interactive message refused: reply sent without options", error=code)
    if text_id is not None:
        return text_id, False
    return _send_whatsapp(address, text, last_inbound), False


def _whatsapp(message: dict[str, Any]) -> str:
    response = _social().send_whatsapp_message(
        originationPhoneNumberId=_phone_number_id(),
        message=json.dumps({"messaging_product": "whatsapp", **message}).encode(),
        metaApiVersion="v20.0",
    )
    return str(response.get("messageId", ""))  # an empty id is simply not stored


def _send_email(address: str, text: str, conversation: dict[str, Any]) -> None:
    """In the thread of the contact's last email (T-26b): "Re: <their subject>" and In-Reply-To /
    References, which the Router stored only if printable ASCII (what SES accepts)."""
    sender = _param("SES_FROM_PARAM")
    if sender == "UNSET":
        raise ChannelUnavailableError
    thread = str(conversation.get("lastEmailSubject") or "")
    if not thread:
        subject = SUBJECTS.get(conversation.get("lastInboundLocale") or "", SUBJECTS["it-IT"])
    else:
        subject = thread if REPLY_SUBJECT.match(thread) else f"Re: {thread}"
    simple: dict[str, Any] = {
        "Subject": {"Data": subject, "Charset": "UTF-8"},
        "Body": {"Text": {"Data": text, "Charset": "UTF-8"}},
    }
    if parent := conversation.get("lastEmailMessageId"):
        simple["Headers"] = [
            {"Name": "In-Reply-To", "Value": parent},
            {"Name": "References", "Value": parent},
        ]
    _ses().send_email(
        FromEmailAddress=sender,
        Destination={"ToAddresses": [address]},
        Content={"Simple": simple},
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
    extra: dict[str, Any] = {"sentBy": request.sentBy} if request.sentBy else {}
    if interactive:  # what the contact could tap (console, simulator)
        extra["interactive"] = interactive.model_dump(exclude_none=True)
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
    extra: dict[str, Any],
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


# --- WhatsApp templates: proactive reorder (T-52, F-13) and delivery day (F-12) ------------

REORDER_TEMPLATE = "reorder_suggestion"
DELIVERY_TEMPLATE = "delivery_update"
# Quick-reply payloads (ours, sent with the template) and the labels approved by Meta, in the
# order of the template's buttons (`whatsapp_templates/*.json`, checked by the tests).
TEMPLATE_BUTTONS: dict[str, dict[str, list[tuple[str, str]]]] = {
    REORDER_TEMPLATE: {
        "it": [
            ("reorder_same", "Riordina uguale"),
            ("reorder_modify", "Modifica"),
            ("reorder_no", "No grazie"),
            ("reorder_stop", "Stop proposte"),
        ],
        "en": [
            ("reorder_same", "Reorder same"),
            ("reorder_modify", "Change"),
            ("reorder_no", "No thanks"),
            ("reorder_stop", "Stop suggestions"),
        ],
    },
    DELIVERY_TEMPLATE: {
        "it": [("delivery_received", "Ricevuto"), ("delivery_issue", "Segnala problema")],
        "en": [("delivery_received", "Received"), ("delivery_issue", "Report a problem")],
    },
}
MAX_REORDER_PRODUCTS = 3
DAYS = {
    "it": ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"),
    "en": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
}
MONTHS = {
    "it": (
        "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
        "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
    ),
    "en": (
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ),
}  # fmt: skip
AND = {"it": " e ", "en": " and "}


def _lang(contact: dict[str, Any]) -> str:
    return "en" if str(contact.get("language", "it")).startswith("en") else "it"


def _day(value: date, language: str, weekday: bool = False) -> str:
    text = f"{value.day} {MONTHS[language][value.month - 1]}"
    return f"{DAYS[language][value.weekday()]} {text}" if weekday else text


def _first_name(contact: dict[str, Any], customer: dict[str, Any]) -> str:
    name = str(contact.get("name") or "").split()
    return name[0] if name else str(customer.get("venueName") or "")


def _whatsapp_conversation(contact_id: str) -> dict[str, Any] | None:
    """The contact's conversation whose last verified message came from WhatsApp (the newest one):
    the template goes to that address, never to one taken from the event."""
    items = table("conversations").query(
        IndexName="by-contactId", KeyConditionExpression=Key("contactId").eq(contact_id)
    )["Items"]
    on_whatsapp = [c for c in items if c.get("lastInboundChannel") == "WHATSAPP"]
    on_whatsapp.sort(key=lambda c: str(c.get("lastMessageAt", "")), reverse=True)
    return on_whatsapp[0] if on_whatsapp else None


def _reorder_due(detail: dict[str, Any]) -> dict[str, str]:
    """`reorder_suggestion` to the venue's consenting contacts on WhatsApp (F-13.3). Consent and
    status are read again: they may have changed since the trigger ran."""
    customer_id = str(detail.get("customerId", ""))
    logger.set_correlation_id(customer_id)
    customer = table("customers").get_item(Key={"customerId": customer_id}).get("Item")
    skus = [str(s) for s in detail.get("skus", [])][:MAX_REORDER_PRODUCTS]
    if not customer or not skus:
        raise InvalidInputError
    names = [
        str(p["name"])
        for sku in skus
        if (p := table("products").get_item(Key={"sku": sku}).get("Item"))
    ]
    if not names:
        raise InvalidInputError
    last = table("order-history").query(
        KeyConditionExpression=Key("customerId").eq(customer_id), ScanIndexForward=False, Limit=1
    )["Items"]
    last_date = date.fromisoformat(str(last[0]["date"])[:10]) if last else None
    dates, _ = delivery_dates(
        customer["deliveryDays"],
        calendar_closed(customer["zone"]),
        datetime.now(UTC),
        parse_cutoff(os.environ["DELIVERY_CUTOFF"]),
        1,
    )
    if not dates or not last_date:
        raise InvalidInputError
    statuses: list[str] = []
    for contact_id in detail.get("contactIds", []):
        contact = table("contacts").get_item(Key={"contactId": str(contact_id)}).get("Item")
        if not (
            contact
            and contact.get("status") == "VERIFIED"
            and contact.get("proactiveConsent") is True
            and customer_id in contact.get("customerIds", [])
        ):
            statuses.append("NO_CONSENT")
            continue
        language = _lang(contact)
        products = ", ".join(n.lower() for n in names[:-1])
        products = f"{products}{AND[language]}{names[-1].lower()}" if products else names[0].lower()
        statuses.append(
            _send_template(
                str(contact_id),
                REORDER_TEMPLATE,
                language,
                [
                    _first_name(contact, customer),
                    products,
                    _day(last_date, language),
                    _day(dates[0], language, weekday=True),
                ],
                f"reorder#{customer_id}#{contact_id}#{date.today().isoformat()}",
                {"customerId": customer_id},
            )
        )
    logger.info("reorder suggestions", statuses=statuses)
    return {"status": ",".join(statuses) or "NO_CONTACT"}


def _delivery_update(detail: dict[str, Any]) -> dict[str, str]:
    """The delivery message when the order leaves (F-12.1), to the customer contact who placed it
    (an order placed by a sales rep: none): RCS with suggested replies if the contact has a
    verified `SMS#` identity, otherwise (or if RCS refuses it) the `delivery_update` template on
    WhatsApp."""
    if detail.get("to") != "OUT_FOR_DELIVERY":
        return {"status": "SKIPPED"}
    order_id = parse_order_id(detail.get("orderId"))
    logger.set_correlation_id(order_id)
    order = table("orders").get_item(Key={"orderId": order_id}).get("Item")
    if not order:
        raise NotFoundError
    contact_id = str(order.get("confirmedBy") or order.get("createdBy") or "")
    contact = table("contacts").get_item(Key={"contactId": contact_id}).get("Item")
    if not contact_id.startswith("con_") or not contact:
        return {"status": "NO_CONTACT"}
    delivery = table("deliveries").get_item(Key={"orderId": order_id}).get("Item") or {}
    start, _, end = str(delivery.get("window", "")).partition("-")
    if not end:
        raise InvalidInputError
    customer = table("customers").get_item(Key={"customerId": order["customerId"]}).get("Item")
    language = _lang(contact)
    if address := _sms_address(contact_id):  # F-12.1: RCS, SMS fallback (FN-18)
        try:
            return {
                "status": _send_sms_message(
                    f"delivery-sms#{order_id}",
                    order.get("conversationId"),
                    address,
                    DELIVERY_SMS[language].format(
                        name=_first_name(contact, customer or {}),
                        order=order_id,
                        start=start,
                        end=end,
                    ),
                    TEMPLATE_BUTTONS[DELIVERY_TEMPLATE][language],
                    {"orderId": order_id, "template": "delivery_update_rcs"},
                    has_fallback=True,
                )
            }
        except (ChannelUnavailableError, ClientError) as e:  # F-11.C7: the WhatsApp template
            logger.warning("rcs refused: whatsapp template instead", error=type(e).__name__)
    return {
        "status": _send_template(
            contact_id,
            DELIVERY_TEMPLATE,
            _lang(contact),
            [_first_name(contact, customer or {}), order_id, start, end],
            f"delivery#{order_id}",
            {"orderId": order_id},
        )
    }


def _send_template(
    contact_id: str,
    name: str,
    language: str,
    params: list[str],
    key: str,
    extra: dict[str, Any],
) -> str:
    conversation = _whatsapp_conversation(contact_id)
    if not conversation or not conversation.get("lastInboundFrom"):
        return "NO_WHATSAPP"  # RCS / SMS for contacts without WhatsApp arrive with T-27
    if conversation.get("mode") == "HUMAN":
        return "HANDOFF"  # an operator has the conversation: no automatic message
    conversation_id = str(conversation["conversationId"])
    if not _claim(key):
        if _is_done(key):
            return "DUPLICATE"
        raise SendInProgressError
    buttons = TEMPLATE_BUTTONS[name][language]
    sandbox = _sandbox()
    try:
        if sandbox:
            provider_id: str | None = _sandbox_id(key)
        else:
            provider_id = _whatsapp(
                {
                    "to": conversation["lastInboundFrom"],
                    "type": "template",
                    "template": {
                        "name": name,
                        "language": {"code": language},
                        "components": [
                            {
                                "type": "body",
                                "parameters": [{"type": "text", "text": p} for p in params],
                            },
                            *(
                                {
                                    "type": "button",
                                    "sub_type": "quick_reply",
                                    "index": str(i),
                                    "parameters": [{"type": "payload", "payload": button_id}],
                                }
                                for i, (button_id, _) in enumerate(buttons)
                            ),
                        ],
                    },
                }
            )
    except Exception:
        _unclaim(key)
        _event("notification.failed", conversation_id, "WHATSAPP", sandbox, name)
        raise
    _done(key)
    status = "SANDBOX" if sandbox else "SENT"
    try:
        _store(
            conversation_id,
            key,
            "WHATSAPP",
            f"[{name}] " + " · ".join(params),
            provider_id,
            status,
            {
                **extra,
                "template": name,
                "interactive": {
                    "kind": "TEMPLATE",
                    "options": [{"id": i, "title": t} for i, t in buttons],
                },
            },
        )
        _event("notification.sent", conversation_id, "WHATSAPP", sandbox, name)
    except Exception:
        logger.exception("sent, but not recorded")
    logger.info("template sent", template=name, sandbox=sandbox)
    return status


# --- SMS / RCS (T-27, FN-15, FN-18) -----------------------------------------------------------

# RCS limits: text body 3072 characters, suggestion text 25, at most 11 suggestions. The SMS
# fallback (sender ID, one-way in Italy) is a notification: no options to answer (F-11.C4).
RCS_TEXT_LIMIT = 3072
RCS_SUGGESTION_LIMIT = 25
RCS_MAX_SUGGESTIONS = 11
SMS_FALLBACK_LIMIT = 300
SMS_CONFIRMATION = {
    "it": "Ordine {order} confermato, consegna {date}. Conferma con il PDF via email.",
    "en": "Order {order} confirmed, delivery on {date}. Confirmation with the PDF by email.",
}
SMS_UPDATED = {
    "it": "Ordine {order} aggiornato, consegna {date}.",
    "en": "Order {order} updated, delivery on {date}.",
}
DELIVERY_SMS = {
    "it": "Ciao {name}, l'ordine {order} arriva oggi tra le {start} e le {end}. "
    "Quando arriva, facci sapere se è tutto a posto.",
    "en": "Hi {name}, order {order} will be delivered today between {start} and {end}. "
    "When it arrives, let us know if everything is fine.",
}


def _sms_param(env_name: str) -> str:
    value = _param(env_name)
    if value == "UNSET":
        raise ChannelUnavailableError
    return value


def _send_rcs(address: str, text: str, options: list[tuple[str, str]]) -> str:
    """An RCS text from the agent, with suggested replies for the options (their postback is the
    option id, back to the Router as `interactiveReply`); a phone without RCS gets the SMS
    fallback from the sender ID, without the options."""
    content: dict[str, Any] = {"Content": {"TextMessage": {"Body": text[:RCS_TEXT_LIMIT]}}}
    if options:
        content["Suggestions"] = [
            {"Reply": {"Text": title[:RCS_SUGGESTION_LIMIT], "PostbackData": option_id}}
            for option_id, title in options[:RCS_MAX_SUGGESTIONS]
        ]
    response = _sms().send_rcs_message(
        DestinationPhoneNumber=address,
        OriginationIdentity=_sms_param("RCS_AGENT_PARAM"),
        RcsMessageContent=content,
        MessageTrafficType="TRANSACTIONAL",
        FallbackConfiguration={
            "Channel": "SMS",
            "OriginationIdentity": _sms_param("SMS_SENDER_PARAM"),
            "MessageBody": text
            if len(text) <= SMS_FALLBACK_LIMIT
            else text[: SMS_FALLBACK_LIMIT - 1] + "…",
        },
        ConfigurationSetName=_sms_param("SMS_CONFIGURATION_SET_PARAM"),
    )
    return str(response.get("MessageId", ""))


def _sms_address(contact_id: str) -> str | None:
    """The contact's verified `SMS#` identity: SMS/RCS only to a number given for it, never to
    the WhatsApp number (testers only for the RCS test agent, SMS sandbox)."""
    items = table("channel-identities").query(
        IndexName="by-contactId", KeyConditionExpression=Key("contactId").eq(contact_id)
    )["Items"]
    for item in items:
        if item.get("channel") == "SMS" and item.get("verified") is True:
            return str(item["channelAddress"]).removeprefix("SMS#")
    return None


def _send_sms_message(
    key: str,
    conversation_id: str | None,
    address: str,
    text: str,
    options: list[tuple[str, str]],
    extra: dict[str, Any],
    has_fallback: bool = False,
) -> str:
    """One idempotent RCS/SMS send, recorded in the conversation (if any). With `has_fallback`
    the caller sends on another channel when this fails: no `notification.failed`."""
    if not _claim(key):
        if _is_done(key):
            return "DUPLICATE"
        raise SendInProgressError
    sandbox = _sandbox()
    try:
        provider_id: str | None = _sandbox_id(key) if sandbox else _send_rcs(address, text, options)
    except Exception:
        _unclaim(key)
        if not has_fallback:
            _event(
                "notification.failed", conversation_id or "", "SMS", sandbox, extra.get("template")
            )
        raise
    _done(key)
    status = "SANDBOX" if sandbox else "SENT"
    try:
        if conversation_id:
            if options:
                extra = extra | {
                    "interactive": {
                        "kind": "SUGGESTIONS",
                        "options": [{"id": i, "title": t} for i, t in options],
                    }
                }
            _store(conversation_id, key, "SMS", text, provider_id, status, extra)
        _event("notification.sent", conversation_id or "", "SMS", sandbox, extra.get("template"))
    except Exception:
        logger.exception("sent, but not recorded")
    logger.info("rcs sent", sandbox=sandbox)  # never the number (AGENTS §7)
    return status


def _order_sms(detail: dict[str, Any]) -> None:
    """Short RCS/SMS confirmation next to the email (FN-15, F-11), once per order revision, to the
    customer contact who confirmed and has a verified `SMS#` identity. Best effort: the email
    goes out anyway, a failure here is logged (the retry of the event sends it again)."""
    try:
        order_id = parse_order_id(detail.get("orderId"))
        order = table("orders").get_item(Key={"orderId": order_id}).get("Item")
        if not order or order["status"] not in EMAILED_STATUSES:
            return
        contact_id = str(order.get("confirmedBy") or order.get("createdBy") or "")
        address = _sms_address(contact_id) if contact_id.startswith("con_") else None
        if not address:
            return
        language = "en" if _language(contact_id).startswith("en") else "it"
        when = _day(date.fromisoformat(str(order["deliveryDate"])[:10]), language, weekday=True)
        texts = SMS_UPDATED if detail.get("reason") == "updated" else SMS_CONFIRMATION
        revision = int(detail.get("revision", order.get("revision", 0)))
        _send_sms_message(
            f"order-sms#{order_id}#{revision}",
            order.get("conversationId"),
            address,
            texts[language].format(order=order_id, date=when),
            [],
            {"orderId": order_id, "template": "order_confirmation_sms"},
        )
    except ChannelUnavailableError:
        logger.info("rcs not configured: no order sms")
    except Exception:
        logger.exception("order sms not sent")


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
