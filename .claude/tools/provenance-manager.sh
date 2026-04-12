#!/usr/bin/env bash
# provenance-manager.sh — Create, update, show, and verify .provenance.md sidecar files
#
# Usage:
#   tools/provenance-manager.sh init <file>
#   tools/provenance-manager.sh add <file> <url> <status> [<note>]
#   tools/provenance-manager.sh show <file>
#   tools/provenance-manager.sh verify <file>
#   tools/provenance-manager.sh list
#
# Status values: consulted, accepted, rejected, stale
# Exit codes: 0 success, 1 error, 2 usage error

set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
ACTION="${1:-}"
TARGET="${2:-}"

[[ -z "$ACTION" ]] && { echo "usage: $0 <init|add|show|verify|list> [file] [url] [status] [note]" >&2; exit 2; }

prov_file() {
  local f="$1"
  local dir base
  dir="$(dirname "$f")"
  base="$(basename "$f")"
  echo "${dir}/.provenance-${base}.md"
}

today() { date +%Y-%m-%d; }

case "$ACTION" in
  init)
    [[ -z "$TARGET" ]] && { echo "usage: $0 init <file>" >&2; exit 2; }
    [[ ! -e "$TARGET" ]] && { echo "error: '$TARGET' does not exist" >&2; exit 1; }
    pf="$(prov_file "$TARGET")"
    [[ -f "$pf" ]] && { echo "Already exists: $pf"; exit 1; }
    base="$(basename "$TARGET")"
    cat > "$pf" <<EOF
# Provenance: $base
Last updated: $(today)

## Sources
| # | URL | Status | Date consulted | Note |
|---|-----|--------|---------------|------|
EOF
    echo "Created: $pf" ;;

  add)
    URL="${3:-}"; STATUS="${4:-}"; NOTE="${5:-}"
    [[ -z "$TARGET" || -z "$URL" || -z "$STATUS" ]] && {
      echo "usage: $0 add <file> <url> <status> [note]" >&2; exit 2
    }
    case "$STATUS" in
      consulted|accepted|rejected|stale) ;;
      *) echo "error: status must be consulted|accepted|rejected|stale" >&2; exit 2 ;;
    esac
    pf="$(prov_file "$TARGET")"
    [[ ! -f "$pf" ]] && { echo "error: no provenance file for '$TARGET' — run init first" >&2; exit 1; }
    count=$(grep -c '^| [0-9]' "$pf" 2>/dev/null || echo 0)
    next=$((count + 1))
    echo "| $next | $URL | $STATUS | $(today) | ${NOTE:-—} |" >> "$pf"
    sed -i '' "s/^Last updated:.*/Last updated: $(today)/" "$pf" 2>/dev/null || true
    echo "Added source #$next to provenance for '$(basename "$TARGET")'" ;;

  show)
    [[ -z "$TARGET" ]] && { echo "usage: $0 show <file>" >&2; exit 2; }
    pf="$(prov_file "$TARGET")"
    [[ ! -f "$pf" ]] && { echo "error: no provenance file for '$TARGET'" >&2; exit 1; }
    cat "$pf" ;;

  verify)
    [[ -z "$TARGET" ]] && { echo "usage: $0 verify <file>" >&2; exit 2; }
    pf="$(prov_file "$TARGET")"
    [[ ! -f "$pf" ]] && { echo "error: no provenance file for '$TARGET'" >&2; exit 1; }
    echo "Verifying sources for: $(basename "$TARGET")"
    echo ""
    stale_count=0
    while IFS='|' read -r _ num url status rest; do
      url="$(echo "$url" | xargs)"
      [[ -z "$url" || "$url" == "URL" || "$url" == "..." ]] && continue
      http_code=$(curl -sI -o /dev/null -w "%{http_code}" --max-time 10 "$url" 2>/dev/null || echo "000")
      if [[ "$http_code" =~ ^[23] ]]; then
        printf "  [OK]    %s (HTTP %s)\n" "$url" "$http_code"
      else
        printf "  [STALE] %s (HTTP %s)\n" "$url" "$http_code"
        stale_count=$((stale_count + 1))
      fi
    done < <(grep '^| [0-9]' "$pf")
    echo ""
    if [[ $stale_count -gt 0 ]]; then
      echo "$stale_count source(s) may be stale."
      exit 1
    else
      echo "All sources reachable."
    fi ;;

  list)
    find "$REPO_ROOT" -name '.provenance-*.md' -type f | sort | while read -r f; do
      rel="${f#$REPO_ROOT/}"
      count=$(grep -c '^| [0-9]' "$f" 2>/dev/null || echo 0)
      printf "%-60s %s source(s)\n" "$rel" "$count"
    done ;;

  *) echo "usage: $0 <init|add|show|verify|list> [file] [url] [status] [note]" >&2; exit 2 ;;
esac
