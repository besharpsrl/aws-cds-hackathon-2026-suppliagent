"""SigV4 auth for the Gateway MCP endpoint."""

import httpx
import pytest
from suppliagent_agent.sigv4 import GatewaySigV4Auth


def test_requests_are_signed_for_bedrock_agentcore(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIDEXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "token")
    request = httpx.Request(
        "POST",
        "https://gw-123.gateway.bedrock-agentcore.eu-west-1.amazonaws.com/mcp",
        json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
    )
    signed = next(GatewaySigV4Auth("eu-west-1").auth_flow(request))
    authorization = signed.headers["Authorization"]
    assert authorization.startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/")
    assert "/eu-west-1/bedrock-agentcore/aws4_request" in authorization
    assert "content-type" in authorization  # body type is part of the signature
    assert signed.headers["X-Amz-Security-Token"] == "token"
