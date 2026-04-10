#!/usr/bin/env bash
# post-edit-balance.sh — After editing data pipeline files, remind about conservation checks
set -euo pipefail

CONTEXT=""
if ! [ -t 0 ]; then
  CONTEXT="$(cat)"
fi

FILE_PATH=$(echo "$CONTEXT" | grep -oE '"file_path":\s*"[^"]*"' 2>/dev/null | head -1 | sed 's/.*"file_path":\s*"//' | sed 's/"//' || echo "")

[[ -z "$FILE_PATH" ]] && exit 0

# Check if the edited file is in a data pipeline path
if echo "$FILE_PATH" | grep -qiE '(migration|pipeline|etl|transform|ingest|export)' 2>/dev/null; then
  echo "NOTE: Edited a data pipeline file. Run /balance to verify conservation (inputs = outputs)." >&2
fi

exit 0
