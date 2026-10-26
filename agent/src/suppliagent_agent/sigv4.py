"""SigV4 signing for the AgentCore Gateway MCP endpoint (inbound auth = AWS IAM)."""

from collections.abc import Generator

import boto3
import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest


class GatewaySigV4Auth(httpx.Auth):
    """Signs every MCP request with the credentials of the boto3 chain (the Runtime role)."""

    requires_request_body = True

    def __init__(self, region: str, service: str = "bedrock-agentcore") -> None:
        self._region = region
        self._service = service
        self._session = boto3.Session()

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        credentials = self._session.get_credentials()
        if credentials is None:
            raise RuntimeError("no AWS credentials to sign the Gateway request")
        signed = AWSRequest(
            method=request.method,
            url=str(request.url),
            data=request.content,
            headers={"Content-Type": request.headers.get("Content-Type", "application/json")},
        )
        SigV4Auth(credentials.get_frozen_credentials(), self._service, self._region).add_auth(
            signed
        )
        request.headers.update(dict(signed.headers.items()))
        yield request
