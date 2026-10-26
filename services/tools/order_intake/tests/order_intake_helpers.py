"""Constants and scripted fakes shared by the order_intake tests."""

import json
from dataclasses import dataclass, field
from typing import Any

from botocore.exceptions import ClientError
from suppliagent_shared.auth import CallerContext
from suppliagent_shared.models import Role

BUCKET = "suppliagent-test-media"
CALLER = CallerContext(
    role=Role.CUSTOMER_CONTACT,
    contactId="con_anna",
    channelAddress="WHATSAPP#+390000000001",
    conversationId="conv_1",
)
PHOTO = f"s3://{BUCKET}/media/con_anna/m1/wamid1.jpg"
VOICE = f"s3://{BUCKET}/media/con_anna/m2/wamid2.ogg"
JPEG = b"\xff\xd8\xff\xe0fake-jpeg"


def client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "x"}}, "Converse")


def tool_use(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"toolUse": {"name": "x", "input": payload}}],
            }
        }
    }


def line(raw: str, qty: str | None = "3", unit: str | None = "kg", **extra: Any) -> dict[str, Any]:
    return {"rawText": raw, "rawQuantity": qty, "rawUnit": unit, "readConfidence": 0.9, **extra}


def extraction(**fields: Any) -> dict[str, Any]:
    return {"isOrder": True, "imageReadable": True, "lines": [line("mozz fdl")], **fields}


@dataclass
class FakeBedrock:
    replies: list[Any] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        response: dict[str, Any] = reply
        return response

    def reply(self, payload: dict[str, Any]) -> None:
        self.replies.append(tool_use(payload))


@dataclass
class FakeTranscribe:
    s3: Any
    statuses: list[str] = field(default_factory=lambda: ["COMPLETED"])
    transcript: str = "tre chili di mozzarella e due casse di pelati"
    started: list[dict[str, Any]] = field(default_factory=list)
    conflict: bool = False

    def start_transcription_job(self, **kwargs: Any) -> dict[str, Any]:
        if self.conflict:
            error = type("ConflictException", (Exception,), {})
            raise error("exists")
        self.started.append(kwargs)
        body = {"results": {"transcripts": [{"transcript": self.transcript}]}}
        self.s3.put_object(Bucket=BUCKET, Key=kwargs["OutputKey"], Body=json.dumps(body))
        return {}

    def get_transcription_job(self, **_: Any) -> dict[str, Any]:
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return {"TranscriptionJob": {"TranscriptionJobStatus": status}}
