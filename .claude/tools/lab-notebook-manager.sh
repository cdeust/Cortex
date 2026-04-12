#!/usr/bin/env bash
# lab-notebook-manager.sh — Manage a structured research lab notebook
#
# Usage:
#   tools/lab-notebook-manager.sh add "<entry>" [--tag <tag>] [--commit <sha>]
#   tools/lab-notebook-manager.sh show [--last <n>]
#   tools/lab-notebook-manager.sh search "<term>"
#   tools/lab-notebook-manager.sh timeline
#
# Notebook stored at research/NOTEBOOK.md
# Exit codes: 0 success, 1 error, 2 usage error

set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
NOTEBOOK="$REPO_ROOT/research/NOTEBOOK.md"
ACTION="${1:-}"

[[ -z "$ACTION" ]] && { echo "usage: $0 <add|show|search|timeline> [args]" >&2; exit 2; }

ensure_notebook() {
  if [[ ! -f "$NOTEBOOK" ]]; then
    mkdir -p "$(dirname "$NOTEBOOK")"
    echo "# Lab Notebook" > "$NOTEBOOK"
    echo "" >> "$NOTEBOOK"
  fi
}

case "$ACTION" in
  add)
    shift
    ENTRY="" ; TAG="" ; COMMIT=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --tag) TAG="$2"; shift 2 ;;
        --commit) COMMIT="$2"; shift 2 ;;
        *) ENTRY="$1"; shift ;;
      esac
    done
    [[ -z "$ENTRY" ]] && { echo "usage: $0 add \"<entry>\" [--tag <tag>] [--commit <sha>]" >&2; exit 2; }
    ensure_notebook
    timestamp="$(date -u +%Y-%m-%dT%H:%M:%S)"
    tag_str=""
    [[ -n "$TAG" ]] && tag_str=" [$TAG]"
    {
      echo ""
      echo "## ${timestamp}${tag_str}"
      echo "$ENTRY"
      [[ -n "$COMMIT" ]] && echo "Commit: $COMMIT"
      echo ""
      echo "---"
    } >> "$NOTEBOOK"
    echo "Entry added: ${timestamp}${tag_str}" ;;

  show)
    [[ ! -f "$NOTEBOOK" ]] && { echo "No notebook found at $NOTEBOOK" >&2; exit 1; }
    LAST=""
    shift
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --last) LAST="$2"; shift 2 ;;
        *) shift ;;
      esac
    done
    if [[ -n "$LAST" ]]; then
      # Extract the last N entries (each separated by ---)
      awk '/^## [0-9]{4}-[0-9]{2}-[0-9]{2}/' "$NOTEBOOK" | tail -"$LAST" | while read -r header; do
        ts="$(echo "$header" | sed 's/^## //')"
        # Print from this header to the next ---
        sed -n "/^## ${ts}/,/^---$/p" "$NOTEBOOK"
        echo ""
      done
    else
      cat "$NOTEBOOK"
    fi ;;

  search)
    shift
    TERM="${1:-}"
    [[ -z "$TERM" ]] && { echo "usage: $0 search \"<term>\"" >&2; exit 2; }
    [[ ! -f "$NOTEBOOK" ]] && { echo "No notebook found at $NOTEBOOK" >&2; exit 1; }
    # Find entries containing the term
    grep -B2 -A5 -i "$TERM" "$NOTEBOOK" || echo "No entries matching: $TERM" ;;

  timeline)
    [[ ! -f "$NOTEBOOK" ]] && { echo "No notebook found at $NOTEBOOK" >&2; exit 1; }
    echo "Lab Notebook Timeline"
    echo "====================="
    echo ""
    grep '^## [0-9]' "$NOTEBOOK" | while read -r line; do
      ts="$(echo "$line" | sed 's/^## //')"
      printf "  %s\n" "$ts"
    done
    total=$(grep -c '^## [0-9]' "$NOTEBOOK" 2>/dev/null || echo 0)
    echo ""
    echo "Total entries: $total" ;;

  *) echo "usage: $0 <add|show|search|timeline> [args]" >&2; exit 2 ;;
esac
