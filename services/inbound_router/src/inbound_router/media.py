"""Media to S3 (T-23, FN-05, FN-06; TECHNICAL_FLOWS §3.4): WhatsApp media through EUM Social and
email attachments, under `media/<owner>/<messageId>/` in the media bucket. Runs inside the router:
a failed download fails the message, which SQS retries and then moves to the DLQ (E-02).

Environment: `MEDIA_BUCKET`, `WA_PHONE_NUMBER_ID_PARAM` (SSM name of the EUM Social number id),
`SANDBOX_PARAM` (SSM name of `notifierSandbox`: simulated media, see `_fetch_simulated`).
"""

import os
import re
from functools import cache
from typing import Any

import boto3
from aws_lambda_powertools import Logger
from suppliagent_shared.errors import SuppliAgentError
from suppliagent_shared.messages import Attachment, AttachmentType

from inbound_router.normalize import EmailFile, RawMessage

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# Accepted types -> key extension. No SVG (scripts; the console shows images inline), no legacy
# .xls (macros). The extension comes from here, never from the sender's file name.
IMAGES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/heic": ".heic",
    "image/heif": ".heif",
}
DOCUMENTS = {"application/pdf": ".pdf", XLSX: ".xlsx", "text/csv": ".csv"}
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENTS = 10
# Not processed: the agent asks for a photo or text (§3.4).
NOT_FETCHED = {AttachmentType.VIDEO, AttachmentType.STICKER}
SIMULATED_ID = re.compile(r"^sim_[0-9a-f]{32}$")  # `scripts/simulate_channel.py` (T-14)
UNSET = "UNSET"  # SSM default until the WABA is connected (ChannelsStack)
logger = Logger(service="inbound-router")


@cache
def _s3() -> Any:
    return boto3.client("s3")


@cache
def _ssm() -> Any:
    return boto3.client("ssm")


@cache
def _social() -> Any:
    return boto3.client("socialmessaging")


def _mime(mime_type: str | None) -> str:
    return (mime_type or "").split(";")[0].strip().lower()


def _kind(mime: str) -> AttachmentType | None:
    """Type of an accepted file; None for anything not allowed (E-13)."""
    if mime in IMAGES:
        return AttachmentType.IMAGE
    if mime.startswith("audio/"):
        return AttachmentType.AUDIO
    if mime in DOCUMENTS:
        return AttachmentType.DOCUMENT
    return None


def _looks_like(mime: str, content: bytes) -> bool:
    """The declared type must match the file's first bytes: email attachments are not scanned
    beyond SES, and a mislabelled executable must not reach the console."""
    signatures: dict[str, tuple[bytes, ...]] = {
        "image/jpeg": (b"\xff\xd8\xff",),
        "image/png": (b"\x89PNG\r\n\x1a\n",),
        "image/gif": (b"GIF87a", b"GIF89a"),
        "application/pdf": (b"%PDF-",),
        XLSX: (b"PK\x03\x04",),
    }
    if mime in signatures:
        return content.startswith(signatures[mime])
    if mime == "image/webp":
        return content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    if mime in ("image/heic", "image/heif"):
        return content[4:8] == b"ftyp"
    if mime == "text/csv":
        return b"\x00" not in content
    return False  # email audio and anything else: not accepted


def store(raw: RawMessage, owner: str, message_id: str) -> tuple[Attachment, ...]:
    """Attachments of `raw`, with `s3Uri` where the file was stored. A rejected file stays in the
    list without `s3Uri`, so the agent can tell the customer (E-13)."""
    bucket = os.environ["MEDIA_BUCKET"]
    prefix = f"media/{owner}/{message_id}/"
    fetched = [_fetch(a, bucket, prefix) for a in raw.attachments]
    uploaded = [
        _upload(f, f"{prefix}{i}", bucket, raw.files_scanned and i < MAX_ATTACHMENTS)
        for i, f in enumerate(raw.files)
    ]
    return tuple(fetched + uploaded)


def _fetch(attachment: Attachment, bucket: str, prefix: str) -> Attachment:
    if (
        not attachment.mediaId
        or attachment.type in NOT_FETCHED
        or _kind(_mime(attachment.mimeType)) is None
    ):
        return attachment
    if SIMULATED_ID.fullmatch(attachment.mediaId) and _sandbox():
        return _fetch_simulated(attachment, bucket, prefix)
    phone_number_id = _ssm().get_parameter(Name=os.environ["WA_PHONE_NUMBER_ID_PARAM"])[
        "Parameter"
    ]["Value"]
    if phone_number_id == UNSET:
        logger.warning("media not fetched: WhatsApp phone number not configured")
        return attachment
    response = _social().get_whatsapp_message_media(
        mediaId=attachment.mediaId,
        originationPhoneNumberId=phone_number_id,
        destinationS3File={"bucketName": bucket, "key": prefix},
    )
    if response.get("fileSize", 0) * 1024 > MAX_FILE_BYTES:  # fileSize is in KB
        logger.info("media dropped: too large", mimeType=attachment.mimeType)
        return attachment  # left to the bucket lifecycle, never handed to the agent
    # The service appends `<mediaId>.<extension>` to the key prefix.
    found = _s3().list_objects_v2(Bucket=bucket, Prefix=prefix + attachment.mediaId)
    keys = [o["Key"] for o in found.get("Contents", [])]
    if not keys:
        raise SuppliAgentError("media not found after download")  # retried by SQS
    return attachment.model_copy(update={"s3Uri": f"s3://{bucket}/{keys[0]}"})


def _sandbox() -> bool:
    """Simulated media only while the Notifier is in sandbox, so never in `demo` (T-14). Unlike
    the Notifier, a missing parameter means off."""
    try:
        value = _ssm().get_parameter(Name=os.environ["SANDBOX_PARAM"])["Parameter"]["Value"]
    except _ssm().exceptions.ParameterNotFound:
        return False
    return str(value).lower() == "true"


def _fetch_simulated(attachment: Attachment, bucket: str, prefix: str) -> Attachment:
    """The simulator stores the file under `sim/<mediaId>/` instead of EUM Social: copy it to
    where a real download would land (same key shape, so the rest of the flow is the real one)."""
    found = _s3().list_objects_v2(Bucket=bucket, Prefix=f"sim/{attachment.mediaId}/")
    objects = found.get("Contents", [])
    if not objects:
        raise SuppliAgentError("simulated media not found")  # retried by SQS
    source = objects[0]
    if source["Size"] > MAX_FILE_BYTES:
        return attachment
    key = f"{prefix}{attachment.mediaId}{os.path.splitext(source['Key'])[1]}"
    _s3().copy_object(Bucket=bucket, Key=key, CopySource={"Bucket": bucket, "Key": source["Key"]})
    return attachment.model_copy(update={"s3Uri": f"s3://{bucket}/{key}"})


def _upload(file: EmailFile, key_stem: str, bucket: str, allowed: bool) -> Attachment:
    mime = _mime(file.mime_type)
    attachment_type = _kind(mime)
    rejected = Attachment(type=attachment_type or AttachmentType.DOCUMENT, mimeType=mime[:100])
    if (
        not allowed
        or attachment_type is None
        or len(file.content) > MAX_FILE_BYTES
        or not _looks_like(mime, file.content)
    ):
        logger.info("attachment rejected", mimeType=mime[:100], size=len(file.content))
        return rejected
    key = key_stem + {**IMAGES, **DOCUMENTS}[mime]
    _s3().put_object(
        Bucket=bucket,
        Key=key,
        Body=file.content,
        ContentType=mime,
        # Documents are downloaded, never rendered by the browser.
        ContentDisposition="inline" if attachment_type is AttachmentType.IMAGE else "attachment",
    )
    return rejected.model_copy(update={"s3Uri": f"s3://{bucket}/{key}"})
