"""Role-based authorization inside the tools (FN-32, INFRASTRUCTURE_DESIGN §5.3.2).

Every Gateway call carries a `caller` argument that the agent code (not the model) sets from the
turn request. Tools trust only who the caller is; what the caller may see is always read from
DynamoDB, never taken from the call.
"""

# ruff: noqa: N815 - field names are the camelCase wire names (02 §6).

from dataclasses import dataclass

from boto3.dynamodb.conditions import Key
from pydantic import BaseModel, ConfigDict, Field

from suppliagent_shared.aws import table
from suppliagent_shared.models import ContactStatus, Role


class CallerContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Role
    # `con_…` for CUSTOMER_CONTACT, `rep_…` for SALES_REP
    contactId: str | None = Field(None, max_length=64)
    # `CHANNEL#address`: the verified sender of the conversation, set by the Dispatcher
    channelAddress: str = Field(max_length=320)
    # log correlation; required where a tool keeps per-conversation state
    conversationId: str | None = Field(None, max_length=64)


@dataclass(frozen=True)
class Scope:
    customer_ids: frozenset[str]  # full access: verified contact's venues, or rep portfolio
    # Contact awaiting verification (F-02.C2): basic venue data and order drafts only. Tools
    # opt in to these explicitly; anything sensitive (prices, orders, history) must not.
    pending_customer_ids: frozenset[str] = frozenset()


NO_ACCESS = Scope(frozenset())


def caller_scope(caller: CallerContext) -> Scope:
    """Customers the caller may access: own venues for a contact, portfolio for a sales rep.
    Fail-closed: unknown roles or contact statuses get nothing."""
    if not caller.contactId:
        return NO_ACCESS
    if caller.role is Role.CUSTOMER_CONTACT:
        contact = table("contacts").get_item(Key={"contactId": caller.contactId}).get("Item")
        if not contact:
            return NO_ACCESS
        venues = frozenset(contact["customerIds"])
        if contact["status"] == ContactStatus.VERIFIED:
            return Scope(venues)
        if contact["status"] == ContactStatus.PENDING_VERIFICATION:
            return Scope(frozenset(), pending_customer_ids=venues)
        return NO_ACCESS
    if caller.role is Role.SALES_REP:
        # ponytail: single page (1 MB) is plenty for a rep portfolio; paginate if that changes.
        items = table("customers").query(
            IndexName="by-repId",
            KeyConditionExpression=Key("repId").eq(caller.contactId),
            ProjectionExpression="customerId",
        )["Items"]
        return Scope(frozenset(i["customerId"] for i in items))
    return NO_ACCESS
