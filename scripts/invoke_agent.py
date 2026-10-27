"""Send one message to the deployed agent, as the turn dispatcher (T-22) will do.

Usage:
  uv run python scripts/invoke_agent.py --env dev --address WHATSAPP#+393330000001 --text "ciao"
  uv run python scripts/invoke_agent.py --env dev --address WHATSAPP#+393330000001 \\
      --image s3://suppliagent-dev-media-<account>/media/con_001/t1/note.jpg

`--image`/`--audio` take the S3 URI of a file already uploaded under `media/<contactId>/…` (what the
Inbound Router does for real messages); repeat them for several attachments in one turn.

Resolves the role from ChannelIdentities (TECHNICAL_FLOWS §3.2), builds the turn request (§6.2)
and calls InvokeAgentRuntime. The same --conversation keeps the history (same runtime session).
"""

import argparse
import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key


def session_id(conversation_id: str) -> str:
    """Runtime session per conversation (33–256 chars): same conversation, same history."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"suppliagent:{conversation_id}"))


def resolve(dynamodb: Any, env: str, address: str) -> dict[str, Any]:
    def table(name: str) -> Any:
        return dynamodb.Table(f"suppliagent-{env}-{name}")

    identity = table("channel-identities").get_item(Key={"channelAddress": address}).get("Item")
    if not identity:
        return {"role": "UNKNOWN", "contactId": None, "customerIds": [], "locale": "it-IT"}
    contact_id, role = identity["contactId"], identity["role"]
    if role == "SALES_REP":
        rep = table("sales-reps").get_item(Key={"repId": contact_id})["Item"]
        portfolio = table("customers").query(
            IndexName="by-repId", KeyConditionExpression=Key("repId").eq(contact_id)
        )["Items"]
        customer_ids = sorted(c["customerId"] for c in portfolio)
        language = rep["language"]
    else:
        contact = table("contacts").get_item(Key={"contactId": contact_id})["Item"]
        customer_ids, language = contact["customerIds"], contact["language"]
    return {
        "role": role,
        "contactId": contact_id,
        "customerIds": customer_ids,
        "locale": "en-GB" if language == "en" else "it-IT",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env", required=True, choices=["dev"])
    parser.add_argument("--address", required=True, help="CHANNEL#address, e.g. WHATSAPP#+39...")
    parser.add_argument("--text")
    parser.add_argument("--image", action="append", default=[], metavar="S3_URI")
    parser.add_argument("--audio", action="append", default=[], metavar="S3_URI")
    parser.add_argument("--conversation", help="default: derived from the address")
    parser.add_argument("--profile")
    parser.add_argument("--region", default="eu-west-1")
    args = parser.parse_args()
    if not (args.text or args.image or args.audio):
        parser.error("give --text, --image or --audio")

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    digest = hashlib.sha256(args.address.encode()).hexdigest()[:12]
    conversation_id = args.conversation or f"conv_cli_{digest}"
    caller = resolve(session.resource("dynamodb"), args.env, args.address)
    turn = {
        "conversationId": conversation_id,
        "channelAddress": args.address,
        "channel": args.address.split("#", 1)[0],
        "activeCustomerId": caller["customerIds"][0] if len(caller["customerIds"]) == 1 else None,
        "messages": [
            {
                "messageId": f"cli_{uuid.uuid4().hex[:8]}",
                "ts": datetime.now(UTC).isoformat(timespec="seconds"),
                **({"text": args.text} if args.text else {}),
                "attachments": [
                    *({"type": "image", "s3Uri": uri} for uri in args.image),
                    *({"type": "audio", "s3Uri": uri} for uri in args.audio),
                ],
            }
        ],
        **caller,
    }
    runtime_arn = session.client("ssm").get_parameter(
        Name=f"/suppliagent/{args.env}/agentRuntimeArn"
    )["Parameter"]["Value"]
    print(f"→ {caller['role']} {caller['contactId'] or ''} {conversation_id}")
    response = session.client("bedrock-agentcore").invoke_agent_runtime(
        agentRuntimeArn=runtime_arn,
        runtimeSessionId=session_id(conversation_id),
        payload=json.dumps(turn).encode(),
    )
    result = json.loads(response["response"].read())
    print(result.get("reply") or json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
