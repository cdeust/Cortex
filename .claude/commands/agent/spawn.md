# Spawn Agent in Worktree

Spawn an agent as a standalone Claude Code session in an isolated git worktree.

## Instructions

1. Parse arguments: the first word is the agent name, the rest is the task description.
   Example: `/agent-spawn engineer Fix the auth bug in login.py`

2. Validate the agent exists by checking `agents/<name>.md` or `agents/genius/<name>.md`.

3. Run: `scripts/spawn-agent.sh <agent-name> "<task>"`

4. Report the worktree path and branch name to the user.

5. If no task is provided, spawn in interactive REPL mode (no `-p` flag).

$ARGUMENTS
