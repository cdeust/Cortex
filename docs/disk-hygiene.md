# Session disk hygiene

Claude Code and Codex invoke one shared Python standard-library bundle in
`plugins/hypermnesia-mcp-codex/scripts/disk_hygiene.py`. It packages the existing
local hook, with transcript retention enabled by default. Python 3, Git,
authenticated GitHub CLI and `lsof` must be available. Missing safety checks
protect paths rather than authorizing removal.

## Register disposable work

The SessionStart context supplies the installed command and session identifier.
Use `--host codex --session "$CODEX_THREAD_ID"` for Codex, or `--host claude`
with the UUID supplied by Claude's SessionStart. Set `CLEANUP` below to the
installed `scripts/disk_hygiene.py` path. Run from the main checkout when disposing.

```sh
python3 "$CLEANUP" --host codex --session "$CODEX_THREAD_ID" register-worktree --repo /absolute/main --path /absolute/main/.Codex/worktrees/task
python3 "$CLEANUP" --host codex --session "$CODEX_THREAD_ID" link-pr --path /absolute/main/.Codex/worktrees/task --pr https://github.com/owner/repo/pull/123
# Save required review evidence outside the disposable tree before this step.
python3 "$CLEANUP" --host codex --session "$CODEX_THREAD_ID" evidence-preserved --path /absolute/main/.Codex/worktrees/task --evidence /absolute/main/tasks/review.md
python3 "$CLEANUP" --host codex --session "$CODEX_THREAD_ID" dispose --dry-run
python3 "$CLEANUP" --host codex --session "$CODEX_THREAD_ID" dispose
```

Use `create-temp --parent /absolute/parent` from the repository to create and
register disposable build/download/capture directories. Existing directories are
never claimed as scratch. Nested Git repositories are protected; use registered
linked worktrees for review checkouts. Stop processes and remove owned ignored
build outputs before disposal. `status` reports the current owner's paths.

The shared ledger defaults to
`$CORTEX_CLAUDE_DIR/methodology/worktree-cleanup.json` (`~/.claude` by default).
`--state` selects another ledger; both hosts must share it for ownership checks.
Existing standalone-hook registrations stay in their original ledger. Finish
those tasks with their original command rather than registering them twice.
Then remove the old standalone cleanup entries from the host's hook configuration.
An independently installed older hook can still delete transcripts: the plugin's
retention setting does not disable other commands. Keep unrelated hook entries.

## Lifecycle and protection

After recognized pushes and PR creation, the hook attempts current-owner cleanup.
Stop retries and reports protected paths. Explicitly dispose immediately after
push when a tool payload is not recognized. SessionEnd records pending cleanup;
new sessions retry ended owners registered in the same main repository. A resumed
session cancels its ended marker. No periodic background sweep runs.

A worktree must be registered, clean, unlocked and unused by a process. Its linked
PR's live head must contain every local commit, and preserved evidence must still
match. Untracked and ignored files, unpushed commits, replaced paths, main
checkouts and other active owners remain protected. Git removes worktrees and
local branches without force. Failed branch deletion remains pending for retry.
Remote PRs and remote branches remain available for review.

GitHub CLI queries the registered PR and Git fetches its head. These are network
requests to the repository host. Process checks are point-in-time observations;
other sessions must respect ownership. Abrupt host termination without a lifecycle
event cannot mark a session ended.

## Transcripts and resume

`CORTEX_CLEANUP_TRANSCRIPTS=keep` is the default. Claude transcripts, nested subagent
transcripts and file history remain; Codex rollouts remain. Runtime scratch can be
removed while native resume history is retained.

Set `CORTEX_CLEANUP_TRANSCRIPTS=delete` in the host environment to opt into deletion.
Other values fail before cleanup. Claude waits for its Cortex lifecycle reader;
Codex requires an exact completion receipt at least as recent as the rollout and
an inactive writer lock. Deferred files are retried on later hook events. Cortex's
receipt is not a transcript backup: deletion can remove native resume/rewind history.
Shared databases, caches, images and attachments are not swept.

See [ADR-1092](adr/ADR-1092-package-the-existing-shared-disk-hygiene-hook.md)
for source provenance and the distinction between native trials and fixture tests.
