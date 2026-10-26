"""Channel events -> RawMessage (TECHNICAL_FLOWS §3.1). Pure: no AWS calls, no identity."""

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Any

from suppliagent_shared.messages import Attachment, AttachmentType, InteractiveReply
from suppliagent_shared.models import Channel

MEDIA_TYPES = {t.value for t in AttachmentType}
ORDER_ADDRESS = re.compile(r"^ordine\+(ord_\w+)@", re.IGNORECASE)
# Start of the quoted part of a reply (English and Italian clients).
QUOTE_START = re.compile(
    r"^(>|-+ ?(original message|messaggio originale)|(on|il) .+ (wrote|ha scritto):?$)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RawMessage:
    """A message before identity resolution."""

    channel: Channel
    provider_message_id: str
    sender: str  # E.164 number (WhatsApp) or lowercase address (email)
    received_at: str
    text: str | None = None
    attachments: tuple[Attachment, ...] = ()
    interactive_reply: InteractiveReply | None = None
    order_id: str | None = None
    # False when the channel cannot vouch for `sender`: the router then treats it as UNKNOWN.
    sender_verified: bool = True


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
        return None, (), InteractiveReply(id=reply["id"], title=reply["title"]) if reply else None
    if kind == "button":  # quick reply of a template
        return None, (), InteractiveReply(id=m["button"]["payload"], title=m["button"]["text"])
    # location, contacts, unsupported: stored anyway, the agent asks for text or a photo
    return None, (), None


def email_message(notification: dict[str, Any], raw: bytes) -> RawMessage:
    """A mail received by SES: `notification` is the receipt rule's SNS message, `raw` the S3
    object. Attachments (photos, PDF, Excel) arrive with T-23."""
    mail = notification["mail"]
    msg = message_from_bytes(raw, policy=policy.default)
    subject = str(msg.get("Subject", "")).strip()
    body = _clean_body(msg)
    text = "\n".join(part for part in (subject, body) if part) or None
    order_ids = (m.group(1) for d in mail.get("destination", []) if (m := ORDER_ADDRESS.match(d)))
    return RawMessage(
        channel=Channel.EMAIL,
        provider_message_id=mail["messageId"],
        sender=parseaddr(str(msg.get("From", "")))[1].lower(),
        received_at=_iso(datetime.fromisoformat(mail["timestamp"])),
        text=text,
        order_id=next(order_ids, None),
        sender_verified=_from_verified(notification.get("receipt", {})),
    )


def _from_verified(receipt: dict[str, Any]) -> bool:
    """Only DMARC checks that SPF or DKIM align with the `From` domain: without a DMARC PASS
    anyone could claim a contact's address (INFRASTRUCTURE_DESIGN §5.3.2)."""
    return bool(receipt.get("dmarcVerdict", {}).get("status") == "PASS")


def _clean_body(msg: EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    content = part.get_content()
    if part.get_content_type() == "text/html":
        content = re.sub(r"<[^>]+>", " ", content)  # ponytail: tags stripped, not rendered
    lines: list[str] = []
    for line in content.splitlines():
        if QUOTE_START.match(line.strip()):
            break
        lines.append(line.rstrip())
    return "\n".join(lines).strip()
