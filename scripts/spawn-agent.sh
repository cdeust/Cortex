#!/usr/bin/env bash
# Spawn a zetetic agent as a standalone Claude Code session in an isolated git worktree.
#
# Usage:
#   scripts/spawn-agent.sh <agent-name> [task-description]
#
# Examples:
#   scripts/spawn-agent.sh engineer "Fix the auth bug in login.py"
#   scripts/spawn-agent.sh architect                         # interactive REPL
#
# What it does:
#   1. Resolves the agent file (.claude/agents/<name>.md) and strips YAML frontmatter.
#   2. Creates a git worktree at ../<repo>-<agent>-<timestamp> on a new branch.
#   3. Launches `claude` there with:
#        --append-system-prompt  <agent body>   (installs the agent persona)
#        --permission-mode bypassPermissions    (no interactive approval prompts)
#      If a task is passed, runs headless with -p; otherwise drops into the REPL.
#
# Requirements: `claude` CLI on PATH, `git` >= 2.5.

set -euo pipefail

AGENT="${1:-}"
shift || true
TASK="${*:-}"

if [[ -z "$AGENT" ]]; then
  echo "usage: $0 <agent-name> [task]" >&2
  exit 2
fi

REPO_ROOT="$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel)"

# Resolve agent file: check .claude/agents/<name>.md first, then .claude/agents/genius/<name>.md
AGENT_FILE="$REPO_ROOT/.claude/agents/$AGENT.md"
if [[ ! -f "$AGENT_FILE" ]]; then
  AGENT_FILE="$REPO_ROOT/.claude/agents/genius/$AGENT.md"
fi

if [[ ! -f "$AGENT_FILE" ]]; then
  echo "error: agent not found: $AGENT" >&2
  echo "" >&2
  echo "team agents:" >&2
  ls "$REPO_ROOT/.claude/agents"/*.md 2>/dev/null | xargs -I{} basename {} .md | sed 's/^/  /' >&2
  echo "" >&2
  echo "genius agents:" >&2
  ls "$REPO_ROOT/.claude/agents/genius"/*.md 2>/dev/null | grep -v INDEX | xargs -I{} basename {} .md | sed 's/^/  genius\//' >&2
  exit 1
fi

# Strip the YAML frontmatter (everything between the first two `---` lines).
AGENT_BODY="$(awk 'BEGIN{f=0} /^---$/{f++; next} f>=2{print}' "$AGENT_FILE")"

# Target project = current working directory's git root (the repo you want the
# agent to work ON), not this subagents repo.
TARGET_REPO="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
TARGET_NAME="$(basename "$TARGET_REPO")"
STAMP="$(date +%Y%m%d-%H%M%S)"
WORKTREE="$TARGET_REPO/../${TARGET_NAME}-${AGENT}-${STAMP}"
BRANCH="agent/${AGENT}/${STAMP}"

echo "→ creating worktree: $WORKTREE (branch $BRANCH)"
git -C "$TARGET_REPO" worktree add -b "$BRANCH" "$WORKTREE"

cd "$WORKTREE"

echo "→ launching claude as '$AGENT' (permissions bypassed)"

# Set MEMORY_AGENT_ID so memory-tool.sh audit log and ACL use the correct
# identity. AGENT is the slug (basename of the agent file without .md).
# Identity MUST come from the spawn site, not the subagent: the subagent
# cannot forge its own id.
export MEMORY_AGENT_ID="$AGENT"

if [[ -n "$TASK" ]]; then
  exec claude \
    --permission-mode bypassPermissions \
    --append-system-prompt "$AGENT_BODY" \
    -p "$TASK"
else
  exec claude \
    --permission-mode bypassPermissions \
    --append-system-prompt "$AGENT_BODY"
fi
