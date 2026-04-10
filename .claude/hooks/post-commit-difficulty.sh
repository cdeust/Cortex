#!/usr/bin/env bash
# post-commit-difficulty.sh — After commit, check if difficulty books need updating
set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
DB_DIR="$REPO_ROOT/tasks"

[[ ! -d "$DB_DIR" ]] && exit 0

# Get files in the last commit
COMMITTED=$(git -C "$REPO_ROOT" diff-tree --no-commit-id --name-only -r HEAD 2>/dev/null)
[[ -z "$COMMITTED" ]] && exit 0

# Check if any difficulty book references the committed files' directories
for db in "$DB_DIR"/difficulty-book-*.md; do
  [[ ! -f "$db" ]] && continue
  bname="$(basename "$db" .md | sed 's/difficulty-book-//')"
  # If any committed file's path appears in the difficulty book, notify
  while IFS= read -r cf; do
    if grep -qi "$(dirname "$cf")\|$(basename "$cf" | sed 's/\..*//')" "$db" 2>/dev/null; then
      echo "NOTE: Commit touches area tracked by difficulty book '$bname'. Consider updating." >&2
      break
    fi
  done <<< "$COMMITTED"
done

exit 0
