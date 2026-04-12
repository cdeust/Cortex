#!/usr/bin/env bash
# post-research-provenance.sh — Append URL/query to active provenance file after research tool calls
# Fires after WebFetch/WebSearch. Lightweight (< 1s). Silent no-op if no active provenance.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
TOOLS="$REPO_ROOT/tools"
RESEARCH_DIR="$REPO_ROOT/research"

# Guard: provenance-manager must exist
[[ ! -x "$TOOLS/provenance-manager.sh" ]] && exit 0

# Guard: check for active research session
PROVENANCE_FILE=""
if [[ -f "$RESEARCH_DIR/NOTEBOOK.md" ]]; then
  # Find the most recent .provenance.md in the research directory
  PROVENANCE_FILE="$(find "$RESEARCH_DIR" -maxdepth 2 -name '*.provenance.md' -type f -print0 \
    | xargs -0 ls -t 2>/dev/null | head -1)"
fi

# Also check for standalone .provenance.md in repo root
if [[ -z "$PROVENANCE_FILE" && -f "$REPO_ROOT/.provenance.md" ]]; then
  PROVENANCE_FILE="$REPO_ROOT/.provenance.md"
fi

# Guard: no active provenance file — silent no-op
[[ -z "$PROVENANCE_FILE" ]] && exit 0

# Extract URL or query from hook arguments
# $1 = tool name (WebFetch or WebSearch), $2 = URL or query string
TOOL_NAME="${1:-unknown}"
SOURCE="${2:-}"
[[ -z "$SOURCE" ]] && exit 0

TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

# Append to provenance via the manager
"$TOOLS/provenance-manager.sh" append \
  --file "$PROVENANCE_FILE" \
  --source "$SOURCE" \
  --tool "$TOOL_NAME" \
  --status "consulted" \
  --timestamp "$TIMESTAMP" 2>/dev/null || {
  # Fallback: direct append if manager fails
  echo "| $TIMESTAMP | $TOOL_NAME | $SOURCE | consulted |" >> "$PROVENANCE_FILE"
}

exit 0
