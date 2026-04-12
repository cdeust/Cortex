#!/usr/bin/env bash
# pre-tool-claim-gate.sh — Check code content for zetetic violations before Write/Edit
# Catches hardcoded constants, magic numbers, and unsourced algorithms at edit time.
# Input: $1 = file path being written/edited, $2 = temp file with new content (or stdin)
set -euo pipefail

FILE="${1:-}"
CONTENT_FILE="${2:-}"
VIOLATIONS=0

[[ -z "$FILE" ]] && exit 0

# Only check code files, skip markdown/config
case "$FILE" in
  *.md|*.json|*.yaml|*.yml|*.toml|*.lock|*.txt|*.csv) exit 0 ;;
esac

# Read content from temp file or stdin
if [[ -n "$CONTENT_FILE" && -f "$CONTENT_FILE" ]]; then
  CONTENT="$(cat "$CONTENT_FILE")"
elif [[ ! -t 0 ]]; then
  CONTENT="$(cat)"
else
  exit 0
fi

[[ -z "$CONTENT" ]] && exit 0

line_num=0
while IFS= read -r line; do
  line_num=$((line_num + 1))

  # Magic numbers: 2+ digit numeric literals not annotated with source
  if echo "$line" | grep -qE '[^a-zA-Z_0-9][0-9]{2,}(\.[0-9]+)?' 2>/dev/null; then
    if ! echo "$line" | grep -qi "source:\|#.*from\|//.*from\|port\|status\|http\|errno\|exit\|range\|len\|size\|index\|offset\|version" 2>/dev/null; then
      echo "WARNING: Possible magic number at $FILE:$line_num — add '# source: <ref>' annotation"
      VIOLATIONS=$((VIOLATIONS + 1))
    fi
  fi

  # Threshold / constant assignment without source
  if echo "$line" | grep -qiE '(threshold|alpha|beta|gamma|epsilon|lambda|weight|factor|coefficient|decay)\s*[=:]\s*[0-9]' 2>/dev/null; then
    if ! echo "$line" | grep -qi "source:\|ref:\|from\|paper\|doi\|arxiv" 2>/dev/null; then
      echo "WARNING: Constant without citation at $FILE:$line_num — zetetic standard requires source"
      VIOLATIONS=$((VIOLATIONS + 1))
    fi
  fi

  # Algorithm implementation marker without citation
  if echo "$line" | grep -qiE '(algorithm|implementation of|based on|adapted from|following)\s' 2>/dev/null; then
    if ! echo "$line" | grep -qi "source:\|ref:\|doi\|arxiv\|http\|see:\|citation:" 2>/dev/null; then
      echo "WARNING: Algorithm reference without citation at $FILE:$line_num"
      VIOLATIONS=$((VIOLATIONS + 1))
    fi
  fi
done <<< "$CONTENT"

if [[ $VIOLATIONS -gt 0 ]]; then
  echo ""
  echo "Claim gate: $VIOLATIONS potential zetetic violation(s). Consider adding source annotations."
fi

exit 0
