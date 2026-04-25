#!/usr/bin/env bash
# session-end-memory-drain.sh — SessionEnd hook: surface pending sync queue depth.
#
# Contract:
#   Precondition:  runs at session end; CLAUDE_PLUGIN_ROOT is set (or falls
#                  back to the directory two levels above this script).
#   Postcondition: if the sync queue is non-empty, prints queue depth and a
#                  single-line hint directing the next session to run
#                  /session:memory-sync.  Does NOT call Cortex MCP — bash
#                  cannot speak MCP.  Does NOT drain the queue.
#
# Re-entrant: safe to run multiple times; query is read-only.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd -P)}"
TOOL="$PLUGIN_ROOT/tools/memory-tool.sh"

[[ -x "$TOOL" ]] || exit 0   # tool absent: silent skip (hook must not block)

STATUS="$("$TOOL" sync-status 2>/dev/null || true)"

# Extract pending count from "queue: N pending, M claimed" line.
PENDING=$(printf '%s\n' "$STATUS" | awk -F'[: ,]+' '/^queue:/{print $2+0; exit}')
PENDING="${PENDING:-0}"

if (( PENDING > 0 )); then
  printf '\n[memory-drain] Cortex replica queue has %d pending job(s).\n' "$PENDING"
  printf '[memory-drain] Run /session:memory-sync at the start of the next session to sync.\n\n'
fi

exit 0
