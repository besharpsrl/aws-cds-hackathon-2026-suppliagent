"""Agent turn (T-41): caller injection, role tool sets, prompts, turn request contract."""

import json
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from mcp.types import Tool
from pydantic import ValidationError
from strands import tool
from strands.models import Model
from strands.tools.mcp.mcp_agent_tool import MCPAgentTool
from strands.types.tools import AgentTool
from suppliagent_agent import turn as turn_module
from suppliagent_agent.turn import (
    TurnRequest,
    run_turn,
    select_tools,
    system_prompt,
    user_prompt,
)

TURN = {
    "conversationId": "conv_1",
    "contactId": "con_001",
    "role": "CUSTOMER_CONTACT",
    "channelAddress": "WHATSAPP#+393330000001",
    "customerIds": ["cus_001", "cus_005"],
    "locale": "it-IT",
    "messages": [{"messageId": "m1", "ts": "2026-10-26T08:00:00Z", "text": "ciao"}],
    "whatsappWindowOpen": True,  # extra dispatcher fields are ignored
}
CALLER_SCHEMA = {"type": "object", "description": "Injected by the runtime."}


def mcp_tool(name: str) -> AgentTool:
    schema = {
        "type": "object",
        "properties": {"customerId": {"type": "string"}, "caller": CALLER_SCHEMA},
        "required": ["customerId", "caller"],
    }
    spec = Tool.model_validate({"name": name, "inputSchema": schema})
    return MCPAgentTool(spec, mcp_client=None)  # type: ignore[arg-type]


def test_select_tools_filters_by_role_and_hides_caller() -> None:
    tools = [
        mcp_tool("customers___identify_contact"),
        mcp_tool("customers___get_customer_profile"),
        mcp_tool("order-intake___extract_order_lines"),
        mcp_tool("catalog___match_products"),
        mcp_tool("catalog___search_catalog"),
        mcp_tool("inventory-pricing___check_availability"),
        mcp_tool("orders___confirm_order"),
        mcp_tool("orders___delete_everything"),  # not an allowed tool of the target
        mcp_tool("other___identify_contact"),  # same short name on another target: not allowed
        mcp_tool("x_amz_bedrock_agentcore_search"),
    ]
    unknown = select_tools(tools, "UNKNOWN")
    assert [t.tool_name for t in unknown] == ["customers___identify_contact"]
    customer = select_tools(tools, "CUSTOMER_CONTACT")
    assert [t.tool_name for t in customer] == [
        "customers___identify_contact",
        "customers___get_customer_profile",
        "order-intake___extract_order_lines",
        "catalog___match_products",
        "catalog___search_catalog",
        "inventory-pricing___check_availability",
        "orders___confirm_order",
    ]
    assert "orders___confirm_order" not in {t.tool_name for t in unknown}
    rep = select_tools(tools, "SALES_REP")
    assert {"order-intake___extract_order_lines", "orders___confirm_order"} <= {
        t.tool_name for t in rep
    }
    for t in customer:
        schema = t.tool_spec["inputSchema"]["json"]
        assert "caller" not in schema["properties"]
        assert schema["required"] == ["customerId"]


class ScriptedModel(Model):
    """Answers with the scripted tool calls first, then with a text reply."""

    def __init__(
        self, tool_calls: list[tuple[str, dict[str, Any]]], reply: str, fail: bool = False
    ) -> None:
        self.tool_calls = list(tool_calls)
        self.reply = reply
        self.fail = fail
        self.system_prompts: list[str | None] = []

    def update_config(self, **model_config: Any) -> None:
        pass

    def get_config(self) -> Any:
        return {}

    def structured_output(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def stream(
        self, messages: Any, tool_specs: Any = None, system_prompt: str | None = None, **_: Any
    ) -> AsyncGenerator[Any, None]:
        self.system_prompts.append(system_prompt)
        if self.fail:
            raise RuntimeError("throttled")
        yield {"messageStart": {"role": "assistant"}}
        if self.tool_calls:
            name, args = self.tool_calls.pop(0)
            start = {"toolUse": {"toolUseId": f"t{len(self.tool_calls)}", "name": name}}
            yield {"contentBlockStart": {"start": start}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(args)}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockDelta": {"delta": {"text": self.reply}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}


@pytest.fixture(autouse=True)
def clean_history() -> None:
    turn_module._HISTORY.clear()


def test_caller_is_always_injected_by_code_even_if_the_model_forges_it() -> None:
    received: list[dict[str, Any]] = []

    @tool(name="customers___get_customer_profile")
    def get_customer_profile(customerId: str, caller: dict[str, Any] | None = None) -> str:  # noqa: N803
        """Profile."""
        received.append({"customerId": customerId, "caller": caller})
        return "{}"

    forged = {"role": "SALES_REP", "contactId": "rep_001", "channelAddress": "x"}
    model = ScriptedModel(
        [("customers___get_customer_profile", {"customerId": "cus_002", "caller": forged})],
        "Ecco il profilo.",
    )
    reply = run_turn(TurnRequest.model_validate(TURN), [get_customer_profile], model)

    assert reply == "Ecco il profilo."
    assert received == [
        {
            "customerId": "cus_002",
            "caller": {
                "role": "CUSTOMER_CONTACT",
                "contactId": "con_001",
                "channelAddress": "WHATSAPP#+393330000001",
                "conversationId": "conv_1",
            },
        }
    ]
    history = json.dumps(list(turn_module._HISTORY.values()))
    assert "con_001" not in history and "+393330000001" not in history  # injected caller not kept


KEY = ("conv_1", "WHATSAPP#+393330000001")


def test_unknown_caller_has_no_null_fields_for_the_gateway_schema() -> None:
    unknown = TurnRequest.model_validate({**TURN, "role": "UNKNOWN", "contactId": None})
    assert turn_module.caller_of(unknown) == {
        "role": "UNKNOWN",
        "channelAddress": "WHATSAPP#+393330000001",
        "conversationId": "conv_1",
    }


def test_model_thinking_is_never_sent_to_the_user() -> None:
    model = ScriptedModel([], "<thinking>internal notes</thinking>\n\nBuongiorno!")
    assert run_turn(TurnRequest.model_validate(TURN), [], model) == "Buongiorno!"


def test_history_is_kept_per_conversation() -> None:
    model = ScriptedModel([], "Ciao!")
    run_turn(TurnRequest.model_validate(TURN), [], model)
    run_turn(TurnRequest.model_validate(TURN), [], model)
    assert len(turn_module._HISTORY[KEY]) == 4  # user, assistant, user, assistant
    run_turn(TurnRequest.model_validate({**TURN, "conversationId": "conv_2"}), [], model)
    assert len(turn_module._HISTORY[("conv_2", KEY[1])]) == 2


def test_another_sender_on_the_same_conversation_starts_empty() -> None:
    run_turn(TurnRequest.model_validate(TURN), [], ScriptedModel([], "Ciao!"))
    other = ScriptedModel([], "Ciao!")
    run_turn(TurnRequest.model_validate({**TURN, "channelAddress": "SMS#+39333"}), [], other)
    assert len(turn_module._HISTORY[("conv_1", "SMS#+39333")]) == 2


def test_a_failed_turn_leaves_the_history_unchanged() -> None:
    run_turn(TurnRequest.model_validate(TURN), [], ScriptedModel([], "Ciao!"))
    before = json.dumps(turn_module._HISTORY[KEY])
    with pytest.raises(RuntimeError):
        run_turn(TurnRequest.model_validate(TURN), [], ScriptedModel([], "", fail=True))
    assert json.dumps(turn_module._HISTORY[KEY]) == before


@pytest.mark.parametrize(
    ("role", "locale", "expected", "absent"),
    [
        ("UNKNOWN", "it-IT", ["Reply language: Italian", "identify first"], []),
        ("CUSTOMER_CONTACT", "en-GB", ["Reply language: English"], []),
        ("SALES_REP", "it-IT", ["Sales rep (copilot)"], ["identify first"]),
    ],
)
def test_system_prompt_by_role_and_language(
    role: str, locale: str, expected: list[str], absent: list[str]
) -> None:
    prompt = system_prompt(TurnRequest.model_validate({**TURN, "role": role, "locale": locale}))
    assert "virtual ordering assistant" in prompt
    for text in expected:
        assert text in prompt
    for text in absent:
        assert text not in prompt


def test_user_prompt_joins_the_burst_and_labels_attachments() -> None:
    messages = [
        {"messageId": "m1", "ts": "t", "attachments": [{"type": "image", "s3Uri": "s3://b/k"}]},
        {"messageId": "m2", "ts": "t", "attachments": [{"type": "audio", "s3Uri": "s3://b/v"}]},
        {"messageId": "m3", "ts": "t", "attachments": [{"type": "document"}]},  # not stored (E-13)
        {"messageId": "m4", "ts": "t", "text": "questo è l'ordine"},
    ]
    turn = TurnRequest.model_validate({**TURN, "messages": messages})
    assert user_prompt(turn) == (
        "[photo attached: s3Uri=s3://b/k]\n"
        "[voice message attached: s3Uri=s3://b/v]\n"
        "[document attached: not available]\n"
        "questo è l'ordine"
    )


@pytest.mark.parametrize(
    "patch",
    [{"role": "ADMIN"}, {"messages": []}, {"conversationId": ""}, {"channelAddress": None}],
)
def test_invalid_turn_requests_are_rejected(patch: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        TurnRequest.model_validate({**TURN, **patch})
