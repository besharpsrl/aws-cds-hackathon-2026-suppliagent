"""identify_contact, get_customer_profile and update_privacy (FN-02, FN-03, F-01, F-02,
TECHNICAL_FLOWS §3.2 and §6.5)."""

# ruff: noqa: N815 - field names are the camelCase wire names (02 §6).

import os
import re
import unicodedata
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Any, cast
from uuid import uuid4

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError
from pydantic import BaseModel, ConfigDict, Field
from suppliagent_shared.auth import CallerContext, caller_scope
from suppliagent_shared.aws import put_event, table
from suppliagent_shared.errors import AccessDeniedError, InvalidInputError, NotFoundError
from suppliagent_shared.models import (
    ChannelIdentity,
    Contact,
    ContactStatus,
    CustomerId,
    Language,
    Role,
)

SOURCE = "suppliagent.tool-customers"
VENUE_SIMILARITY = 0.8
# F-02.C4, per conversation; SSM parameter identificationMaxAttempts, passed by CDK as env var
MAX_IDENTIFY_ATTEMPTS = int(os.environ.get("IDENTIFICATION_MAX_ATTEMPTS", "3"))
LAST_ORDERS = 5
VENUE_FIELDS = ("customerId", "venueName", "venueType", "city", "deliveryDays")
INTERNAL_FIELDS = ("legalName", "zone", "priceListId", "repId")  # sales reps only


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    caller: CallerContext  # set by the agent code, never by the model


class IdentifyContactInput(ToolInput):
    customerCode: str | None = Field(None, max_length=32)
    vatNumber: str | None = Field(None, max_length=20)
    venueName: str | None = Field(None, max_length=120)
    language: Language = Language.IT
    # F-01: the privacy notice was already sent to this unregistered caller; stored on the contact
    privacyNoticeSent: bool = False


class GetCustomerProfileInput(ToolInput):
    customerId: CustomerId


class UpdatePrivacyInput(ToolInput):
    noticeSent: bool = False
    proactiveConsent: bool | None = None


def identify_contact(args: IdentifyContactInput) -> dict[str, Any]:
    """Known caller: own contact and venues. Unknown caller: match a customer and register the
    caller's address as a contact pending verification (F-02 step 3), or verified at once for a
    test customer flagged `autoVerifyContacts` (F-02.C7)."""
    if args.caller.role is not Role.UNKNOWN:
        return _known(args.caller)
    if not (args.customerCode or args.vatNumber) or not args.venueName:
        raise InvalidInputError
    if not _attempt_allowed(args.caller):
        return {"status": "IDENTIFICATION_FAILED"}  # F-02.C4: the agent hands off
    match = _find_customer(args)
    if match is None:
        return {"status": "NOT_FOUND"}
    customer, method = match
    return _register(args, customer, method)


def get_customer_profile(args: GetCustomerProfileInput) -> dict[str, Any]:
    scope = caller_scope(args.caller)
    full = args.customerId in scope.customer_ids
    if not full and args.customerId not in scope.pending_customer_ids:
        raise AccessDeniedError
    customer = table("customers").get_item(Key={"customerId": args.customerId}).get("Item")
    if not customer:
        raise NotFoundError
    profile = {k: customer[k] for k in VENUE_FIELDS}
    if full:  # F-02.C2: no order history until the contact is verified
        orders = table("order-history").query(
            KeyConditionExpression=Key("customerId").eq(args.customerId),
            ScanIndexForward=False,
            Limit=LAST_ORDERS,
        )["Items"]
        profile["lastOrders"] = [
            {"orderId": o["orderId"], "date": o["date"], "lines": o["lines"]} for o in orders
        ]
    if args.caller.role is Role.SALES_REP:
        profile |= {k: customer[k] for k in INTERNAL_FIELDS}
        insights = table("customer-insights").get_item(Key={"customerId": args.customerId})
        profile["insights"] = {
            k: v for k, v in insights.get("Item", {}).items() if k != "customerId"
        }
    return profile


def update_privacy(args: UpdatePrivacyInput) -> dict[str, Any]:
    """Records that the privacy notice was sent and/or the contact's answer on proactive messages
    (F-01, FN-02). Customer contacts only, and only their own record."""
    caller = args.caller
    if caller.role is not Role.CUSTOMER_CONTACT or not caller.contactId:
        raise AccessDeniedError
    if not args.noticeSent and args.proactiveConsent is None:
        raise InvalidInputError
    now = _now()
    version = _notice_version()
    channel = caller.channelAddress.split("#", 1)[0]
    sets: list[str] = []
    values: dict[str, Any] = {}
    if args.noticeSent:  # the first notice stays on record
        sets += [
            "privacyNoticeSentAt = if_not_exists(privacyNoticeSentAt, :now)",
            "privacyNoticeVersion = if_not_exists(privacyNoticeVersion, :version)",
        ]
        values |= {":now": now, ":version": version}
    if args.proactiveConsent is not None:  # the latest answer wins: "stop" revokes at any time
        sets += [
            "proactiveConsent = :consent",
            "proactiveConsentAt = :now",
            "proactiveConsentChannel = :channel",
            "proactiveConsentVersion = :version",
        ]
        values |= {
            ":consent": args.proactiveConsent,
            ":now": now,
            ":channel": channel,
            ":version": version,
        }
    try:
        updated = table("contacts").update_item(
            Key={"contactId": caller.contactId},
            UpdateExpression="SET " + ", ".join(sets),
            ConditionExpression="attribute_exists(contactId)",
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
        )["Attributes"]
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        raise NotFoundError from e
    detail: dict[str, Any] = {"contactId": caller.contactId, "channel": channel}
    if args.noticeSent:
        detail["noticeSent"] = True
    if args.proactiveConsent is not None:
        detail["proactiveConsent"] = args.proactiveConsent
    put_event(SOURCE, "contact.privacy_updated", detail)
    return {"status": "UPDATED", "privacy": _privacy(updated)}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _notice_version() -> str:
    return os.environ.get("PRIVACY_NOTICE_VERSION", "unversioned")


def _privacy(contact: dict[str, Any]) -> dict[str, Any]:
    """What the agent needs for F-01: was the notice sent, and the answer on proactive messages
    (None = never asked)."""
    return {
        "noticeSent": "privacyNoticeSentAt" in contact,
        "proactiveConsent": contact.get("proactiveConsent"),
    }


def _known(caller: CallerContext) -> dict[str, Any]:
    scope = caller_scope(caller)
    if scope.customer_ids:
        status, venues = ContactStatus.VERIFIED, scope.customer_ids
    elif scope.pending_customer_ids:
        status, venues = ContactStatus.PENDING_VERIFICATION, scope.pending_customer_ids
    else:
        return {"status": "NOT_FOUND"}
    known: dict[str, Any] = {
        "status": "KNOWN",
        "contact": {"contactId": caller.contactId, "status": status},
        "role": caller.role,
        "customers": _venues(sorted(venues)),
    }
    if caller.role is Role.CUSTOMER_CONTACT:  # a sales rep is staff: no privacy notice
        contact = table("contacts").get_item(Key={"contactId": caller.contactId}).get("Item", {})
        known["privacy"] = _privacy(contact)
    return known


def _venues(customer_ids: list[str]) -> list[dict[str, Any]]:
    # ponytail: one GetItem per venue (a contact has a handful); BatchGetItem if portfolios grow.
    customers = table("customers")
    items = (
        customers.get_item(Key={"customerId": cid}, ProjectionExpression="customerId, venueName")
        for cid in customer_ids
    )
    return [item["Item"] for item in items if "Item" in item]


def _attempt_allowed(caller: CallerContext) -> bool:
    """Counts identification attempts on the conversation; False once the limit is reached."""
    if not caller.conversationId:
        raise InvalidInputError
    # ponytail: per-conversation limit; a sender with unlimited new email addresses gets new
    # conversations, so add a per-sender-domain or global rate limit if that is abused.
    try:
        table("conversations").update_item(
            Key={"conversationId": caller.conversationId},
            UpdateExpression="ADD identifyAttempts :one",
            ConditionExpression="attribute_not_exists(identifyAttempts) OR identifyAttempts < :max",
            ExpressionAttributeValues={":one": 1, ":max": MAX_IDENTIFY_ATTEMPTS},
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        return False
    return True


def _find_customer(args: IdentifyContactInput) -> tuple[dict[str, Any], str] | None:
    if args.customerCode:
        method = "CUSTOMER_CODE"
        condition = Attr("customerCode").eq(args.customerCode.strip().upper())
    else:
        method = "VAT_NUMBER"
        vat = re.sub(r"[\s.]", "", args.vatNumber or "").upper()
        condition = Attr("vatNumber").eq(vat if vat[:2].isalpha() else f"IT{vat}")
    # ponytail: Scan with a filter on a registry of a few hundred venues; add a GSI on
    # customerCode/vatNumber (and paginate) if it grows past one 1 MB page.
    candidates = table("customers").scan(FilterExpression=condition)["Items"]
    for customer in candidates:
        if _same_venue(customer["venueName"], args.venueName or ""):
            return customer, method
    return None  # same answer for wrong code and wrong venue: no oracle on customer codes


def _normalize(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z0-9]+", ascii_text.casefold()))


def _same_venue(registered: str, given: str) -> bool:
    a, b = _normalize(registered), _normalize(given)
    if not a or not b:
        return False
    short, long_ = sorted((a, b), key=len)
    # "forno antico" matches "pizzeria il forno antico"; a bare "pizzeria" does not
    contained = short in long_ and len(short) >= len(long_) / 2
    return contained or SequenceMatcher(None, a, b).ratio() >= VENUE_SIMILARITY


def _register(args: IdentifyContactInput, customer: dict[str, Any], method: str) -> dict[str, Any]:
    caller = args.caller
    verified = customer.get("autoVerifyContacts") is True
    contact = Contact(
        contactId=f"con_{uuid4().hex[:12]}",
        customerId=customer["customerId"],
        customerIds=[customer["customerId"]],
        language=args.language,
        status=ContactStatus.VERIFIED if verified else ContactStatus.PENDING_VERIFICATION,
        privacyNoticeSentAt=_now() if args.privacyNoticeSent else None,
        privacyNoticeVersion=_notice_version() if args.privacyNoticeSent else None,
    )
    # model_validate: a malformed caller address is a ValidationError (INVALID_INPUT), not a crash
    identity = ChannelIdentity.model_validate(
        {
            "channelAddress": caller.channelAddress,
            "channel": caller.channelAddress.split("#", 1)[0],
            "contactId": contact.contactId,
            "role": Role.CUSTOMER_CONTACT,
            "verified": verified,
            "conversationId": caller.conversationId,
        }
    )
    # ponytail: two conditional writes, not a transaction; a crash in between leaves an
    # unreachable PENDING contact (no address points to it). TransactWriteItems if that matters.
    table("contacts").put_item(
        Item=contact.model_dump(mode="json", exclude_none=True),
        ConditionExpression="attribute_not_exists(contactId)",
    )
    try:
        table("channel-identities").put_item(
            Item=identity.model_dump(mode="json"),
            ConditionExpression="attribute_not_exists(channelAddress)",
            ReturnValuesOnConditionCheckFailure="ALL_OLD",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        # Address already registered (retry, race, or already a contact): never overwrite it,
        # answer with what the address is bound to.
        table("contacts").delete_item(Key={"contactId": contact.contactId})
        existing = cast(dict[str, Any], e.response)["Item"]  # low-level format
        return _known(
            CallerContext(
                role=existing["role"]["S"],
                contactId=existing["contactId"]["S"],
                channelAddress=caller.channelAddress,
                conversationId=caller.conversationId,
            )
        )
    put_event(
        SOURCE,
        "contact.identified",
        {"contactId": contact.contactId, "method": method, "verified": verified},
    )
    return {
        "status": "MATCHED",
        "contact": {"contactId": contact.contactId, "status": contact.status},
        "role": Role.CUSTOMER_CONTACT,
        "customers": [{"customerId": customer["customerId"], "venueName": customer["venueName"]}],
        "privacy": _privacy(contact.model_dump(mode="json", exclude_none=True)),
    }
