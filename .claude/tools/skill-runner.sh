#!/usr/bin/env bash
# skill-runner.sh — Resolve and display a skill's procedure for Claude to follow
#
# Usage:
#   tools/skill-runner.sh <skill-name>
#
# Searches skills/ recursively for <name>.md, prints its procedure and zetetic gates.
# Exit codes: 0 found, 1 not found

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKILLS_DIR="$REPO_ROOT/skills"

NAME="${1:-}"
[[ -z "$NAME" ]] && { echo "usage: $0 <skill-name>" >&2; exit 1; }

# Search for the skill file
SKILL_FILE=$(find "$SKILLS_DIR" -name "${NAME}.md" -not -name "_*" 2>/dev/null | head -1)

if [[ -z "$SKILL_FILE" ]]; then
  echo "Skill not found: $NAME" >&2
  echo "" >&2
  echo "Available skills:" >&2
  find "$SKILLS_DIR" -name "*.md" -not -name "_*" | xargs -I{} basename {} .md | sort | sed 's/^/  /' >&2
  exit 1
fi

echo "=== Skill: $NAME ==="
echo "File: $SKILL_FILE"
echo ""

# Extract and display key sections
awk '
/^---$/ { fm++; next }
fm < 2 { next }
fm >= 2 { print }
' "$SKILL_FILE"
