"""Hackathon CDS rules (AGENTS.md §2, §8.7) checked on the runtime code, so CI fails early.

- Only the allowed CDS clients are used: `socialmessaging`, `sesv2`, `pinpoint-sms-voice-v2`;
  never `pinpoint` (v1, EUM Push included) nor `pinpoint-email`.
- Only the Notifier calls the CDS send APIs, and it really calls WhatsApp and SES.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIRS = ("services", "agent/src", "scripts", "seed")
NOTIFIER = ROOT / "services/notifier/src"
SEND_CALL = re.compile(
    r"\.(send_whatsapp_message|send_email|send_raw_email|send_text_message|send_rcs_message|send_media_message)\("
)
CLIENT = re.compile(r"""client\(\s*["']([\w-]+)["']""")
FORBIDDEN_CLIENTS = {"pinpoint", "pinpoint-email", "sesv1", "ses"}


def _runtime_files() -> list[Path]:
    files = [p for d in RUNTIME_DIRS for p in (ROOT / d).rglob("*.py")]
    return [p for p in files if "tests" not in p.relative_to(ROOT).parts and ".venv" not in p.parts]


def test_no_forbidden_cds_clients() -> None:
    used = {
        (str(p.relative_to(ROOT)), name)
        for p in _runtime_files()
        for name in CLIENT.findall(p.read_text(encoding="utf-8"))
        if name in FORBIDDEN_CLIENTS
    }
    assert not used, f"forbidden CDS clients (allowed: socialmessaging, sesv2, sms v2): {used}"


def test_only_the_notifier_sends() -> None:
    senders = {
        str(p.relative_to(ROOT))
        for p in _runtime_files()
        if SEND_CALL.search(p.read_text(encoding="utf-8")) and NOTIFIER not in p.parents
    }
    assert not senders, f"CDS send APIs outside services/notifier (AGENTS §8.7): {senders}"


def test_the_notifier_really_calls_whatsapp_and_ses() -> None:
    code = "\n".join(p.read_text(encoding="utf-8") for p in NOTIFIER.rglob("*.py"))
    assert re.search(r"""client\(\s*["']socialmessaging["']""", code)
    assert re.search(r"""client\(\s*["']sesv2["']""", code)
    assert ".send_whatsapp_message(" in code
    assert ".send_email(" in code
    assert re.search(r"""client\(\s*["']pinpoint-sms-voice-v2["']""", code)
    assert ".send_rcs_message(" in code
    assert ".send_text_message(" in code
