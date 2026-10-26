"""Runtime entrypoint (T-41): invalid turn requests never reach the model or the Gateway."""

import pytest
from suppliagent_agent import app


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
