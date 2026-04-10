# Hooks — Automated Zetetic Enforcement

Hooks automatically enforce the zetetic standard at key workflow points. They are the differentiator: the epistemic standard is not voluntary — it is built into the development lifecycle.

## Installation

Copy the hooks configuration to your project's `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "command": "/path/to/zetetic-team-subagents/hooks/pre-commit-zetetic.sh",
        "timeout": 30000
      },
      {
        "matcher": "Bash",
        "command": "/path/to/zetetic-team-subagents/hooks/pre-push-review.sh",
        "timeout": 60000
      },
      {
        "matcher": "Edit|Write",
        "command": "/path/to/zetetic-team-subagents/hooks/pre-edit-layer-check.sh",
        "timeout": 10000
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Bash",
        "command": "/path/to/zetetic-team-subagents/hooks/post-commit-difficulty.sh",
        "timeout": 15000
      },
      {
        "matcher": "Edit|Write",
        "command": "/path/to/zetetic-team-subagents/hooks/post-edit-balance.sh",
        "timeout": 10000
      }
    ],
    "Notification": [
      {
        "command": "/path/to/zetetic-team-subagents/hooks/notification-handler.sh",
        "timeout": 10000
      }
    ],
    "Stop": [
      {
        "command": "/path/to/zetetic-team-subagents/hooks/session-end.sh",
        "timeout": 15000
      }
    ]
  }
}
```

Replace `/path/to/zetetic-team-subagents` with the actual path to your clone.

## Hook Reference

| Hook | Event | What it does | Blocks? |
|------|-------|-------------|---------|
| **pre-commit-zetetic** | Before `git commit` | Scans staged files for invented constants, unsourced claims, TODOs without difficulty-book refs | Yes — violations block commit |
| **post-commit-difficulty** | After `git commit` | Checks if committed files relate to an active difficulty book; reminds to update | No — advisory |
| **pre-push-review** | Before `git push` | Runs zetetic checker on all changes since last push | Yes — violations block push |
| **session-start** | Session start | Loads repo state, difficulty books, agent worktrees, cached session | No — context injection |
| **session-end** | Session end (`Stop`) | Saves session summary to local cache and Cortex | No — background save |
| **pre-edit-layer-check** | Before `Edit`/`Write` | Warns if editing a core/ file (risk of layer violation) | No — advisory |
| **post-edit-balance** | After `Edit`/`Write` | Reminds to run /balance after editing pipeline files | No — advisory |
| **notification-handler** | Subagent completes | Logs result, checks for unmerged agent worktrees | No — informational |

## Session Start via CLAUDE.md

Since Claude Code has no `SessionStart` hook event, add this to your project's `CLAUDE.md`:

```markdown
## Session Start Protocol

At the beginning of every session:
1. Run `./hooks/session-start.sh` to load context
2. Call Cortex `query_methodology` for cognitive profile
3. Call Cortex `recall` with the project topic
4. Check difficulty books with `./tools/difficulty-book-manager.sh status`
```

## What the hooks enforce

The hooks are not style linters — they are epistemic enforcement:

1. **No invented constants.** Every hardcoded number must cite its source.
2. **No unsourced claims.** Comments containing "always," "never," "obviously" must cite evidence.
3. **No orphaned TODOs.** Every TODO must reference a difficulty-book entry or be explicitly tracked.
4. **Layer integrity.** Core files are flagged when edited to remind about dependency direction.
5. **Data conservation.** Pipeline file edits trigger a reminder to verify mass-balance.
6. **Difficulty-book hygiene.** Commits and pushes check that hardest cases are addressed.
7. **Session continuity.** Context is saved and loaded across sessions.
