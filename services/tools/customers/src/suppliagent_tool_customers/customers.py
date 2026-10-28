"""identify_contact and get_customer_profile (FN-03, F-02, TECHNICAL_FLOWS §3.2 and §6.5)."""

# ruff: noqa: N815 - field names are the camelCase wire names (02 §6).

import os
import re
import unicodedata
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


class GetCustomerProfileInput(ToolInput):
    customerId: CustomerId


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


def _known(caller: CallerContext) -> dict[str, Any]:
    scope = caller_scope(caller)
    if scope.customer_ids:
        status, venues = ContactStatus.VERIFIED, scope.customer_ids
    elif scope.pending_customer_ids:
        status, venues = ContactStatus.PENDING_VERIFICATION, scope.pending_customer_ids
    else:
        return {"status": "NOT_FOUND"}
    return {
        "status": "KNOWN",
        "contact": {"contactId": caller.contactId, "status": status},
        "role": caller.role,
        "customers": _venues(sorted(venues)),
    }


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
    }
