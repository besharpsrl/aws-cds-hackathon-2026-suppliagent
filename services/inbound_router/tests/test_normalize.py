"""Channel event -> RawMessage (FN-01, TECHNICAL_FLOWS §3.1)."""

from collections.abc import Callable
from typing import Any

import pytest
from inbound_router.normalize import email_message, whatsapp_messages
from suppliagent_shared.messages import AttachmentType
from suppliagent_shared.models import Channel

Builder = Callable[..., Any]


def test_whatsapp_text(wa_event: Builder) -> None:
    event = wa_event(
        [{"from": "393330000001", "id": "wamid.1", "timestamp": "1", "type": "text",
          "text": {"body": "ciao"}}]
    )  # fmt: skip
    [msg] = whatsapp_messages(event)
    assert msg.channel is Channel.WHATSAPP
    assert (msg.provider_message_id, msg.sender, msg.text) == ("wamid.1", "+393330000001", "ciao")
    assert msg.received_at == "2026-10-26T10:00:00.123Z"


def test_whatsapp_photo_voice_and_unsupported_media(wa_event: Builder) -> None:
    event = wa_event(
        [
            {"from": "39333", "id": "w1", "type": "image",
             "image": {"mime_type": "image/jpeg", "id": "530", "caption": "ordine"}},
            {"from": "39333", "id": "w2", "type": "audio",
             "audio": {"mime_type": "audio/ogg", "id": "531"}},
            {"from": "39333", "id": "w3", "type": "sticker", "sticker": {"id": "532"}},
        ]
    )  # fmt: skip
    photo, voice, sticker = whatsapp_messages(event)
    assert photo.text == "ordine"
    assert photo.attachments[0].type is AttachmentType.IMAGE
    assert (photo.attachments[0].mediaId, photo.attachments[0].mimeType) == ("530", "image/jpeg")
    assert voice.attachments[0].type is AttachmentType.AUDIO and voice.text is None
    assert sticker.attachments[0].type is AttachmentType.STICKER


def test_messages_of_one_event_keep_their_order(wa_event: Builder) -> None:
    event = wa_event(
        [{"from": "39333", "id": f"w{i}", "type": "text", "text": {"body": "x"}} for i in range(3)]
    )
    stamps = [m.received_at for m in whatsapp_messages(event)]
    assert stamps == sorted(stamps) and len(set(stamps)) == 3


def test_whatsapp_button_and_list_replies(wa_event: Builder) -> None:
    event = wa_event(
        [
            {"from": "39333", "id": "w1", "type": "interactive", "interactive": {
                "type": "button_reply", "button_reply": {"id": "confirm", "title": "Confermo"}}},
            {"from": "39333", "id": "w2", "type": "interactive", "interactive": {
                "type": "list_reply", "list_reply": {"id": "line_3_opt_1", "title": "Mozzarella"}}},
            {"from": "39333", "id": "w3", "type": "button",
             "button": {"payload": "stop", "text": "Stop proposte"}},
        ]
    )  # fmt: skip
    replies = [m.interactive_reply for m in whatsapp_messages(event)]
    assert [(r.id, r.title) for r in replies if r] == [
        ("confirm", "Confermo"),
        ("line_3_opt_1", "Mozzarella"),
        ("stop", "Stop proposte"),
    ]


def test_whatsapp_statuses_and_reactions_are_not_messages(wa_event: Builder) -> None:
    statuses = wa_event(None, statuses=[{"id": "wamid.1", "status": "delivered"}])
    reaction = wa_event([{"from": "39333", "id": "w1", "type": "reaction", "reaction": {}}])
    assert whatsapp_messages(statuses) == []
    assert whatsapp_messages(reaction) == []


def test_email_body_sender_and_timestamp(ses_notification: Builder, raw_mail: Builder) -> None:
    msg = email_message(ses_notification(), raw_mail("10 kg farina 00\n2 cs pomodori"))
    assert msg.channel is Channel.EMAIL
    assert msg.provider_message_id == "ses-abc"
    assert msg.sender == "ordini.fornoantico@example.com"
    assert msg.text == "Ordine\n10 kg farina 00\n2 cs pomodori"
    assert msg.received_at == "2026-10-26T09:30:00.250Z"
    assert msg.order_id is None
    assert msg.sender_verified


@pytest.mark.parametrize("dmarc", ["FAIL", "GRAY", "PROCESSING_FAILED"])
def test_email_without_dmarc_pass_is_not_verified(
    dmarc: str, ses_notification: Builder, raw_mail: Builder
) -> None:
    msg = email_message(ses_notification(dmarc=dmarc), raw_mail("10 kg farina"))
    assert not msg.sender_verified


def test_email_reply_drops_quoted_text_and_correlates_the_order(
    ses_notification: Builder, raw_mail: Builder
) -> None:
    body = "Confermo\n\nIl lun 26 ott 2026 alle 09:00 SuppliAgent ha scritto:\n> Riepilogo ordine"
    msg = email_message(ses_notification("ordine+ord_789@ordini.example.com"), raw_mail(body))
    assert msg.text == "Ordine\nConfermo"
    assert msg.order_id == "ord_789"
