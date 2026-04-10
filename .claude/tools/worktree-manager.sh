#!/usr/bin/env bash
# worktree-manager.sh — Manage agent worktrees
#
# Usage:
#   tools/worktree-manager.sh list                  # show active agent worktrees
#   tools/worktree-manager.sh cleanup               # remove merged worktrees
#   tools/worktree-manager.sh status <agent-name>   # show last commit in worktree
#
# Exit codes: 0 success, 1 error, 2 usage error

set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
ACTION="${1:-}"; AGENT="${2:-}"

[[ -z "$ACTION" ]] && { echo "usage: $0 <list|cleanup|status> [agent]" >&2; exit 2; }

case "$ACTION" in
  list)
    echo "Active agent worktrees:"
    git -C "$REPO_ROOT" worktree list 2>/dev/null | grep "agent/" || echo "  (none)"
    ;;

  cleanup)
    echo "Cleaning up merged agent worktrees..."
    cleaned=0
    while IFS= read -r line; do
      path=$(echo "$line" | awk '{print $1}')
      branch=$(echo "$line" | awk '{print $3}' | tr -d '[]')
      [[ "$branch" != agent/* ]] && continue
      # Check if branch is merged into current
      if git -C "$REPO_ROOT" branch --merged 2>/dev/null | grep -q "${branch#*/}" 2>/dev/null; then
        echo "  Removing: $path ($branch)"
        git -C "$REPO_ROOT" worktree remove "$path" 2>/dev/null || true
        git -C "$REPO_ROOT" branch -d "$branch" 2>/dev/null || true
        cleaned=$((cleaned + 1))
      fi
    done < <(git -C "$REPO_ROOT" worktree list 2>/dev/null)
    echo "Cleaned $cleaned worktree(s)."
    ;;

  status)
    [[ -z "$AGENT" ]] && { echo "usage: $0 status <agent-name>" >&2; exit 2; }
    worktree=$(git -C "$REPO_ROOT" worktree list 2>/dev/null | grep "$AGENT" | head -1 | awk '{print $1}')
    if [[ -z "$worktree" ]]; then
      echo "No active worktree for agent: $AGENT"
      exit 1
    fi
    echo "Agent: $AGENT"
    echo "Path: $worktree"
    echo "Last commit: $(git -C "$worktree" log --oneline -1 2>/dev/null || echo 'none')"
    echo "Uncommitted: $(git -C "$worktree" status --porcelain 2>/dev/null | wc -l | tr -d ' ') files"
    ;;

  *) echo "usage: $0 <list|cleanup|status> [agent]" >&2; exit 2 ;;
esac
