"""Gateway handler: tool dispatch and error mapping (nothing but a code reaches the model)."""

import logging
from types import SimpleNamespace
from typing import Any

import pytest
from order_intake_helpers import CALLER, PHOTO, FakeBedrock, extraction
from suppliagent_tool_order_intake.handler import lambda_handler

CONTEXT = SimpleNamespace(
    client_context=SimpleNamespace(
        custom={"bedrockAgentCoreToolName": "order_intake___extract_order_lines"}
    ),
    function_name="tool-order-intake",
    memory_limit_in_mb=512,
    invoked_function_arn="arn:aws:lambda:eu-west-1:111111111111:function:x",
    aws_request_id="r1",
)


def call(**args: Any) -> dict[str, Any]:
    return lambda_handler({"caller": CALLER.model_dump(exclude_none=True), **args}, CONTEXT)


def test_text_call_returns_the_lines(bedrock: FakeBedrock) -> None:
    bedrock.reply(extraction())
    result = call(text="3 kg mozzarella")
    assert result["status"] == "OK" and result["lines"][0]["rawText"] == "mozz fdl"


def test_errors_are_codes_without_details(bedrock: FakeBedrock) -> None:
    assert call(s3Uri="s3://x/media/con_bruno/m/f.jpg") == {"error": "ACCESS_DENIED"}
    assert call() == {"error": "INVALID_INPUT"}
    bedrock.replies += [{"output": {"message": {"content": []}}}] * 2
    assert call(text="burro") == {"error": "EXTRACTION_FAILED"}
    assert call(s3Uri=PHOTO.replace("wamid1", "missing")) == {"error": "INTERNAL_ERROR"}
    unknown = SimpleNamespace(
        client_context=SimpleNamespace(custom={"bedrockAgentCoreToolName": "t___other"})
    )
    assert lambda_handler({}, unknown) == {"error": "UNKNOWN_TOOL"}


def test_logs_hold_no_message_content(
    bedrock: FakeBedrock, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    bedrock.reply(extraction(lines=[{"rawText": "BURRO SEGRETO", "readConfidence": 1}]))
    with caplog.at_level(logging.DEBUG):
        call(text="ordine di Mario Rossi, via Roma 1, burro")
    logged = caplog.text + capsys.readouterr().out
    assert "Mario Rossi" not in logged and "BURRO" not in logged and "WHATSAPP#" not in logged
