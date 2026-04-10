# Commands Index

16 commands across 6 categories. Commands are operational shortcuts that invoke tools, skills, and agents.

## Quick Reference

| Command | Category | Description |
|---------|----------|-------------|
| `/agent-list` | agent | List agents by type, shape, or keyword |
| `/agent-spawn` | agent | Spawn an agent in an isolated worktree |
| `/agent-status` | agent | Check active agent worktrees |
| `/skill-run` | skill | Execute a registered skill by name |
| `/zcommit` | git | Commit with zetetic pre-checks and conventional message |
| `/zpr` | git | Create PR with review, zetetic checklist, and description |
| `/zclean` | git | Clean up merged agent worktree branches |
| `/session-save` | session | Save session context to Cortex + local cache |
| `/session-recall` | session | Load context from previous session |
| `/pre-commit` | quality | Run zetetic pre-commit checks manually |
| `/pre-push` | quality | Run full review on changes since last push |
| `/qverify` | zetetic | Quick claim verification (fast /verify-claim) |
| `/qestimate` | zetetic | Quick Fermi bracket (fast /estimate) |
| `/qreview` | zetetic | Quick review of staged changes (critical only) |
| `/qdifficulty` | zetetic | Check difficulty book status |
| `/qintegrity` | zetetic | Quick integrity audit (Feynman-style) |

## Installation

Copy commands to your Claude Code commands directory:

```bash
# Global (all projects)
cp -r zetetic-team-subagents/commands/* ~/.claude/commands/

# Per-project
mkdir -p .claude/commands
cp -r zetetic-team-subagents/commands/* .claude/commands/
```

Then type `/` in Claude Code to see available commands.
