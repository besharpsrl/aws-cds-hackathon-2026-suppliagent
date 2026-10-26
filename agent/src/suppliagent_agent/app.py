"""AgentCore Runtime entrypoint (T-41). Environment: GATEWAY_URL, MODEL_ID, AWS_REGION."""

import logging
import os
from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from pydantic import ValidationError
from strands.models import BedrockModel
from strands.tools.mcp import MCPClient

from suppliagent_agent.sigv4 import GatewaySigV4Auth
from suppliagent_agent.turn import TurnRequest, run_turn

logger = logging.getLogger(__name__)
# Strands logs tool inputs at DEBUG: never below INFO.
logging.getLogger("strands").setLevel(logging.INFO)
app = BedrockAgentCoreApp()


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
    with gateway:
        reply = run_turn(
            turn,
            gateway.list_tools_sync(),
            BedrockModel(model_id=os.environ["MODEL_ID"], region_name=region),
        )
    return {"conversationId": turn.conversationId, "reply": reply}
