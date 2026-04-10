#!/usr/bin/env bash
# pre-push-review.sh — Check for zetetic violations before push
set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
TOOLS="$REPO_ROOT/tools"

TRACKING="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref '@{upstream}' 2>/dev/null || echo '')"
[[ -z "$TRACKING" ]] && exit 0

CHANGED_FILES=()
while IFS= read -r f; do
  [[ -f "$REPO_ROOT/$f" ]] && CHANGED_FILES+=("$REPO_ROOT/$f")
done < <(git -C "$REPO_ROOT" diff "$TRACKING"...HEAD --name-only 2>/dev/null)

[[ ${#CHANGED_FILES[@]} -eq 0 ]] && exit 0

"$TOOLS/zetetic-checker.sh" --files "${CHANGED_FILES[@]}" 2>&1 || {
  echo "BLOCKED: Zetetic violations in files being pushed." >&2
  exit 2
}

"$TOOLS/difficulty-book-manager.sh" check 2>&1 || {
  echo "WARNING: Pushing with unaddressed difficulty-book entries." >&2
}

exit 0
