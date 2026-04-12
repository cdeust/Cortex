#!/usr/bin/env bash
# pre-push-provenance.sh — Verify provenance sidecars exist for research files before push
# Configurable strictness: PROVENANCE_STRICT=block (default) or PROVENANCE_STRICT=warn
set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
STRICTNESS="${PROVENANCE_STRICT:-warn}"

# Get the remote branch to diff against
REMOTE="${1:-origin}"
BRANCH="$(git -C "$REPO_ROOT" branch --show-current 2>/dev/null || echo 'main')"
REMOTE_REF="${REMOTE}/${BRANCH}"

# Get changed files compared to remote
CHANGED_FILES=$(git -C "$REPO_ROOT" diff --name-only "$REMOTE_REF"...HEAD 2>/dev/null || \
                git -C "$REPO_ROOT" diff --name-only HEAD~5...HEAD 2>/dev/null || echo "")

[[ -z "$CHANGED_FILES" ]] && exit 0

MISSING=0

prov_file() {
  local f="$1"
  local dir base
  dir="$(dirname "$f")"
  base="$(basename "$f")"
  echo "${dir}/.provenance-${base}.md"
}

needs_provenance() {
  local f="$1"
  # Check if file contains algorithm markers, constants, or research code
  [[ ! -f "$REPO_ROOT/$f" ]] && return 1
  case "$f" in
    *.md|*.json|*.yaml|*.yml|*.toml|*.lock|*.txt|*.csv|*.sh) return 1 ;;
  esac
  # Check for provenance-worthy content
  grep -qiE '(algorithm|threshold|alpha|beta|gamma|epsilon|coefficient|weight.*=|factor.*=|# source:|implementation of)' "$REPO_ROOT/$f" 2>/dev/null
}

while IFS= read -r file; do
  [[ -z "$file" ]] && continue
  if needs_provenance "$file"; then
    pf="$(prov_file "$REPO_ROOT/$file")"
    if [[ ! -f "$pf" ]]; then
      echo "MISSING PROVENANCE: $file"
      echo "  Expected: $(prov_file "$file")"
      echo "  Create with: tools/provenance-manager.sh init \"$file\""
      MISSING=$((MISSING + 1))
    fi
  fi
done <<< "$CHANGED_FILES"

if [[ $MISSING -gt 0 ]]; then
  echo ""
  echo "$MISSING file(s) with research content lack provenance sidecars."
  if [[ "$STRICTNESS" == "block" ]]; then
    echo "BLOCKED: Set PROVENANCE_STRICT=warn to override."
    exit 1
  else
    echo "WARNING: Consider adding provenance before merging."
  fi
fi

exit 0
