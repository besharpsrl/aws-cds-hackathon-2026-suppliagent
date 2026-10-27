"""The simulator's events must be what the Inbound Router reads (T-14)."""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from inbound_router.normalize import whatsapp_messages

SPEC = importlib.util.spec_from_file_location(
    "simulate_channel", Path(__file__).parents[1] / "scripts" / "simulate_channel.py"
)
assert SPEC and SPEC.loader
sim: Any = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sim)

AT = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)


def test_text_event_is_read_by_the_router() -> None:
    event = sim.build_event("+393330000001", sim.text_message("ciao"), AT)

    [message] = whatsapp_messages(event)
    assert message.sender == "+393330000001"
    assert message.text == "ciao"
    assert message.provider_message_id.startswith("wamid.sim_")


def test_media_event_carries_a_simulated_media_id_and_caption() -> None:
    media = sim.media_message("image", "sim_" + "a" * 32, "image/jpeg", "bigliettino")
    event = sim.build_event("393330000001", media, AT)

    [message] = whatsapp_messages(event)
    [attachment] = message.attachments
    assert attachment.type == "image"
    assert attachment.mediaId == "sim_" + "a" * 32
    assert message.text == "bigliettino"


def test_every_event_has_its_own_message_id() -> None:
    ids = {
        whatsapp_messages(sim.build_event("+39333", sim.text_message("x"), AT))[
            0
        ].provider_message_id
        for _ in range(3)
    }
    assert len(ids) == 3  # a repeated run is not deduplicated by the Router


def test_conversation_id_matches_the_routers() -> None:
    assert sim.conversation_id("con_001") == "conv_con001"
