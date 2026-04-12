#!/usr/bin/env bash
# session-start-research.sh — Load research-specific context at session start
# Extension to session-start.sh for active research sessions.
set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
TOOLS="$REPO_ROOT/tools"
SESSION_FILE="$REPO_ROOT/research/.session.json"
NOTEBOOK="$REPO_ROOT/research/NOTEBOOK.md"

echo "=== Research Context ==="
echo ""

# Check for active research session
if [[ -f "$SESSION_FILE" ]]; then
  echo "## Active Research Session"
  "$TOOLS/research-session-manager.sh" status 2>/dev/null || echo "(session file exists but could not read status)"
  echo ""
else
  echo "No active research session. Start one with: /research-session start \"<question>\""
  echo ""
fi

# Lab notebook status
if [[ -f "$NOTEBOOK" ]]; then
  entry_count=$(grep -c '^## [0-9]' "$NOTEBOOK" 2>/dev/null || echo 0)
  last_entry=$(grep '^## [0-9]' "$NOTEBOOK" 2>/dev/null | tail -1 | sed 's/^## //' || echo "none")
  echo "## Lab Notebook"
  echo "Entries: $entry_count"
  echo "Last entry: $last_entry"
  echo ""
else
  echo "## Lab Notebook"
  echo "No notebook found. Will be created with research session."
  echo ""
fi

# Provenance files
prov_count=$(find "$REPO_ROOT" -name '.provenance-*.md' -type f 2>/dev/null | wc -l | tr -d ' ')
if [[ "$prov_count" -gt 0 ]]; then
  echo "## Provenance Files"
  echo "Active provenance sidecars: $prov_count"
  "$TOOLS/provenance-manager.sh" list 2>/dev/null | head -5
  [[ "$prov_count" -gt 5 ]] && echo "  ... and $((prov_count - 5)) more"
  echo ""
fi

# Difficulty books with research context
echo "## Research Difficulty Books"
"$TOOLS/difficulty-book-manager.sh" status 2>/dev/null || echo "(none)"
echo ""

echo "Reminder: use /research-session resume to reload full context with Cortex."
