#!/usr/bin/env bash
# session-end.sh — Record session context before exit
set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
TOOLS="$REPO_ROOT/tools"

# Auto-save a minimal session summary
BRANCH="$(git -C "$REPO_ROOT" branch --show-current 2>/dev/null || echo 'unknown')"
LAST_COMMIT="$(git -C "$REPO_ROOT" log --oneline -1 2>/dev/null || echo 'none')"
UNCOMMITTED="$(git -C "$REPO_ROOT" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"

"$TOOLS/session-store.sh" save "Branch: $BRANCH | Last: $LAST_COMMIT | Uncommitted: $UNCOMMITTED files" 2>/dev/null || true

echo "Session context saved." >&2
exit 0
