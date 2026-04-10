#!/usr/bin/env bash
# pre-edit-layer-check.sh — Warn if an edit might violate layer boundaries
# Reads the file path from stdin (Claude Code hook context) and checks
# if the target file is in core/ and the edit might add infrastructure imports.
# This is advisory (warn, not block) since the full edit isn't known at pre-edit time.
set -euo pipefail

# Read hook context from stdin if available
CONTEXT=""
if ! [ -t 0 ]; then
  CONTEXT="$(cat)"
fi

# Extract file path from context (Claude Code passes tool args as JSON)
FILE_PATH=$(echo "$CONTEXT" | grep -oE '"file_path":\s*"[^"]*"' 2>/dev/null | head -1 | sed 's/.*"file_path":\s*"//' | sed 's/"//' || echo "")

[[ -z "$FILE_PATH" ]] && exit 0

# Check if editing a core/ file
if echo "$FILE_PATH" | grep -qE '(^|/)core/' 2>/dev/null; then
  echo "NOTE: Editing a core/ file. Ensure no infrastructure/I/O imports are added." >&2
  echo "Core may only import from shared/. Dependencies point inward." >&2
fi

exit 0
