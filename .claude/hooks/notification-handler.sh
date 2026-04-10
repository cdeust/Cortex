#!/usr/bin/env bash
# notification-handler.sh — Handle subagent/background task completion
set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

# Read notification from stdin
NOTIFICATION=""
if ! [ -t 0 ]; then
  NOTIFICATION="$(cat)"
fi

# Log the notification
echo "=== Agent Task Completed ===" >&2
echo "$NOTIFICATION" | head -5 >&2

# Check for unmerged agent worktrees
ACTIVE=$(git -C "$REPO_ROOT" worktree list 2>/dev/null | grep "agent/" | wc -l | tr -d ' ')
if [[ "$ACTIVE" -gt 0 ]]; then
  echo "Active agent worktrees: $ACTIVE (run /agent-status for details)" >&2
fi

exit 0
