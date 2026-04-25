#!/usr/bin/env bash
# pre-commit-ruff.sh — block commits with ruff format or check failures.
#
# Runs the SAME two checks CI runs (ruff format --check . and ruff check .),
# so failures surface locally before push instead of in GitHub Actions.
#
# Install: referenced from .claude/hooks/hooks.json as a PreToolUse entry on
# Bash commits (matcher: Bash, when: command contains 'git commit'). The
# Claude Code harness runs this script before executing the commit.
#
# Exit codes:
#   0 — all ruff checks pass; commit proceeds
#   2 — ruff format drift OR ruff check violations; commit blocked with a
#       plain-English reason on stderr that Claude sees
#
# Source: mirrors Cortex's .github/workflows/ci.yml Lint job (ruff format
# --check . + ruff check .) so local and CI results agree.

set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$REPO_ROOT"

if ! command -v ruff >/dev/null 2>&1; then
  echo "[pre-commit-ruff] ruff not installed — skipping (install: pip install ruff)" >&2
  exit 0
fi

fmt_out=$(ruff format --check . 2>&1)
fmt_rc=$?
chk_out=$(ruff check . 2>&1)
chk_rc=$?

if (( fmt_rc != 0 )) || (( chk_rc != 0 )); then
  echo "[pre-commit-ruff] BLOCKED — ruff CI-parity checks failed" >&2
  if (( fmt_rc != 0 )); then
    echo "" >&2
    echo "[pre-commit-ruff] ruff format --check . said:" >&2
    echo "$fmt_out" | tail -20 >&2
    echo "" >&2
    echo "[pre-commit-ruff] Fix with: ruff format ." >&2
  fi
  if (( chk_rc != 0 )); then
    echo "" >&2
    echo "[pre-commit-ruff] ruff check . said:" >&2
    echo "$chk_out" | tail -30 >&2
    echo "" >&2
    echo "[pre-commit-ruff] Fix with: ruff check --fix ." >&2
  fi
  exit 2
fi

exit 0
