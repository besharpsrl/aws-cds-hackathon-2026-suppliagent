"""One agent turn: turn request (TECHNICAL_FLOWS §6.2) → reply text.

The `caller` context reaches the tools from code only (INFRASTRUCTURE_DESIGN §5.3.2): it is removed
from the tool schemas the model sees and written into every tool call by a hook.
"""

# ruff: noqa: N815 - field names are the camelCase wire names (02 §6).

import copy
import re
from datetime import datetime
from importlib.resources import files
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field
from strands import Agent
from strands.hooks import BeforeToolCallEvent
from strands.models import Model
from strands.tools.mcp.mcp_agent_tool import MCPAgentTool
from strands.types.content import Messages
from strands.types.tools import AgentTool

Role = Literal["CUSTOMER_CONTACT", "SALES_REP", "UNKNOWN"]
CALLER = "caller"
# Gateway tool names are `<target>___<tool>`; the role decides which tools the model gets.
IDENTIFY = "customers___identify_contact"
PROFILE = "customers___get_customer_profile"
EXTRACT = "order-intake___extract_order_lines"
MATCH = "catalog___match_products"
SEARCH = "catalog___search_catalog"
# F-14: every role, UNKNOWN included (identification failed, new customer).
HANDOFF = "orders___handoff_to_human"
# Stock, prices, delivery dates (T-45) and the order lifecycle (T-46); the tools check the caller's
# own customers (or the rep's portfolio) themselves.
ORDER_TOOLS = frozenset(
    {
        "inventory-pricing___check_availability",
        "inventory-pricing___get_prices",
        "inventory-pricing___get_delivery_options",
        "orders___create_order_draft",
        "orders___update_order_draft",
        "orders___request_order_confirmation",
        "orders___confirm_order",
        "orders___cancel_order",
        "orders___get_order_status",
        "orders___report_delivery_issue",
    }
)
KNOWN_TOOLS = frozenset({IDENTIFY, PROFILE, EXTRACT, MATCH, SEARCH, HANDOFF}) | ORDER_TOOLS
ROLE_TOOLS: dict[Role, frozenset[str]] = {
    "UNKNOWN": frozenset({IDENTIFY, HANDOFF}),
    "CUSTOMER_CONTACT": KNOWN_TOOLS,
    "SALES_REP": KNOWN_TOOLS,
}
ROLE_PROMPTS: dict[Role, list[str]] = {
    "UNKNOWN": ["customer_unknown.md"],
    "CUSTOMER_CONTACT": ["customer.md", "ordering.md"],
    "SALES_REP": ["sales_rep.md", "ordering.md"],
}
LANGUAGES = {"it": "Italian", "en": "English"}
# Nova writes its reasoning inline and sometimes wraps the answer in <response>: never sent as is.
THINKING = re.compile(r"<thinking>.*?(</thinking>|$)", re.DOTALL)
RESPONSE_TAG = re.compile(r"</?response>")
ATTACHMENT_LABELS = {"image": "photo", "audio": "voice message", "document": "document"}


class Attachment(BaseModel):
    type: str
    s3Uri: str | None = None


class InboundMessage(BaseModel):
    messageId: str
    ts: str
    text: str | None = Field(None, max_length=4000)
    attachments: list[Attachment] = []


class TurnRequest(BaseModel):
    """Dispatcher → Runtime (02 §6.2). Unknown fields are ignored so the dispatcher can evolve."""

    model_config = ConfigDict(extra="ignore")

    conversationId: str = Field(min_length=1, max_length=64)
    contactId: str | None = None
    role: Role
    channelAddress: str = Field(max_length=320)
    customerIds: list[str] = []
    activeCustomerId: str | None = None
    channel: str = "WHATSAPP"
    locale: str = "it-IT"
    messages: list[InboundMessage] = Field(min_length=1)


def caller_of(turn: TurnRequest) -> dict[str, Any]:
    caller = {
        "role": turn.role,
        "contactId": turn.contactId,
        "channelAddress": turn.channelAddress,
        "conversationId": turn.conversationId,
    }
    # The Gateway validates the input against the schema: null is not a string.
    return {k: v for k, v in caller.items() if v is not None}


def select_tools(tools: list[AgentTool], role: Role) -> list[AgentTool]:
    """Tools allowed for the role, with `caller` removed from the schema the model sees."""
    selected = [t for t in tools if t.tool_name in ROLE_TOOLS[role]]
    for tool in selected:
        # MCPAgentTool builds tool_spec around the MCP tool's own schema dict: edit it in place.
        schema = tool.tool_spec["inputSchema"]["json"]
        schema.get("properties", {}).pop(CALLER, None)
        if CALLER in schema.get("required", []):
            schema["required"].remove(CALLER)
    return [model_facing(t) for t in selected]


def model_facing(tool: AgentTool) -> AgentTool:
    """Nova fails (`invalid sequence as part of ToolUse`) on tool names with a hyphen, and Gateway
    target names cannot use `_`: the model sees `_`, the Gateway gets the original name."""
    if isinstance(tool, MCPAgentTool) and "-" in tool.tool_name:
        return MCPAgentTool(
            tool.mcp_tool,
            tool.mcp_client,
            name_override=tool.tool_name.replace("-", "_"),
            timeout=tool.timeout,
        )
    return tool


def inject_caller(event: BeforeToolCallEvent) -> None:
    """Always overwrite: whatever the model put in `caller` is discarded."""
    tool_input = event.tool_use["input"]
    # A copy: tool_use is also the block in the conversation history, which must not hold `caller`.
    event.tool_use = {
        **event.tool_use,
        "input": {
            **(tool_input if isinstance(tool_input, dict) else {}),
            CALLER: event.invocation_state[CALLER],
        },
    }


def now_in_rome(turn: TurnRequest) -> str:
    """Moment of the last message in the distributor's time zone: "tomorrow" needs a date."""
    moment = datetime.fromisoformat(turn.messages[-1].ts).astimezone(ZoneInfo("Europe/Rome"))
    return moment.strftime("%A %Y-%m-%d %H:%M (Europe/Rome)")


def system_prompt(turn: TurnRequest) -> str:
    prompts = files("suppliagent_agent") / "prompts"
    language = LANGUAGES.get(turn.locale.split("-")[0].lower(), "English")
    context = "\n".join(
        [
            "## Conversation context (set by the system, not by the user)",
            f"- Caller role: {turn.role}",
            f"- Channel: {turn.channel}",
            f"- Now: {now_in_rome(turn)}",
            f"- Reply language: {language}",
            f"- Caller's venues (customerId): {', '.join(turn.customerIds) or 'none'}",
            f"- Active venue: {turn.activeCustomerId or 'not chosen'}",
        ]
    )
    parts = [(prompts / name).read_text() for name in ["shared.md", *ROLE_PROMPTS[turn.role]]]
    return "\n\n".join([*parts, context])


def user_prompt(turn: TurnRequest) -> str:
    """All messages of the burst (debounced by the dispatcher) as one user turn."""
    lines = []
    for message in turn.messages:
        # The URI (set by the system, never by the sender) is what `extract_order_lines` takes.
        lines += [
            f"[{ATTACHMENT_LABELS.get(a.type, a.type)} attached: "
            f"{f's3Uri={a.s3Uri}' if a.s3Uri else 'not available'}]"
            for a in message.attachments
        ]
        if message.text:
            lines.append(message.text)
    return "\n".join(lines) or "[empty message]"


# ponytail: conversation history lives in the Runtime session's memory (one microVM per
# runtimeSessionId); lost when the session ends. AgentCore Memory replaces it in T-54.
# Keyed by conversation and sender: another sender never inherits tool results.
_HISTORY: dict[tuple[str, str], Messages] = {}


def run_turn(turn: TurnRequest, tools: list[AgentTool], model: Model) -> str:
    key = (turn.conversationId, turn.channelAddress)
    agent = Agent(
        model=model,
        tools=list[Any](select_tools(tools, turn.role)),
        system_prompt=system_prompt(turn),
        # a copy: a failed turn must not leave a dangling user message or toolUse in the history
        messages=copy.deepcopy(_HISTORY.get(key, [])),
        callback_handler=None,  # the default handler prints the streamed text: no contents in logs
    )
    agent.add_hook(inject_caller, BeforeToolCallEvent)
    result = agent(user_prompt(turn), invocation_state={CALLER: caller_of(turn)})
    _HISTORY[key] = agent.messages
    return RESPONSE_TAG.sub("", THINKING.sub("", str(result))).strip()
