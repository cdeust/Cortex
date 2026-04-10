#!/usr/bin/env bash
# session-start.sh — Load context at session start
set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
TOOLS="$REPO_ROOT/tools"

echo "=== Zetetic Session Start ==="
echo ""

echo "## Repository"
echo "Branch: $(git -C "$REPO_ROOT" branch --show-current 2>/dev/null || echo 'unknown')"
echo "Uncommitted: $(git -C "$REPO_ROOT" status --porcelain 2>/dev/null | wc -l | tr -d ' ') files"
echo "Last commit: $(git -C "$REPO_ROOT" log --oneline -1 2>/dev/null || echo 'none')"
echo ""

echo "## Difficulty Books"
"$TOOLS/difficulty-book-manager.sh" status 2>/dev/null || echo "(none)"
echo ""

echo "## Agent Worktrees"
"$TOOLS/worktree-manager.sh" list 2>/dev/null || echo "(none)"
echo ""

echo "## Session Cache"
"$TOOLS/session-store.sh" load 2>/dev/null || echo "(no cached session)"
echo ""

echo "Reminder: call query_methodology for cognitive profile, recall for Cortex context."
