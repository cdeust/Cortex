#!/usr/bin/env bash
# pre-commit-zetetic.sh — Enforce zetetic standard before commits
# Blocks commit if: invented constants, unsourced claims, or TODOs without difficulty-book refs.
set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
TOOLS="$REPO_ROOT/tools"

output=$("$TOOLS/zetetic-checker.sh" --staged 2>&1) || {
  echo "BLOCKED: Zetetic violations in staged files." >&2
  echo "$output" >&2
  exit 2
}

"$TOOLS/difficulty-book-manager.sh" check 2>&1 || {
  echo "WARNING: Difficulty book has unaddressed hardest case." >&2
}

exit 0
