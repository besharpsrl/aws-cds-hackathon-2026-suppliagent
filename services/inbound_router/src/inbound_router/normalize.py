"""Channel events -> RawMessage (TECHNICAL_FLOWS §3.1). Pure: no AWS calls, no identity."""

import html
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr
from typing import Any

from suppliagent_shared.messages import Attachment, AttachmentType, InteractiveReply
from suppliagent_shared.models import Channel

MEDIA_TYPES = {t.value for t in AttachmentType}
ORDER_ADDRESS = re.compile(r"^ordine\+(ord_\w+)@(.+)$", re.IGNORECASE)
# Keeps a message well under the DynamoDB item limit and the model's context.
MAX_TEXT_CHARS = 4000
HIDDEN_HTML = re.compile(r"<(script|style)\b.*?</\1\s*>|<!--.*?-->", re.IGNORECASE | re.DOTALL)
# Start of the quoted part of a reply (English and Italian clients).
QUOTE_START = re.compile(
    r"^(>|-+ ?(original message|messaggio originale)|(on|il) .+ (wrote|ha scritto):?$)",
    re.IGNORECASE,
)
# "Re:", "R:", "Rif:", "AW:", "SV:": the subject of a reply only repeats the thread's.
REPLY_SUBJECT = re.compile(r"^\s*(re|r|rif|aw|sv)\s*:", re.IGNORECASE)
# Kept to thread our answer (In-Reply-To): printable ASCII, as SES accepts in a header value.
MESSAGE_ID = re.compile(r"^<[!-~]{1,900}>$")


@dataclass(frozen=True)
class EmailFile:
    """An email attachment, before upload (T-23). The sender's file name is not kept."""

    mime_type: str
    content: bytes


@dataclass(frozen=True)
class RawMessage:
    """A message before identity resolution."""

    channel: Channel
    provider_message_id: str
    sender: str  # E.164 number (WhatsApp) or lowercase address (email)
    received_at: str
    text: str | None = None
    attachments: tuple[Attachment, ...] = ()
    files: tuple[EmailFile, ...] = ()
    files_scanned: bool = True  # SES virus scan PASS; otherwise no file is stored (E-13)
    interactive_reply: InteractiveReply | None = None
    order_id: str | None = None
    # False when the channel cannot vouch for `sender`: the router then treats it as UNKNOWN.
    sender_verified: bool = True
    # Email only: the reply goes out in the same thread (subject "Re: …", In-Reply-To).
    email_subject: str | None = None
    email_message_id: str | None = None


def is_whatsapp(event: dict[str, Any]) -> bool:
    return "whatsAppWebhookEntry" in event


def is_email(event: dict[str, Any]) -> bool:
    return event.get("notificationType") == "Received"


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def whatsapp_messages(event: dict[str, Any]) -> list[RawMessage]:
    """Messages of an EUM Social event. Delivery statuses and reactions are not messages: delivery
    events are the Notifier's (T-24)."""
    # `message_timestamp` is when AWS received the event: finer than WhatsApp's own seconds, so
    # messages of a burst keep their order, and the same on every redelivery. Messages of the same
    # event share it: 1 ms apart each, in the order WhatsApp lists them.
    arrived = datetime.fromisoformat(event["message_timestamp"])
    entry = json.loads(event["whatsAppWebhookEntry"])
    messages: list[RawMessage] = []
    for change in entry.get("changes", []):
        for m in change.get("value", {}).get("messages", []):
            if m["type"] == "reaction":
                continue
            text, attachments, reply = _whatsapp_content(m)
            messages.append(
                RawMessage(
                    channel=Channel.WHATSAPP,
                    provider_message_id=m["id"],
                    sender="+" + m["from"].lstrip("+"),
                    received_at=_iso(arrived + timedelta(milliseconds=len(messages))),
                    text=text,
                    attachments=attachments,
                    interactive_reply=reply,
                )
            )
    return messages


def _whatsapp_content(
    m: dict[str, Any],
) -> tuple[str | None, tuple[Attachment, ...], InteractiveReply | None]:
    kind = m["type"]
    if kind == "text":
        return m["text"]["body"], (), None
    if kind in MEDIA_TYPES:
        media = m[kind]
        attachment = Attachment(
            type=AttachmentType(kind), mimeType=media.get("mime_type"), mediaId=media.get("id")
        )
        return media.get("caption"), (attachment,), None
    if kind == "interactive":
        interactive = m["interactive"]
        reply = interactive.get("button_reply") or interactive.get("list_reply")
        if not reply:
            return None, (), None
        return (
            None,
            (),
            InteractiveReply(id=reply["id"], title=reply["title"], contextId=_context(m)),
        )
    if kind == "button":  # quick reply of a template
        button = m["button"]
        return (
            None,
            (),
            InteractiveReply(id=button["payload"], title=button["text"], contextId=_context(m)),
        )
    # location, contacts, unsupported: stored anyway, the agent asks for text or a photo
    return None, (), None


def _context(m: dict[str, Any]) -> str | None:
    context_id = m.get("context", {}).get("id")
    return str(context_id) if context_id else None


def email_message(notification: dict[str, Any], raw: bytes, order_domain: str = "") -> RawMessage:
    """A mail received by SES: `notification` is the receipt rule's SNS message, `raw` the S3
    object. `ordine+<orderId>@` counts only on `order_domain` and from a verified sender."""
    mail = notification["mail"]
    receipt = notification.get("receipt", {})
    msg = message_from_bytes(raw, policy=policy.default)
    subject = " ".join(str(msg.get("Subject", "")).split())
    body = _clean_body(msg)
    shown_subject = "" if REPLY_SUBJECT.match(subject) else subject
    text = "\n".join(part for part in (shown_subject, body) if part) or None
    if text and len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + " […]"
    sender = parseaddr(str(msg.get("From", "")))[1].lower()
    verified = _from_verified(receipt, msg, mail, sender)
    order_ids = (
        m.group(1)
        for d in mail.get("destination", [])
        if (m := ORDER_ADDRESS.match(d)) and order_domain and m.group(2).lower() == order_domain
    )
    message_id = str(msg.get("Message-ID", "")).strip()
    return RawMessage(
        channel=Channel.EMAIL,
        provider_message_id=mail["messageId"],
        sender=sender,
        received_at=_iso(datetime.fromisoformat(mail["timestamp"])),
        text=text,
        files=_files(msg),
        files_scanned=receipt.get("virusVerdict", {}).get("status") == "PASS",
        order_id=next(order_ids, None) if verified else None,
        sender_verified=verified,
        email_subject=subject[:200] or None,
        email_message_id=message_id if MESSAGE_ID.match(message_id) else None,
    )


def _files(msg: EmailMessage) -> tuple[EmailFile, ...]:
    files: list[EmailFile] = []
    for part in msg.iter_attachments():
        content = part.get_payload(decode=True)
        if isinstance(content, bytes):  # not a nested message/rfc822
            files.append(EmailFile(part.get_content_type(), content))
    return tuple(files)


def _from_verified(
    receipt: dict[str, Any], msg: EmailMessage, mail: dict[str, Any], sender: str
) -> bool:
    """Only DMARC checks that SPF or DKIM align with the `From` domain: without a DMARC PASS
    anyone could claim a contact's address (INFRASTRUCTURE_DESIGN §5.3.2). The `From` must also
    be a single address, the same SES evaluated."""
    if receipt.get("dmarcVerdict", {}).get("status") != "PASS":
        return False
    froms = getaddresses([str(f) for f in msg.get_all("From") or []])
    if len(froms) != 1 or not sender:
        return False
    common = mail.get("commonHeaders", {}).get("from") or []
    return all(parseaddr(c)[1].lower() == sender for c in common)


def _clean_body(msg: EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    content = part.get_content()
    if part.get_content_type() == "text/html":
        # Hidden blocks first: text a person never sees must not reach the agent either.
        content = html.unescape(re.sub(r"<[^>]+>", " ", HIDDEN_HTML.sub(" ", content)))
    lines: list[str] = []
    for line in content.splitlines():
        if QUOTE_START.match(line.strip()):
            break
        lines.append(line.rstrip())
    return "\n".join(lines).strip()
