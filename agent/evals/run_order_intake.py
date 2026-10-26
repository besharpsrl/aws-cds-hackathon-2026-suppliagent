"""Scores `extract_order_lines` on the handwritten notes in `data/bigliettini/` (T-43, FN-05).

    uv run python agent/evals/run_order_intake.py [--model eu.amazon.nova-pro-v1:0]

Calls Bedrock (InvokeModel only, one call per note) with the current AWS credentials, region from
`AWS_REGION`/`AWS_DEFAULT_REGION` (eu-west-1). A line counts as correct when a returned line is
close to the expected text and the quantity is the same: an approximation of the FN-05 criterion
(>= 90% of the lines on >= 15 notes, T-53), not the criterion itself.
Results: `results/` (git-ignored).
"""

import argparse
import json
import os
import re
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from suppliagent_tool_order_intake.intake import Extraction, _converse

DATA = Path(__file__).parent / "data" / "bigliettini"
RESULTS = Path(__file__).parent / "results"
SIMILAR = 0.6
FORMATS = {".jpeg": "jpeg", ".jpg": "jpeg", ".png": "png"}


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def written(line: Any) -> str:
    return " ".join(p for p in (line.rawQuantity, line.rawUnit, line.rawText) if p)


def same_quantity(line: Any, expected: dict[str, Any]) -> bool:
    if expected["quantity"] is None:
        return True
    found = re.search(r"\d+(?:[.,]\d+)?", line.rawQuantity or "")
    return found is not None and float(found[0].replace(",", ".")) == float(expected["quantity"])


def score(extraction: Extraction, expected: dict[str, Any]) -> dict[str, Any]:
    lines = [line for line in extraction.lines if line.status == "READ"]
    right = [
        any(
            similar(written(line), e["rawText"]) >= SIMILAR and same_quantity(line, e)
            for line in lines
        )
        for e in expected["lines"]
    ]
    correct = sum(right)
    forbidden = [*expected["struckOut"], *expected["notes"]]
    leaked = [
        line.rawText
        for line in lines
        if any(similar(written(line), text) >= SIMILAR for text in forbidden)
    ]
    return {
        "expected": len(expected["lines"]),
        "returned": len(extraction.lines),
        "correct": correct,
        "unreadable": len(extraction.lines) - len(lines),
        # read lines that match no expected line: wrong readings passed off as valid
        "wrongButRead": sum(
            not any(similar(written(line), e["rawText"]) >= SIMILAR for e in expected["lines"])
            for line in lines
        ),
        "struckOutOrNoteAsLine": leaked,
        "notesIgnored": len(extraction.ignoredNotes),
        "struckOut": len(extraction.struckOut),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="eu.amazon.nova-pro-v1:0")
    os.environ["MODEL_ID"] = parser.parse_args().model
    report: dict[str, Any] = {}
    for image in sorted(p for p in DATA.iterdir() if p.suffix in FORMATS):
        expected = json.loads((DATA / f"{image.stem}.expected.json").read_text())
        content: list[dict[str, Any]] = [
            {"image": {"format": FORMATS[image.suffix], "source": {"bytes": image.read_bytes()}}},
            {"text": "Report the order lines in this photo."},
        ]
        report[image.stem] = score(_converse(content), expected)
        print(image.stem, report[image.stem])
    total = sum(r["expected"] for r in report.values())
    correct = sum(r["correct"] for r in report.values())
    print(f"lines correct: {correct}/{total} ({correct / total:.0%})")
    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (RESULTS / f"order_intake_{stamp}.json").write_text(
        json.dumps({"model": os.environ["MODEL_ID"], "notes": report}, indent=2)
    )


if __name__ == "__main__":
    main()
