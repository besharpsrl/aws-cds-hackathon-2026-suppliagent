"""Media to S3 (T-23, FN-05, FN-06; TECHNICAL_FLOWS §3.4): WhatsApp media through EUM Social and
email attachments, under `media/<owner>/<messageId>/` in the media bucket. Runs inside the router:
a failed download fails the message, which SQS retries and then moves to the DLQ (E-02).

Environment: `MEDIA_BUCKET`, `WA_PHONE_NUMBER_ID_PARAM` (SSM name of the EUM Social number id).
"""

import os
import re
from functools import cache
from pathlib import PurePosixPath
from typing import Any

import boto3
from aws_lambda_powertools import Logger
from suppliagent_shared.errors import SuppliAgentError
from suppliagent_shared.messages import Attachment, AttachmentType

from inbound_router.normalize import EmailFile, RawMessage

# SVG is left out on purpose: it can carry scripts and the console shows images inline.
IMAGES = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/heic", "image/heif"}
DOCUMENTS = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "text/csv",
}
MAX_FILE_BYTES = 10 * 1024 * 1024
# Not processed: the agent asks for a photo or text (§3.4).
NOT_FETCHED = {AttachmentType.VIDEO, AttachmentType.STICKER}
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


def _kind(mime_type: str | None) -> AttachmentType | None:
    """Type of an accepted file; None for anything not allowed (E-13)."""
    mime = (mime_type or "").split(";")[0].strip().lower()
    if mime in IMAGES:
        return AttachmentType.IMAGE
    if mime.startswith("audio/"):
        return AttachmentType.AUDIO
    if mime in DOCUMENTS:
        return AttachmentType.DOCUMENT
    return None


def store(raw: RawMessage, owner: str, message_id: str) -> tuple[Attachment, ...]:
    """Attachments of `raw` with `s3Uri` set where the file was stored."""
    bucket = os.environ["MEDIA_BUCKET"]
    prefix = f"media/{owner}/{message_id}/"
    fetched = tuple(_fetch(a, bucket, prefix) for a in raw.attachments)
    uploaded = tuple(
        a for i, f in enumerate(raw.files) if (a := _upload(f, f"{prefix}{i}", bucket))
    )
    return fetched + uploaded


def _fetch(attachment: Attachment, bucket: str, prefix: str) -> Attachment:
    if (
        not attachment.mediaId
        or attachment.type in NOT_FETCHED
        or _kind(attachment.mimeType) is None
    ):
        return attachment
    phone_number_id = _ssm().get_parameter(Name=os.environ["WA_PHONE_NUMBER_ID_PARAM"])[
        "Parameter"
    ]["Value"]
    if phone_number_id == UNSET:
        logger.warning("media not fetched: WhatsApp phone number not configured")
        return attachment
    _social().get_whatsapp_message_media(
        mediaId=attachment.mediaId,
        originationPhoneNumberId=phone_number_id,
        destinationS3File={"bucketName": bucket, "key": prefix},
    )
    # The service appends `<mediaId>.<extension>` to the key prefix.
    found = _s3().list_objects_v2(Bucket=bucket, Prefix=prefix + attachment.mediaId)
    keys = [o["Key"] for o in found.get("Contents", [])]
    if not keys:
        raise SuppliAgentError("media not found after download")  # retried by SQS
    return attachment.model_copy(update={"s3Uri": f"s3://{bucket}/{keys[0]}"})


def _upload(file: EmailFile, key_stem: str, bucket: str) -> Attachment | None:
    attachment_type = _kind(file.mime_type)
    if attachment_type is None or len(file.content) > MAX_FILE_BYTES:
        logger.info("attachment dropped", mimeType=file.mime_type, size=len(file.content))
        return None
    suffix = re.sub(r"[^a-z0-9.]", "", PurePosixPath(file.filename).suffix.lower())[:8]
    key = key_stem + suffix
    _s3().put_object(Bucket=bucket, Key=key, Body=file.content, ContentType=file.mime_type)
    return Attachment(type=attachment_type, mimeType=file.mime_type, s3Uri=f"s3://{bucket}/{key}")
