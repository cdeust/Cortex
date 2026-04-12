#!/usr/bin/env bash
# research-session-manager.sh — Manage research session state
#
# Usage:
#   tools/research-session-manager.sh start "<question>"
#   tools/research-session-manager.sh resume
#   tools/research-session-manager.sh status
#   tools/research-session-manager.sh close
#   tools/research-session-manager.sh hypothesis add "<hypothesis>"
#   tools/research-session-manager.sh hypothesis list
#
# Session stored at research/.session.json, notebook at research/NOTEBOOK.md
# Exit codes: 0 success, 1 error, 2 usage error

set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
RESEARCH_DIR="$REPO_ROOT/research"
SESSION_FILE="$RESEARCH_DIR/.session.json"
NOTEBOOK="$RESEARCH_DIR/NOTEBOOK.md"
ARCHIVE_DIR="$RESEARCH_DIR/archive"
ACTION="${1:-}"

[[ -z "$ACTION" ]] && { echo "usage: $0 <start|resume|status|close|hypothesis> [args]" >&2; exit 2; }

now_iso() { date -u +%Y-%m-%dT%H:%M:%SZ; }
now_epoch() { date +%s; }

json_escape() {
  python3 -c 'import sys,json; print(json.dumps(sys.stdin.read().strip()))' 2>/dev/null <<< "$1" || echo "\"$1\""
}

read_field() {
  local field="$1"
  python3 -c "
import json, sys
try:
    d = json.load(open('$SESSION_FILE'))
    print(d.get('$field', ''))
except: pass
" 2>/dev/null
}

count_hypotheses() {
  python3 -c "
import json
try:
    d = json.load(open('$SESSION_FILE'))
    print(len(d.get('hypotheses', [])))
except: print(0)
" 2>/dev/null
}

case "$ACTION" in
  start)
    QUESTION="${2:-}"
    [[ -z "$QUESTION" ]] && { echo "usage: $0 start \"<research question>\"" >&2; exit 2; }
    [[ -f "$SESSION_FILE" ]] && { echo "error: session already active. Close it first or use 'resume'." >&2; exit 1; }

    mkdir -p "$RESEARCH_DIR"

    # Initialize session file
    cat > "$SESSION_FILE" <<EOF
{
  "question": $(json_escape "$QUESTION"),
  "started": "$(now_iso)",
  "started_epoch": $(now_epoch),
  "hypotheses": [],
  "status": "active"
}
EOF

    # Initialize notebook if missing
    if [[ ! -f "$NOTEBOOK" ]]; then
      cat > "$NOTEBOOK" <<EOF
# Lab Notebook

Research question: $QUESTION
Started: $(now_iso)

---
EOF
    fi

    echo "Research session started."
    echo "Question: $QUESTION"
    echo "Notebook: $NOTEBOOK"
    echo "Add hypotheses with: $0 hypothesis add \"<hypothesis>\"" ;;

  resume)
    [[ ! -f "$SESSION_FILE" ]] && { echo "error: no active session. Start one with: $0 start \"<question>\"" >&2; exit 1; }

    question="$(read_field question)"
    hyp_count="$(count_hypotheses)"
    entry_count=0
    [[ -f "$NOTEBOOK" ]] && entry_count=$(grep -c '^## [0-9]' "$NOTEBOOK" 2>/dev/null || echo 0)

    echo "=== Research Session Resumed ==="
    echo "Question: $question"
    echo "Hypotheses: $hyp_count"
    echo "Notebook entries: $entry_count"
    echo ""
    echo "Use Cortex recall with this question for prior context." ;;

  status)
    [[ ! -f "$SESSION_FILE" ]] && { echo "No active research session." >&2; exit 1; }

    question="$(read_field question)"
    started="$(read_field started)"
    status="$(read_field status)"
    hyp_count="$(count_hypotheses)"
    entry_count=0
    [[ -f "$NOTEBOOK" ]] && entry_count=$(grep -c '^## [0-9]' "$NOTEBOOK" 2>/dev/null || echo 0)

    # Compute duration
    started_epoch="$(read_field started_epoch)"
    duration=""
    if [[ -n "$started_epoch" && "$started_epoch" != "0" ]]; then
      elapsed=$(( $(now_epoch) - started_epoch ))
      hours=$((elapsed / 3600))
      mins=$(( (elapsed % 3600) / 60 ))
      duration="${hours}h ${mins}m"
    fi

    echo "=== Research Session ==="
    echo "Status: $status"
    echo "Question: $question"
    echo "Started: $started"
    [[ -n "$duration" ]] && echo "Duration: $duration"
    echo "Hypotheses: $hyp_count"
    echo "Notebook entries: $entry_count" ;;

  close)
    [[ ! -f "$SESSION_FILE" ]] && { echo "error: no active session to close." >&2; exit 1; }

    question="$(read_field question)"
    hyp_count="$(count_hypotheses)"
    entry_count=0
    [[ -f "$NOTEBOOK" ]] && entry_count=$(grep -c '^## [0-9]' "$NOTEBOOK" 2>/dev/null || echo 0)

    echo "=== Closing Research Session ==="
    echo "Question: $question"
    echo "Hypotheses tracked: $hyp_count"
    echo "Notebook entries: $entry_count"
    echo ""

    # List hypotheses with status
    python3 -c "
import json
try:
    d = json.load(open('$SESSION_FILE'))
    for i, h in enumerate(d.get('hypotheses', []), 1):
        status = h.get('status', 'open')
        text = h.get('text', '')
        print(f'  {i}. [{status}] {text}')
except: pass
" 2>/dev/null

    # Archive
    mkdir -p "$ARCHIVE_DIR"
    archive_name="session-$(date +%Y%m%d-%H%M%S).json"
    cp "$SESSION_FILE" "$ARCHIVE_DIR/$archive_name"
    rm "$SESSION_FILE"

    echo ""
    echo "Session archived to: $ARCHIVE_DIR/$archive_name"
    echo "Notebook preserved at: $NOTEBOOK"
    echo "Remember to store findings in Cortex." ;;

  hypothesis)
    SUB="${2:-}"
    case "$SUB" in
      add)
        HYPO="${3:-}"
        [[ -z "$HYPO" ]] && { echo "usage: $0 hypothesis add \"<hypothesis>\"" >&2; exit 2; }
        [[ ! -f "$SESSION_FILE" ]] && { echo "error: no active session." >&2; exit 1; }

        python3 -c "
import json
d = json.load(open('$SESSION_FILE'))
d.setdefault('hypotheses', []).append({
    'text': '''$HYPO''',
    'status': 'open',
    'added': '$(now_iso)'
})
json.dump(d, open('$SESSION_FILE', 'w'), indent=2)
print(f'Hypothesis added (#{len(d[\"hypotheses\"])}): $HYPO')
" 2>/dev/null ;;

      list)
        [[ ! -f "$SESSION_FILE" ]] && { echo "error: no active session." >&2; exit 1; }
        python3 -c "
import json
d = json.load(open('$SESSION_FILE'))
hyps = d.get('hypotheses', [])
if not hyps:
    print('No hypotheses tracked yet.')
else:
    for i, h in enumerate(hyps, 1):
        status = h.get('status', 'open')
        text = h.get('text', '')
        added = h.get('added', '')
        print(f'  {i}. [{status}] {text}  ({added})')
" 2>/dev/null ;;

      *) echo "usage: $0 hypothesis <add|list> [text]" >&2; exit 2 ;;
    esac ;;

  *) echo "usage: $0 <start|resume|status|close|hypothesis> [args]" >&2; exit 2 ;;
esac
