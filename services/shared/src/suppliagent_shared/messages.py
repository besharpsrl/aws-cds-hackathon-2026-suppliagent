"""NormalizedMessage: the channel-independent inbound message (INFRASTRUCTURE_DESIGN §5.2)."""

# ruff: noqa: N815 - field names are the camelCase wire/DynamoDB attribute names (02 §6).

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from suppliagent_shared.models import Channel, Role


class AttachmentType(StrEnum):
    IMAGE = "image"
    AUDIO = "audio"
    DOCUMENT = "document"
    VIDEO = "video"  # not processed: the agent asks for a photo or text (02 §3.4)
    STICKER = "sticker"


class Attachment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: AttachmentType
    mimeType: str | None = None
    mediaId: str | None = None  # provider media id; the router's media step (T-23) sets `s3Uri`
    s3Uri: str | None = None


class InteractiveReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    # Provider id of the message the button belonged to: a reply id alone can be forged, so
    # actions such as confirm_order must check this against what was actually sent.
    contextId: str | None = None


class NormalizedMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    messageId: str
    providerMessageId: str
    channel: Channel
    direction: Literal["INBOUND"] = "INBOUND"
    contactId: str | None = None  # `con_…`, or `rep_…` for a sales rep; None while UNKNOWN
    role: Role
    customerIds: list[str] = Field(default_factory=list)
    conversationId: str
    orderId: str | None = None
    from_: str = Field(alias="from")  # E.164 number or lowercase email address
    # False for an email without DMARC PASS: never bind it to a contact, never reply to it.
    senderVerified: bool = True
    text: str | None = None
    attachments: list[Attachment] = Field(default_factory=list)
    interactiveReply: InteractiveReply | None = None
    receivedAt: str  # UTC ISO-8601
    locale: str
