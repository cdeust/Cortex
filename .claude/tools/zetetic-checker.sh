#!/usr/bin/env bash
# zetetic-checker.sh — Scan files for zetetic standard violations
#
# Usage:
#   tools/zetetic-checker.sh --staged              # check git staged files
#   tools/zetetic-checker.sh --files <f1> <f2> ...  # check specific files
#
# Checks: magic numbers without source annotation, unsourced claims in comments,
#         TODO/FIXME without difficulty-book reference
#
# Exit codes: 0 clean, 1 violations found, 2 usage error

set -euo pipefail
VIOLATIONS=0

FILES=()
if [[ "${1:-}" == "--staged" ]]; then
  while IFS= read -r f; do
    [[ -f "$f" ]] && FILES+=("$f")
  done < <(git diff --cached --name-only --diff-filter=ACMR 2>/dev/null)
elif [[ "${1:-}" == "--files" ]]; then
  shift; FILES=("$@")
else
  echo "usage: $0 [--staged|--files <file1> ...]" >&2; exit 2
fi

[[ ${#FILES[@]} -eq 0 ]] && { echo "No files to check."; exit 0; }

for file in "${FILES[@]}"; do
  # Skip binary files and agent/skill definition files
  file -b --mime-type "$file" 2>/dev/null | grep -q "text/" || continue
  [[ "$file" == *.md ]] && continue

  line_num=0
  while IFS= read -r line; do
    line_num=$((line_num + 1))

    # Check: magic numbers (2+ digits, not 0 or 1) without source annotation
    if echo "$line" | grep -qE '[^a-zA-Z_0-9][0-9]{2,}(\.[0-9]+)?' 2>/dev/null; then
      if ! echo "$line" | grep -qi "source:\|#.*from\|//.*from\|port\|status\|http\|errno\|exit" 2>/dev/null; then
        echo "MAGIC_NUMBER  $file:$line_num"
        VIOLATIONS=$((VIOLATIONS + 1))
      fi
    fi

    # Check: unsourced absolute claims in comments
    if echo "$line" | grep -qiE '(#|//|/\*|\*).*\b(always|never|obviously|clearly|everyone knows)\b' 2>/dev/null; then
      if ! echo "$line" | grep -qi "source:\|ref:\|see:\|citation:" 2>/dev/null; then
        echo "UNSOURCED     $file:$line_num"
        VIOLATIONS=$((VIOLATIONS + 1))
      fi
    fi

    # Check: TODO/FIXME without difficulty-book reference
    if echo "$line" | grep -qi "TODO\|FIXME\|HACK\|XXX" 2>/dev/null; then
      if ! echo "$line" | grep -qi "difficulty.book\|DB#\|db-entry\|tracked" 2>/dev/null; then
        echo "TODO_NO_DB    $file:$line_num"
        VIOLATIONS=$((VIOLATIONS + 1))
      fi
    fi
  done < "$file"
done

echo ""
if [[ $VIOLATIONS -gt 0 ]]; then
  echo "FAILED: $VIOLATIONS zetetic violation(s). Annotate with '# source: <ref>' before committing."
  exit 1
else
  echo "PASSED: no zetetic violations."
  exit 0
fi
