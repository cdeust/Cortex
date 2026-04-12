#!/usr/bin/env bash
# genius-invoker.sh — Lightweight genius agent invocation, listing, routing, and composition
#
# Usage:
#   tools/genius-invoker.sh invoke <agent-name> "<problem>"
#   tools/genius-invoker.sh list [--shapes] [--search <term>]
#   tools/genius-invoker.sh route "<problem-description>"
#   tools/genius-invoker.sh compose <agent1> <agent2> ... -- "<problem>"
#
# Exit codes: 0 success, 1 error, 2 usage error

set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
GENIUS_DIR="$REPO_ROOT/agents/genius"
INDEX="$GENIUS_DIR/INDEX.md"
ACTION="${1:-}"

[[ -z "$ACTION" ]] && { echo "usage: $0 <invoke|list|route|compose> [args]" >&2; exit 2; }

case "$ACTION" in
  invoke)
    NAME="${2:-}"; PROBLEM="${3:-}"
    [[ -z "$NAME" || -z "$PROBLEM" ]] && { echo "usage: $0 invoke <agent-name> \"<problem>\"" >&2; exit 2; }
    AGENT_FILE="$GENIUS_DIR/${NAME}.md"
    [[ ! -f "$AGENT_FILE" ]] && { echo "error: agent '$NAME' not found at $AGENT_FILE" >&2; exit 1; }

    # Extract frontmatter fields
    description=$(sed -n '/^---$/,/^---$/{ /^description:/s/^description: *//p; }' "$AGENT_FILE")
    when_to_use=$(sed -n '/^---$/,/^---$/{ /^when_to_use:/s/^when_to_use: *//p; }' "$AGENT_FILE")
    shapes=$(sed -n '/^---$/,/^---$/{ /^shapes:/s/^shapes: *//p; }' "$AGENT_FILE")

    echo "=== Genius Agent: $NAME ==="
    echo "Description: $description"
    echo "Shapes: $shapes"
    echo "When to use: $when_to_use"
    echo ""
    echo "=== Problem ==="
    echo "$PROBLEM"
    echo ""
    echo "=== Agent System Prompt ==="
    cat "$AGENT_FILE"
    ;;

  list)
    shift
    SHOW_SHAPES=false; SEARCH=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --shapes) SHOW_SHAPES=true; shift ;;
        --search) SEARCH="$2"; shift 2 ;;
        *) shift ;;
      esac
    done
    for f in "$GENIUS_DIR"/*.md; do
      [[ ! -f "$f" ]] && continue
      bname="$(basename "$f" .md)"
      [[ "$bname" == "INDEX" ]] && continue
      desc=$(sed -n '/^---$/,/^---$/{ /^description:/s/^description: *//p; }' "$f")
      shapes=$(sed -n '/^---$/,/^---$/{ /^shapes:/s/^shapes: *//p; }' "$f")
      # Apply search filter
      if [[ -n "$SEARCH" ]]; then
        if ! echo "$bname $desc $shapes" | grep -qi "$SEARCH"; then
          continue
        fi
      fi
      if [[ "$SHOW_SHAPES" == true ]]; then
        printf "%-20s %s\n  shapes: %s\n" "$bname" "$desc" "$shapes"
      else
        printf "%-20s %s\n" "$bname" "$desc"
      fi
    done ;;

  route)
    shift
    PROBLEM="${1:-}"
    [[ -z "$PROBLEM" ]] && { echo "usage: $0 route \"<problem-description>\"" >&2; exit 2; }
    [[ ! -f "$INDEX" ]] && { echo "error: INDEX.md not found at $INDEX" >&2; exit 1; }
    echo "Routing problem: $PROBLEM"
    echo ""
    # Extract keywords from problem (split on spaces, lowercase)
    matches_found=false
    for word in $PROBLEM; do
      word_lower="$(echo "$word" | tr '[:upper:]' '[:lower:]')"
      [[ ${#word_lower} -lt 4 ]] && continue
      result=$(grep -i "$word_lower" "$INDEX" 2>/dev/null | grep -E '^\| \*\*' | head -5)
      if [[ -n "$result" ]]; then
        matches_found=true
        echo "Keyword '$word_lower':"
        echo "$result"
        echo ""
      fi
    done
    if [[ "$matches_found" == false ]]; then
      echo "No matching shapes found."
      echo "Try broader keywords or check agents/genius/INDEX.md directly."
      exit 1
    fi ;;

  compose)
    shift
    AGENTS=(); PROBLEM=""
    while [[ $# -gt 0 ]]; do
      if [[ "$1" == "--" ]]; then
        shift
        PROBLEM="${1:-}"
        break
      fi
      AGENTS+=("$1")
      shift
    done
    [[ ${#AGENTS[@]} -lt 2 ]] && { echo "usage: $0 compose <agent1> <agent2> ... -- \"<problem>\"" >&2; exit 2; }
    [[ -z "$PROBLEM" ]] && { echo "usage: $0 compose <agent1> <agent2> ... -- \"<problem>\"" >&2; exit 2; }
    # Validate all agents exist
    for agent in "${AGENTS[@]}"; do
      af="$GENIUS_DIR/${agent}.md"
      [[ ! -f "$af" ]] && { echo "error: agent '$agent' not found at $af" >&2; exit 1; }
    done
    echo "=== Multi-Agent Composition ==="
    echo "Agents: ${AGENTS[*]}"
    echo "Problem: $PROBLEM"
    echo ""
    step=1
    for agent in "${AGENTS[@]}"; do
      af="$GENIUS_DIR/${agent}.md"
      desc=$(sed -n '/^---$/,/^---$/{ /^description:/s/^description: *//p; }' "$af")
      echo "=== Step $step: $agent ==="
      echo "Description: $desc"
      echo ""
      echo "--- Agent Content ---"
      cat "$af"
      echo ""
      echo "--- End $agent ---"
      echo ""
      step=$((step + 1))
    done
    echo "=== Apply agents in sequence to: ==="
    echo "$PROBLEM" ;;

  *) echo "usage: $0 <invoke|list|route|compose> [args]" >&2; exit 2 ;;
esac
