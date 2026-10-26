"""Checks the WhatsApp template definitions against Meta's submission rules (T-28)."""

import json
import re
from pathlib import Path
from typing import Any

import pytest

TEMPLATE_DIR = Path(__file__).parents[1] / "services" / "notifier" / "whatsapp_templates"
NAMES = {"order_confirmation", "order_pending_reminder", "delivery_update", "reorder_suggestion"}
LANGUAGES = {"it", "en"}
PLACEHOLDER = re.compile(r"\{\{(\d+)\}\}")

FILES = sorted(TEMPLATE_DIR.glob("*.json"))


def load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def component(template: dict[str, Any], kind: str) -> dict[str, Any] | None:
    return next((c for c in template["components"] if c["type"] == kind), None)


def test_every_template_exists_in_every_language() -> None:
    assert {f.name for f in FILES} == {f"{n}.{lang}.json" for n in NAMES for lang in LANGUAGES}


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_template_follows_meta_rules(path: Path) -> None:
    template = load(path)
    name, language = path.stem.split(".")
    assert template["name"] == name
    assert re.fullmatch(r"[a-z0-9_]{1,512}", name)
    assert template["language"] == language
    assert template["category"] in {"UTILITY", "MARKETING"}

    body = component(template, "BODY")
    assert body is not None
    text = body["text"]
    assert len(text) <= 1024
    assert not text.startswith("{{") and not text.rstrip(".!? ").endswith("}}")
    assert "}}{{" not in text.replace(" ", "")
    numbers = [int(n) for n in PLACEHOLDER.findall(text)]
    assert numbers == list(range(1, len(numbers) + 1)), "placeholders must be {{1}}..{{n}} in order"
    assert len(body["example"]["body_text"][0]) == len(numbers)

    for kind in ("HEADER", "FOOTER"):
        part = component(template, kind)
        if part:
            assert len(part["text"]) <= 60
            assert not PLACEHOLDER.search(part["text"])

    buttons = component(template, "BUTTONS")
    if buttons:
        assert len(buttons["buttons"]) <= 10
        for button in buttons["buttons"]:
            assert button["type"] == "QUICK_REPLY"
            assert len(button["text"]) <= 25


@pytest.mark.parametrize("name", sorted(NAMES))
def test_languages_share_variables_and_buttons(name: str) -> None:
    def shape(lang: str) -> tuple[str, int, int]:
        template = load(TEMPLATE_DIR / f"{name}.{lang}.json")
        body = component(template, "BODY")
        buttons = component(template, "BUTTONS")
        assert body is not None
        return (
            template["category"],
            len(PLACEHOLDER.findall(body["text"])),
            len(buttons["buttons"]) if buttons else 0,
        )

    assert shape("it") == shape("en")
