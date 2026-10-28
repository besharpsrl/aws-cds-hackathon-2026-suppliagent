"""AgentCore Runtime entrypoint (T-41). Environment: GATEWAY_URL, MODEL_ID, AWS_REGION; with
T-54 also MEMORY_ID (AgentCore Memory) and GUARDRAIL_ID/GUARDRAIL_VERSION (Bedrock Guardrail)."""

import logging
import os
from contextlib import nullcontext
from typing import Any

from bedrock_agentcore.memory.integrations.strands.config import (
    AgentCoreMemoryConfig,
    RetrievalConfig,
)
from bedrock_agentcore.memory.integrations.strands.session_manager import (
    AgentCoreMemorySessionManager,
)
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from pydantic import ValidationError
from strands.models import BedrockModel
from strands.tools.mcp import MCPClient

from suppliagent_agent.sigv4 import GatewaySigV4Auth
from suppliagent_agent.turn import TurnRequest, memory_actor_id, run_turn

logger = logging.getLogger(__name__)
# Strands logs tool inputs at DEBUG: never below INFO.
logging.getLogger("strands").setLevel(logging.INFO)
app = BedrockAgentCoreApp()

# Long-term memory recalled at every user message: the namespaces of the strategies in the CDK
# (AgentStack). Summaries are per session and the session's own events are already restored.
RECALLED_NAMESPACES = ("preferences", "facts")
RECALL = RetrievalConfig(top_k=5, relevance_score=0.3)


def guardrail_config() -> dict[str, Any]:
    """Bedrock Guardrail on the model calls (FN-32): the user's latest message on input, every
    reply on output. Tool results and the system prompt are not checked (they hold the caller's
    own data, which the PII filters would flag)."""
    guardrail_id = os.environ.get("GUARDRAIL_ID")
    if not guardrail_id:
        return {}
    return {
        "guardrail_id": guardrail_id,
        "guardrail_version": os.environ.get("GUARDRAIL_VERSION", "DRAFT"),
        "guardrail_latest_message": True,
        "guardrail_redact_input": True,
        "guardrail_redact_input_message": "[message removed by the content filter]",
        "guardrail_trace": "enabled",
    }


def memory_config(turn: TurnRequest) -> AgentCoreMemoryConfig | None:
    """AgentCore Memory (FN-25): `actorId` is the contact, the same on every channel."""
    memory_id = os.environ.get("MEMORY_ID")
    if not memory_id:
        return None
    actor_id = memory_actor_id(turn)
    recall = {f"/{name}/{{actorId}}": RECALL for name in RECALLED_NAMESPACES}
    if turn.contactId and turn.contactId != actor_id:
        # identified in a conversation that keeps the address actor: also the contact's own notes
        contact = turn.contactId.replace("{", "{{").replace("}", "}}")
        recall |= {f"/{name}/{contact}": RECALL for name in RECALLED_NAMESPACES}
    return AgentCoreMemoryConfig(
        memory_id=memory_id,
        session_id=turn.conversationId,
        actor_id=actor_id,
        retrieval_config=recall,
    )


@app.entrypoint
def invoke(payload: dict[str, Any], context: Any) -> dict[str, Any]:
    try:
        turn = TurnRequest.model_validate(payload)
    except ValidationError as e:
        # field locations only: the payload holds message texts
        logger.warning("invalid turn request: %s", [err["loc"] for err in e.errors()])
        return {"error": "INVALID_REQUEST"}
    region = os.environ["AWS_REGION"]
    gateway = MCPClient(url=os.environ["GATEWAY_URL"], auth_provider=GatewaySigV4Auth(region))
    model = BedrockModel(model_id=os.environ["MODEL_ID"], region_name=region, **guardrail_config())
    config = memory_config(turn)
    memory = AgentCoreMemorySessionManager(config, region_name=region) if config else None
    # the session manager flushes pending events when the turn ends, also on errors
    with gateway, memory or nullcontext():
        reply = run_turn(turn, gateway.list_tools_sync(), model, memory)
    return {"conversationId": turn.conversationId, "reply": reply}
