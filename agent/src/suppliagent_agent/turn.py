"""One agent turn: turn request (TECHNICAL_FLOWS §6.2) → reply text and its options.

The `caller` context reaches the tools from code only (INFRASTRUCTURE_DESIGN §5.3.2): it is removed
from the tool schemas the model sees and written into every tool call by a hook.

Options (T-25, FN-08, FN-12): an order summary gets *Confirm / Change* buttons from code when
`request_order_confirmation` put the order in `PENDING_CONFIRMATION` during the turn; the model
offers the choices of one question with the local `offer_choices` tool. A tap on *Confirm* reaches
`confirm_order` as `interactiveReply` from code only, with the id of the message it replied to.
"""

# ruff: noqa: N815 - field names are the camelCase wire names (02 §6).

import copy
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from importlib.resources import files
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field
from strands import Agent
from strands import tool as local_tool
from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent
from strands.models import Model
from strands.session import SessionManager
from strands.tools.mcp.mcp_agent_tool import MCPAgentTool
from strands.types.content import Messages
from strands.types.tools import AgentTool, ToolContext, ToolResult

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
# F-01: privacy notice and consent of a customer contact; sales reps are staff and never get it.
PRIVACY = "customers___update_privacy"
# FN-14, F-07.C7: the address for the order confirmation email, asked when there is none.
ORDER_EMAIL = "customers___set_order_email"
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
REQUEST_CONFIRMATION = "orders___request_order_confirmation"
CONFIRM = "orders___confirm_order"
# After these the summary shown earlier in the turn is no longer what the order is.
SUMMARY_CHANGERS = frozenset(
    {"orders___create_order_draft", "orders___update_order_draft", "orders___cancel_order"}
)
# Local tool (not on the Gateway): the options of the reply's single question.
OFFER_CHOICES = "offer_choices"
CONFIRM_ID, CHANGE_ID = "order_confirm", "order_modify"
SUMMARY_LABELS = {"it": ("Confermo", "Modifica"), "en": ("Confirm", "Change")}
MAX_OPTION_LENGTH = 24  # a WhatsApp list row title
MAX_OPTIONS = 10  # rows of a WhatsApp list
ORDER_ID = re.compile(r"^ord_[A-Za-z0-9]{1,40}$")
TURN_STATE = "turn_state"
ROLE_TOOLS: dict[Role, frozenset[str]] = {
    "UNKNOWN": frozenset({IDENTIFY, HANDOFF}),
    "CUSTOMER_CONTACT": KNOWN_TOOLS | {PRIVACY, ORDER_EMAIL},
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
TAP_ID = re.compile(r"[^A-Za-z0-9_]")
# Message text is untrusted: delimited, and the sender cannot write the system's own tags
# (`user_context` is where AgentCore Memory puts what it recalls about the caller).
UNTRUSTED_TAG = "user_message"
SYSTEM_TAGS = re.compile(r"user_message|user_context", re.IGNORECASE)
# E-06: what the user gets when the Bedrock Guardrail blocks the input or the reply.
GUARDRAIL_REPLY = {
    "it": "Non posso aiutarti con questa richiesta. "
    "Posso aiutarti con ordini, prodotti e consegne.",
    "en": "I can't help with that request. I can help with orders, products and deliveries.",
}

logger = logging.getLogger(__name__)


class Attachment(BaseModel):
    type: str
    s3Uri: str | None = None


class InteractiveReply(BaseModel):
    """A button or list tap (Router, 02 §6.1): `contextId` is the message it replied to."""

    id: str = Field(max_length=256)
    title: str = Field("", max_length=256)
    contextId: str | None = Field(None, max_length=256)


class InboundMessage(BaseModel):
    messageId: str
    ts: str
    text: str | None = Field(None, max_length=4000)
    attachments: list[Attachment] = []
    interactiveReply: InteractiveReply | None = None


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


@dataclass
class TurnState:
    """What the turn's tool calls decided about the reply's options."""

    confirm_tap: str | None = None  # contextId of a tap on Confirm in this turn's messages
    summary_order: str | None = None  # order whose summary this reply shows
    choices: list[str] = field(default_factory=list)


@dataclass
class TurnReply:
    text: str
    interactive: dict[str, Any] | None = None


def inject_caller(event: BeforeToolCallEvent) -> None:
    """Always overwrite: whatever the model put in `caller` is discarded. `confirm_order` gets
    `interactiveReply` only from a real tap on Confirm in this turn, never from the model."""
    name = event.tool_use["name"]
    if name == OFFER_CHOICES:
        return
    tool_input = event.tool_use["input"]
    new_input = {
        **(tool_input if isinstance(tool_input, dict) else {}),
        CALLER: event.invocation_state[CALLER],
    }
    if name == CONFIRM:
        new_input.pop("interactiveReply", None)
        state: TurnState | None = event.invocation_state.get(TURN_STATE)
        if state and state.confirm_tap:
            new_input["interactiveReply"] = {"contextId": state.confirm_tap}
    # A copy: tool_use is also the block in the conversation history, which must not hold `caller`.
    event.tool_use = {**event.tool_use, "input": new_input}


def result_data(result: ToolResult) -> dict[str, Any]:
    """The JSON object a Gateway tool returned (structured content, or a JSON text block)."""
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    for block in result.get("content", []):
        if isinstance(block.get("json"), dict):
            return dict(block["json"])
        try:
            data = json.loads(block.get("text", ""))
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    return {}


def track_summary(event: AfterToolCallEvent) -> None:
    """The reply shows a summary to confirm when the last order step of the turn produced one."""
    state: TurnState | None = event.invocation_state.get(TURN_STATE)
    name = event.tool_use["name"]
    if state is None or (
        name not in SUMMARY_CHANGERS and name not in {REQUEST_CONFIRMATION, CONFIRM}
    ):
        return
    data = result_data(event.result) if event.result.get("status") == "success" else {}
    if name == REQUEST_CONFIRMATION:
        order_id = (data.get("summary") or {}).get("orderId")
        pending = data.get("status") == "PENDING_CONFIRMATION"
        valid = isinstance(order_id, str) and ORDER_ID.match(order_id)
        state.summary_order = order_id if pending and valid else None
    elif name in SUMMARY_CHANGERS or data.get("status") in {"CONFIRMED", "ALREADY_CONFIRMED"}:
        state.summary_order = None


@local_tool(name=OFFER_CHOICES, context=True)
def offer_choices(options: list[str], tool_context: ToolContext) -> str:
    """Show the options of the one question in your reply as buttons the user can tap
    (WhatsApp). Use it only when your reply asks exactly one question with 2 to 10 short
    alternatives: which product of the candidates, which venue, which delivery date. Labels in the
    reply language, at most 24 characters each, in the order you list them; add "Altro" /
    "Something else" when the answer may be none of them. Still write the options in your reply.
    Not for the order summary (its buttons are added for you) and not for yes/no consent.

    Args:
        options: the button labels, 2 to 10.
    """
    labels = [" ".join(o.split()) for o in options if o.strip()]
    if not 2 <= len(labels) <= MAX_OPTIONS:
        raise ValueError(f"Give 2 to {MAX_OPTIONS} options.")
    if too_long := [o for o in labels if len(o) > MAX_OPTION_LENGTH]:
        raise ValueError(f"Shorten these labels to {MAX_OPTION_LENGTH} characters: {too_long}")
    if len({o.casefold() for o in labels}) != len(labels):
        raise ValueError("Two labels are the same: make each one distinct (e.g. add the format).")
    tool_context.invocation_state[TURN_STATE].choices = labels
    return "Done: the options will appear as buttons under your reply."


def interactive_of(turn: TurnRequest, state: TurnState) -> dict[str, Any] | None:
    """Options of the reply for the Notifier (02 §6.2); the summary wins over a choice."""
    if state.summary_order:
        language = "it" if turn.locale.lower().startswith("it") else "en"
        confirm, change = SUMMARY_LABELS[language]
        return {
            "kind": "ORDER_SUMMARY",
            "orderId": state.summary_order,
            "options": [{"id": CONFIRM_ID, "title": confirm}, {"id": CHANGE_ID, "title": change}],
        }
    if state.choices:
        return {
            "kind": "CHOICE",
            "options": [{"id": f"opt_{i}", "title": t} for i, t in enumerate(state.choices, 1)],
        }
    return None


def confirm_tap(turn: TurnRequest) -> str | None:
    """`contextId` of the latest tap on Confirm in the turn's messages."""
    for message in reversed(turn.messages):
        tap = message.interactiveReply
        if tap and tap.id == CONFIRM_ID and tap.contextId:
            return tap.contextId
    return None


def now_in_rome(turn: TurnRequest) -> str:
    """Moment of the last message in the distributor's time zone: "tomorrow" needs a date."""
    moment = datetime.fromisoformat(turn.messages[-1].ts).astimezone(ZoneInfo("Europe/Rome"))
    return moment.strftime("%A %Y-%m-%d %H:%M (Europe/Rome)")


def privacy_notice_line() -> str:
    """Link of the privacy notice (F-01), from the Runtime environment; `UNSET` until published."""
    url = os.environ.get("PRIVACY_NOTICE_URL", "")
    return f"- Privacy notice link: {'none published yet' if url in ('', 'UNSET') else url}"


def system_prompt(turn: TurnRequest) -> str:
    prompts = files("suppliagent_agent") / "prompts"
    language = LANGUAGES.get(turn.locale.split("-")[0].lower(), "English")
    lines = [
        "## Conversation context (set by the system, not by the user)",
        f"- Caller role: {turn.role}",
        f"- Channel: {turn.channel}",
        f"- Now: {now_in_rome(turn)}",
        f"- Reply language: {language}",
        f"- Caller's venues (customerId): {', '.join(turn.customerIds) or 'none'}",
        f"- Active venue: {turn.activeCustomerId or 'not chosen'}",
    ]
    if turn.role != "SALES_REP":  # sales reps are staff: no privacy notice
        lines.append(privacy_notice_line())
    context = "\n".join(lines)
    parts = [(prompts / name).read_text() for name in ["shared.md", *ROLE_PROMPTS[turn.role]]]
    return "\n\n".join([*parts, context])


def user_prompt(turn: TurnRequest) -> str:
    """All messages of the burst (debounced by the dispatcher) as one user turn. The text the
    sender wrote is delimited as untrusted content (FN-32), never mixed with the system's lines."""
    lines = []
    for message in turn.messages:
        # The URI (set by the system, never by the sender) is what `extract_order_lines` takes.
        lines += [
            f"[{ATTACHMENT_LABELS.get(a.type, a.type)} attached: "
            f"{f's3Uri={a.s3Uri}' if a.s3Uri else 'not available'}]"
            for a in message.attachments
        ]
        if tap := message.interactiveReply:
            # The id is ours (button ids of the reply); the label is shown to the user as data.
            lines.append(f"[button tapped: id={TAP_ID.sub('', tap.id)[:40]}, label below]")
        if text := message.text or (message.interactiveReply and message.interactiveReply.title):
            text = SYSTEM_TAGS.sub(lambda m: m.group().replace("_", " "), text)
            lines.append(f"<{UNTRUSTED_TAG}>\n{text}\n</{UNTRUSTED_TAG}>")
    return "\n".join(lines) or "[empty message]"


# Conversation of a sender that was unknown at the first message (inbound router): it keeps its id
# after the identification.
UNKNOWN_CONVERSATION_PREFIX = "conv_u"


def memory_actor_id(turn: TurnRequest) -> str:
    """AgentCore Memory actor (FN-25): the contact, the same on every channel. A conversation that
    started from an unknown sender keeps one actor, a hash of the address (no phone number or email
    stored), also after the identification: Memory keys the history on actor and session."""
    if turn.contactId and not turn.conversationId.startswith(UNKNOWN_CONVERSATION_PREFIX):
        return turn.contactId
    return "addr-" + hashlib.sha256(turn.channelAddress.encode()).hexdigest()[:32]


def guardrail_reply(turn: TurnRequest) -> TurnReply:
    return TurnReply(GUARDRAIL_REPLY.get(turn.locale.split("-")[0].lower(), GUARDRAIL_REPLY["en"]))


# Without AgentCore Memory (local runs, tests) the history lives in the Runtime session's process
# (one microVM per runtimeSessionId) and is lost when the session ends.
# Keyed by conversation and sender: another sender never inherits tool results.
_HISTORY: dict[tuple[str, str], Messages] = {}


def run_turn(
    turn: TurnRequest,
    tools: list[AgentTool],
    model: Model,
    session_manager: SessionManager | None = None,
) -> TurnReply:
    """One turn. With `session_manager` (AgentCore Memory) the history and what is recalled about
    the caller come from Memory; otherwise from the in-process history."""
    key = (turn.conversationId, turn.channelAddress)
    state = TurnState(confirm_tap=confirm_tap(turn))
    agent = Agent(
        model=model,
        tools=[*select_tools(tools, turn.role), offer_choices],
        system_prompt=system_prompt(turn),
        # a copy: a failed turn must not leave a dangling user message or toolUse in the history
        messages=None if session_manager else copy.deepcopy(_HISTORY.get(key, [])),
        session_manager=session_manager,
        callback_handler=None,  # the default handler prints the streamed text: no contents in logs
    )
    agent.add_hook(inject_caller, BeforeToolCallEvent)
    agent.add_hook(track_summary, AfterToolCallEvent)
    result = agent(user_prompt(turn), invocation_state={CALLER: caller_of(turn), TURN_STATE: state})
    if not session_manager:
        _HISTORY[key] = agent.messages
    if result.stop_reason == "guardrail_intervened":
        logger.warning("guardrail intervened", extra={"conversationId": turn.conversationId})
        return guardrail_reply(turn)
    text = RESPONSE_TAG.sub("", THINKING.sub("", str(result))).strip()
    return TurnReply(text, interactive_of(turn, state) if text else None)
