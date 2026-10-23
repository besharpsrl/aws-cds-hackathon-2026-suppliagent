#!/usr/bin/env bash
# PostToolUse hook (Edit|Write|MultiEdit): lint del solo file modificato.
# Exit 2 = segnala gli errori a Claude Code (stderr), che li corregge. Exit 0 = ok o strumento non ancora installato.
set -uo pipefail

FILE=$(python3 -c 'import json,sys
try:
    d=json.load(sys.stdin); print(d.get("tool_input",{}).get("file_path",""))
except Exception:
    print("")')

[ -z "$FILE" ] || [ ! -f "$FILE" ] && exit 0
ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
cd "$ROOT" || exit 0

case "$FILE" in
  *.py)
    command -v uv >/dev/null 2>&1 && [ -f pyproject.toml ] || exit 0
    OUT=$(uv run --quiet ruff check "$FILE" 2>&1) || { echo "ruff: errori in $FILE" >&2; echo "$OUT" | tail -40 >&2; exit 2; }
    uv run --quiet ruff format "$FILE" >/dev/null 2>&1 || true
    ;;
  *.ts|*.tsx)
    DIR=""
    case "$FILE" in */infra/*) DIR=infra ;; */console/*) DIR=console ;; esac
    [ -n "$DIR" ] && [ -d "$DIR/node_modules" ] || exit 0
    (cd "$DIR" && npx --no-install prettier --write "$FILE" >/dev/null 2>&1) || true
    OUT=$(cd "$DIR" && npx --no-install eslint "$FILE" 2>&1) || { echo "eslint: errori in $FILE" >&2; echo "$OUT" | tail -40 >&2; exit 2; }
    ;;
esac
exit 0
