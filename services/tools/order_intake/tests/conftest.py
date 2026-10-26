"""Moto S3 with a few media objects; Bedrock and Transcribe are scripted fakes."""

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import boto3
import pytest
import suppliagent_tool_order_intake.intake as intake
from moto import mock_aws

# --import-mode=importlib does not put this directory on the path: the helpers are a sibling module
sys.path.insert(0, str(Path(__file__).parent))
from order_intake_helpers import BUCKET, JPEG, FakeBedrock, FakeTranscribe  # noqa: E402


@pytest.fixture(autouse=True)
def aws(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("MEDIA_BUCKET", BUCKET)
    monkeypatch.setenv("MODEL_ID", "eu.amazon.nova-pro-v1:0")
    monkeypatch.setenv("KMS_KEY_ARN", "arn:aws:kms:eu-west-1:111111111111:key/test")
    monkeypatch.setattr("suppliagent_tool_order_intake.intake.time.sleep", lambda _: None)
    with mock_aws():
        intake.reset_clients()
        s3: Any = boto3.client("s3")
        s3.create_bucket(
            Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": "eu-west-1"}
        )
        s3.put_object(Bucket=BUCKET, Key="media/con_anna/m1/wamid1.jpg", Body=JPEG)
        s3.put_object(Bucket=BUCKET, Key="media/con_anna/m2/wamid2.ogg", Body=b"OggS")
        s3.put_object(Bucket=BUCKET, Key="media/con_bruno/m9/wamid9.jpg", Body=JPEG)
        yield s3
        intake.reset_clients()


@pytest.fixture
def bedrock(monkeypatch: pytest.MonkeyPatch) -> FakeBedrock:
    fake = FakeBedrock()
    monkeypatch.setattr(intake, "_bedrock", lambda: fake)
    return fake


@pytest.fixture
def transcribe(monkeypatch: pytest.MonkeyPatch, aws: Any) -> FakeTranscribe:
    fake = FakeTranscribe(aws)
    monkeypatch.setattr(intake, "_transcribe", lambda: fake)
    return fake


@pytest.fixture(autouse=True)  # no test may reach EventBridge
def events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    sent: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(intake, "put_event", lambda _src, kind, detail: sent.append((kind, detail)))
    return sent
