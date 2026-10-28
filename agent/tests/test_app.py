"""Runtime entrypoint (T-41): invalid turn requests never reach the model or the Gateway."""

import pytest
from suppliagent_agent import app
from suppliagent_agent.turn import TurnRequest


def test_invalid_request_is_rejected_without_calling_gateway_or_model(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def fail(*_: object, **__: object) -> None:
        raise AssertionError("must not be called")

    monkeypatch.setattr(app, "MCPClient", fail)
    monkeypatch.setattr(app, "run_turn", fail)
    payload = {"conversationId": "conv_1", "role": "ADMIN", "messages": [{"text": "secret text"}]}

    assert app.invoke(payload, None) == {"error": "INVALID_REQUEST"}
    assert "secret text" not in caplog.text


TURN = {
    "conversationId": "conv_1",
    "contactId": "con_001",
    "role": "CUSTOMER_CONTACT",
    "channelAddress": "WHATSAPP#+393330000001",
    "messages": [{"messageId": "m1", "ts": "2026-10-26T08:00:00Z", "text": "ciao"}],
}


def test_without_guardrail_env_the_model_has_no_guardrail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GUARDRAIL_ID", raising=False)
    assert app.guardrail_config() == {}


def test_guardrail_checks_only_the_latest_user_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """FN-32: input and output; the input check covers the user's text, not tool results."""
    monkeypatch.setenv("GUARDRAIL_ID", "gr123")
    monkeypatch.setenv("GUARDRAIL_VERSION", "3")
    config = app.guardrail_config()
    assert config["guardrail_id"] == "gr123" and config["guardrail_version"] == "3"
    assert config["guardrail_latest_message"] is True
    assert config["guardrail_redact_input"] is True  # a blocked message does not stay in history


def test_without_memory_env_there_is_no_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MEMORY_ID", raising=False)
    assert app.memory_config(TurnRequest.model_validate(TURN)) is None


def test_memory_is_per_contact_and_conversation_and_recalls_long_term_notes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEMORY_ID", "mem-1")
    config = app.memory_config(TurnRequest.model_validate(TURN))
    assert config is not None
    assert (config.memory_id, config.actor_id, config.session_id) == ("mem-1", "con_001", "conv_1")
    # the namespaces of the CDK strategies (infra/lib/stacks/agent-stack.ts)
    assert set(config.retrieval_config or {}) == {"/preferences/{actorId}", "/facts/{actorId}"}
