"""Where the order confirmation email goes (FN-14, F-07.C7).

The address is the contact's `orderEmail` (given to the assistant, T-26) or, failing that, a
verified `EMAIL#` channel identity of the same contact (customer contact or sales rep). It is used
only for order confirmations: a stored `orderEmail` never becomes a channel identity, so mail from
that address is not trusted as the contact.
"""

import re

from boto3.dynamodb.conditions import Key

from suppliagent_shared.aws import table
from suppliagent_shared.errors import InvalidInputError

MAX_EMAIL_LENGTH = 254
_EMAIL = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")


def normalize_email(value: str) -> str:
    """Trimmed, lower-case address, or `InvalidInputError` (no display names, no lists)."""
    email = value.strip().lower()
    if len(email) > MAX_EMAIL_LENGTH or not _EMAIL.match(email):
        raise InvalidInputError
    return email


def order_email(contact_id: str | None) -> str | None:
    if not contact_id:
        return None
    if contact_id.startswith("con_"):
        contact = table("contacts").get_item(Key={"contactId": contact_id}).get("Item") or {}
        if email := contact.get("orderEmail"):
            return str(email)
    identities = table("channel-identities").query(
        IndexName="by-contactId", KeyConditionExpression=Key("contactId").eq(contact_id)
    )["Items"]
    emails = sorted(
        str(item["channelAddress"]).removeprefix("EMAIL#")
        for item in identities
        if item.get("channel") == "EMAIL" and item.get("verified") is True
    )
    return emails[0] if emails else None
