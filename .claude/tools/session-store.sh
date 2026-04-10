#!/usr/bin/env bash
# session-store.sh — Save/load session context
#
# Usage:
#   tools/session-store.sh save "<context summary>"
#   tools/session-store.sh load
#
# Stores context in .claude/session-cache.json (Cortex integration is handled
# by Claude directly via MCP; this is the fallback for non-Cortex environments).
# Exit codes: 0 success, 1 error

set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
CACHE_DIR="$REPO_ROOT/.claude"
CACHE_FILE="$CACHE_DIR/session-cache.json"
ACTION="${1:-}"; CONTEXT="${2:-}"

case "$ACTION" in
  save)
    [[ -z "$CONTEXT" ]] && { echo "usage: $0 save \"<context>\"" >&2; exit 1; }
    mkdir -p "$CACHE_DIR"
    cat > "$CACHE_FILE" <<EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "branch": "$(git -C "$REPO_ROOT" branch --show-current 2>/dev/null || echo 'unknown')",
  "last_commit": "$(git -C "$REPO_ROOT" log --oneline -1 2>/dev/null || echo 'none')",
  "context": $(echo "$CONTEXT" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))' 2>/dev/null || echo "\"$CONTEXT\"")
}
EOF
    echo "Session saved to $CACHE_FILE" ;;

  load)
    if [[ -f "$CACHE_FILE" ]]; then
      cat "$CACHE_FILE"
    else
      echo "No cached session found. Use Cortex recall for persistent memory."
      exit 1
    fi ;;

  *) echo "usage: $0 <save|load> [context]" >&2; exit 1 ;;
esac
