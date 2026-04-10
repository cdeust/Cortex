#!/usr/bin/env bash
# difficulty-book-manager.sh — Create, update, list, and check difficulty books
#
# Usage:
#   tools/difficulty-book-manager.sh create <name>
#   tools/difficulty-book-manager.sh add <name> "<entry>"
#   tools/difficulty-book-manager.sh status [name]
#   tools/difficulty-book-manager.sh check [name]     # exits non-zero if hardest case open
#   tools/difficulty-book-manager.sh list
#
# Books stored in tasks/difficulty-book-<name>.md
# Exit codes: 0 success/pass, 1 fail/blocked, 2 usage error

set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
DB_DIR="$REPO_ROOT/tasks"
PREFIX="difficulty-book-"
ACTION="${1:-}"; NAME="${2:-}"; ENTRY="${3:-}"

[[ -z "$ACTION" ]] && { echo "usage: $0 <create|add|status|check|list> [name] [entry]" >&2; exit 2; }

db_file() { echo "$DB_DIR/${PREFIX}${1}.md"; }

case "$ACTION" in
  create)
    [[ -z "$NAME" ]] && { echo "usage: $0 create <name>" >&2; exit 2; }
    f="$(db_file "$NAME")"
    [[ -f "$f" ]] && { echo "Already exists: $f"; exit 1; }
    mkdir -p "$DB_DIR"
    cat > "$f" <<EOF
# Difficulty Book: $NAME
Last updated: $(date +%Y-%m-%d)

## Status: 0 open / 0 addressed / 0 deferred

| # | Contradiction | Damage if true | Status | Resolution |
|---|---------------|----------------|--------|------------|
EOF
    echo "Created: $f" ;;

  add)
    [[ -z "$NAME" || -z "$ENTRY" ]] && { echo "usage: $0 add <name> \"<entry>\"" >&2; exit 2; }
    f="$(db_file "$NAME")"
    [[ ! -f "$f" ]] && { echo "error: no difficulty book '$NAME'" >&2; exit 1; }
    count=$(grep -c '^| [0-9]' "$f" 2>/dev/null || echo 0)
    next=$((count + 1))
    echo "| $next | $ENTRY | TBD | open | — |" >> "$f"
    sed -i '' "s/^Last updated:.*/Last updated: $(date +%Y-%m-%d)/" "$f" 2>/dev/null || true
    echo "Added entry #$next to '$NAME'" ;;

  status)
    if [[ -n "$NAME" ]]; then
      f="$(db_file "$NAME")"
      [[ ! -f "$f" ]] && { echo "error: no difficulty book '$NAME'" >&2; exit 1; }
      head -5 "$f"
    else
      for f in "$DB_DIR"/${PREFIX}*.md; do
        [[ ! -f "$f" ]] && continue
        bname="$(basename "$f" .md)"; bname="${bname#$PREFIX}"
        printf "%-30s %s\n" "$bname" "$(grep '^## Status:' "$f" 2>/dev/null | sed 's/^## Status: //')"
      done
    fi ;;

  check)
    exit_code=0
    for f in "$DB_DIR"/${PREFIX}*.md; do
      [[ ! -f "$f" ]] && continue
      [[ -n "$NAME" && "$f" != "$(db_file "$NAME")" ]] && continue
      first="$(grep '^| 1 |' "$f" 2>/dev/null || true)"
      if echo "$first" | grep -q '| open |' 2>/dev/null; then
        bname="$(basename "$f" .md)"; bname="${bname#$PREFIX}"
        echo "BLOCKED: $bname — hardest case (#1) is open"
        exit_code=1
      fi
    done
    [[ $exit_code -eq 0 ]] && echo "All difficulty books: hardest cases addressed."
    exit $exit_code ;;

  list)
    for f in "$DB_DIR"/${PREFIX}*.md; do
      [[ ! -f "$f" ]] && continue
      basename "$f" .md | sed "s/^${PREFIX}//"
    done ;;

  *) echo "usage: $0 <create|add|status|check|list> [name] [entry]" >&2; exit 2 ;;
esac
