"""Identity and role of the sender (TECHNICAL_FLOWS §3.2): `ChannelIdentities` -> contact or rep."""

from dataclasses import dataclass, replace

from boto3.dynamodb.conditions import Key
from suppliagent_shared.aws import table
from suppliagent_shared.models import Channel, ContactStatus, Language, Role


@dataclass(frozen=True)
class Identity:
    role: Role
    contact_id: str | None = None  # `con_…`, or `rep_…` for a sales rep
    customer_ids: tuple[str, ...] = ()
    language: Language = Language.IT
    conversation_id: str | None = None  # set when identified inside an existing conversation


UNKNOWN = Identity(Role.UNKNOWN)  # F-02.C4: the agent identifies the sender (T-42)


def resolve(channel: Channel, sender: str) -> Identity:
    """Fail-closed: an address without a complete contact or rep record is UNKNOWN; a contact
    pending verification gets no venues (same rule as `caller_scope`). Who the sender may see is
    decided again inside each tool, from DynamoDB (FN-32)."""
    item = table("channel-identities").get_item(Key={"channelAddress": f"{channel}#{sender}"})
    identity = item.get("Item")
    if not identity:
        return UNKNOWN
    resolved = _resolve(Role(identity["role"]), identity["contactId"])
    if resolved.role is Role.UNKNOWN:
        return UNKNOWN
    return replace(resolved, conversation_id=identity.get("conversationId"))


def _resolve(role: Role, contact_id: str) -> Identity:
    if role is Role.CUSTOMER_CONTACT:  # C1, C5: venues of the contact
        contact = table("contacts").get_item(Key={"contactId": contact_id}).get("Item")
        if not contact or contact["status"] not in set(ContactStatus):
            return UNKNOWN
        venues = contact["customerIds"] if contact["status"] == ContactStatus.VERIFIED else []
        return Identity(role, contact_id, tuple(venues), Language(contact["language"]))
    if role is Role.SALES_REP:  # C2: portfolio = customers of the rep
        rep = table("sales-reps").get_item(Key={"repId": contact_id}).get("Item")
        if not rep:
            return UNKNOWN
        # ponytail: one page (1 MB) is plenty for a rep portfolio; paginate if that changes.
        customers = table("customers").query(
            IndexName="by-repId",
            KeyConditionExpression=Key("repId").eq(contact_id),
            ProjectionExpression="customerId",
        )["Items"]
        return Identity(
            role,
            contact_id,
            tuple(sorted(c["customerId"] for c in customers)),
            Language(rep["language"]),
        )
    return UNKNOWN
