#!/usr/bin/env bash
# post-commit-lab-notebook.sh — Prompt for lab notebook entry after commit during research session
# Lightweight check: if research/NOTEBOOK.md exists, remind to log the commit.
set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
NOTEBOOK="$REPO_ROOT/research/NOTEBOOK.md"
SESSION_FILE="$REPO_ROOT/research/.session.json"

# Only act if a research session is active
[[ ! -f "$NOTEBOOK" ]] && exit 0
[[ ! -f "$SESSION_FILE" ]] && exit 0

# Get the commit info
COMMIT_SHA="$(git -C "$REPO_ROOT" log --format='%h' -1 2>/dev/null || echo 'unknown')"
COMMIT_MSG="$(git -C "$REPO_ROOT" log --format='%s' -1 2>/dev/null || echo 'unknown')"

# Extract current research question from session
QUESTION=""
if command -v python3 &>/dev/null; then
  QUESTION=$(python3 -c "
import json, sys
try:
    d = json.load(open('$SESSION_FILE'))
    print(d.get('question', ''))
except: pass
" 2>/dev/null)
fi

echo ""
echo "=== Research Session Active ==="
echo "Commit: $COMMIT_SHA — $COMMIT_MSG"
[[ -n "$QUESTION" ]] && echo "Research question: $QUESTION"
echo ""
echo "Consider adding a lab notebook entry linking this commit to your current hypothesis:"
echo "  /research-notebook add \"<what this commit tests or changes>\" --commit $COMMIT_SHA"
echo ""
