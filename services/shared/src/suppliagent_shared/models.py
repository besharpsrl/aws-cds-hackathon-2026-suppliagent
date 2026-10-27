"""DynamoDB item models (INFRASTRUCTURE_DESIGN §5.7). Dates are UTC ISO-8601 strings."""

# ruff: noqa: N815 - field names are the camelCase wire/DynamoDB attribute names (02 §6).

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, ValidationError

from suppliagent_shared.errors import InvalidInputError

CustomerId = Annotated[str, StringConstraints(pattern=r"^cus_\w+$")]
ContactId = Annotated[str, StringConstraints(pattern=r"^con_\w+$")]
RepId = Annotated[str, StringConstraints(pattern=r"^rep_\w+$")]
OrderId = Annotated[str, StringConstraints(pattern=r"^ord_\w+$")]
_ORDER_ID = TypeAdapter(OrderId)


def parse_order_id(value: object) -> str:
    """An `ord_` id from an untrusted request, or `InvalidInputError`."""
    try:
        return _ORDER_ID.validate_python(value)
    except ValidationError as exc:
        raise InvalidInputError from exc


Weekday = Annotated[str, StringConstraints(pattern=r"^(MON|TUE|WED|THU|FRI|SAT|SUN)$")]


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Role(StrEnum):
    CUSTOMER_CONTACT = "CUSTOMER_CONTACT"
    SALES_REP = "SALES_REP"
    UNKNOWN = "UNKNOWN"


class Channel(StrEnum):
    WHATSAPP = "WHATSAPP"
    EMAIL = "EMAIL"
    SMS = "SMS"


class Language(StrEnum):
    IT = "it"
    EN = "en"


class ContactStatus(StrEnum):
    VERIFIED = "VERIFIED"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"


class Customer(Item):
    customerId: CustomerId
    customerCode: str
    vatNumber: str
    venueName: str
    legalName: str
    venueType: str
    city: str
    zone: str
    deliveryDays: list[Weekday]
    repId: RepId
    priceListId: str


class Contact(Item):
    contactId: ContactId
    name: str | None = None  # unknown for contacts self-identified via identify_contact
    customerId: CustomerId  # primary venue (GSI `by-customerId`)
    customerIds: list[CustomerId]  # every venue the contact orders for
    language: Language
    status: ContactStatus
    privacyNoticeSentAt: str | None = None
    proactiveConsent: bool | None = None


class SalesRep(Item):
    """Portfolio = customers whose `repId` is this rep (GSI `by-repId`), not a list here."""

    repId: RepId
    name: str
    zones: list[str]
    language: Language


class ChannelIdentity(Item):
    channelAddress: str = Field(pattern=r"^(WHATSAPP|SMS)#\+\d{8,15}$|^EMAIL#[^@\s]+@[^@\s]+$")
    channel: Channel
    contactId: ContactId | RepId  # sales reps are addressed by `repId`
    role: Role
    verified: bool
    # Set by identify_contact: the router keeps routing this address to the conversation in which
    # it was identified, so session, handoff and buffer survive the identification.
    conversationId: str | None = None


class OrderLine(Item):
    sku: str
    description: str
    quantity: float = Field(gt=0)
    unit: str


class OrderHistoryEntry(Item):
    customerId: CustomerId
    dateOrderId: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}#ord_\w+$")
    orderId: OrderId
    date: str
    lines: list[OrderLine]


class ExpectedReorder(Item):
    sku: str
    everyDays: int = Field(gt=0)
    lastOrderedAt: str
    dueAt: str


class Suggestion(Item):
    sku: str
    reason: str


class CustomerInsights(Item):
    customerId: CustomerId
    expectedReorders: list[ExpectedReorder]
    droppedProducts: list[str]
    suggestions: list[Suggestion]
    updatedAt: str
