"""Simulated WhatsApp customer (T-14, FN-31): publishes an EUM Social event on `wa-events`.

The real pipeline runs (Router -> debounce -> Dispatcher -> agent -> Notifier) without a WABA.

Usage:
  uv run python scripts/simulate_channel.py --env dev --from +393330000001 --text "ciao" --wait
  uv run python scripts/simulate_channel.py --env dev --from +393330000001 --image note.jpg --wait
  uv run python scripts/simulate_channel.py --env dev --from +393330000001 --audio voice.ogg --wait

`--from` must be in ChannelIdentities (seed numbers), otherwise the sender is UNKNOWN. Photos and
voice notes are uploaded to `sim/<mediaId>/` in the media bucket and the Router copies them to
`media/` (only while `notifierSandbox` is true). `--wait` prints the replies the Notifier records
in `Messages` (status SANDBOX: nothing is sent). Refuses to run when the sandbox is off.
"""

import argparse
import json
import mimetypes
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key


def build_event(
    sender: str, message: dict[str, Any], at: datetime, message_id: str | None = None
) -> dict[str, Any]:
    """EUM Social event: AWS header + `whatsAppWebhookEntry` as a JSON string."""
    entry = {
        "id": "sim-waba",
        "changes": [
            {
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "messages": [
                        {
                            "from": sender.lstrip("+"),
                            "id": f"wamid.sim_{uuid.uuid4().hex}",
                            **message,
                        }
                    ],
                },
            }
        ],
    }
    return {
        "context": {},
        "whatsAppWebhookEntry": json.dumps(entry),
        "aws_account_id": "simulator",
        "message_timestamp": at.astimezone(UTC).isoformat(timespec="milliseconds"),
        "messageId": message_id or str(uuid.uuid4()),
    }


def text_message(text: str) -> dict[str, Any]:
    return {"type": "text", "text": {"body": text}}


def media_message(kind: str, media_id: str, mime_type: str, caption: str | None) -> dict[str, Any]:
    media = {"id": media_id, "mime_type": mime_type, **({"caption": caption} if caption else {})}
    return {"type": kind, kind: media}


def conversation_id(contact_id: str) -> str:
    """As the Router derives it for a known contact."""
    return "conv_" + contact_id.replace("_", "")


def wait_for_replies(messages: Any, conv: str, since: str, timeout: int) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        items = messages.query(
            KeyConditionExpression=Key("conversationId").eq(conv) & Key("tsMessageId").gt(since),
            ConsistentRead=True,
        )["Items"]
        replies = [i for i in items if i["direction"] == "OUTBOUND"]
        if replies:
            return replies
        time.sleep(3)
    return []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env", required=True, choices=["dev"])
    parser.add_argument("--from", dest="sender", required=True, help="E.164, e.g. +393330000001")
    parser.add_argument("--text", help="message text, or the caption of --image")
    parser.add_argument("--image", type=Path)
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--wait", action="store_true", help="print the replies (up to --timeout)")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--profile")
    parser.add_argument("--region", default="eu-west-1")
    args = parser.parse_args()
    if bool(args.image) + bool(args.audio) > 1 or not (args.text or args.image or args.audio):
        parser.error("give --text, or one of --image / --audio")

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    ssm = session.client("ssm")

    def param(name: str) -> str:
        return str(ssm.get_parameter(Name=f"/suppliagent/{args.env}/{name}")["Parameter"]["Value"])

    # Replies must be recorded, not sent: a simulated message must never reach a real person.
    if param("notifierSandbox").lower() != "true":
        raise SystemExit(f"notifierSandbox is not 'true' in {args.env}: refusing to simulate")

    sender = "+" + args.sender.lstrip("+")
    identity: dict[str, Any] | None = (
        session.resource("dynamodb")
        .Table(f"suppliagent-{args.env}-channel-identities")
        .get_item(Key={"channelAddress": f"WHATSAPP#{sender}"})
        .get("Item")
    )
    if not identity:
        raise SystemExit(f"{sender} is not in ChannelIdentities: it would be an UNKNOWN sender")

    file = args.image or args.audio
    if file:
        kind = "image" if args.image else "audio"
        mime = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        media_id = f"sim_{uuid.uuid4().hex}"
        account = session.client("sts").get_caller_identity()["Account"]
        session.client("s3").put_object(
            Bucket=f"suppliagent-{args.env}-media-{account}",
            Key=f"sim/{media_id}/file{file.suffix.lower()}",
            Body=file.read_bytes(),
            ContentType=mime,
        )
        message = media_message(kind, media_id, mime, args.text)
    else:
        message = text_message(args.text)

    now = datetime.now(UTC)
    event = build_event(sender, message, now)
    topic = param("waEventsTopicArn")
    session.client("sns").publish(TopicArn=topic, Message=json.dumps(event))
    print(f"→ published as {sender} ({identity['role']}) on {topic.rsplit(':', 1)[-1]}")

    if args.wait:
        conv = conversation_id(identity["contactId"])
        since = now.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        messages = session.resource("dynamodb").Table(f"suppliagent-{args.env}-messages")
        replies = wait_for_replies(messages, conv, since, args.timeout)
        for reply in replies:
            print(f"← [{reply['status']}] {reply['text']}")
        if not replies:
            raise SystemExit(f"no reply in {args.timeout}s: check the DLQs and the Dispatcher logs")


if __name__ == "__main__":
    main()
