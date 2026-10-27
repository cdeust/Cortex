# Local Codex autonomous maintenance

The owner selected their existing Codex account on 2026-10-27. GitHub runs the
CI tests and native Codex reviews. A per-user macOS launchd dispatcher observes
PR results and open issues, then starts one supervised Codex worker in Orca.
It uses the existing local account, with no API key uploaded to GitHub.
The Mac and Orca must be running for local repair and issue intake.

The dispatcher refreshes origin/main without altering the main checkout and
fast-forwards its dedicated trusted control worktree before dispatch. It reuses
that workspace and releases worker terminals instead of creating a checkout per
repair. Candidate branches are never checked out there.
The dispatcher uses a filesystem lock and one durable active Dispatch. Pending
CI, drafts, holds and branches owned by existing Orca agents are excluded.
Owner-authored/edited issue requirements are automatic. Other authors require
an owner approval comment binding the exact snapshot SHA256; later edits or
new untrusted discussion invalidate that approval. Untrusted comments cannot
wake an owner issue. Trusted follow-up requirements change the revision and
remain eligible even if they arrive while a worker finishes.
Inspection never launches, replays or releases a worker.
Identical snapshots do not launch an LLM. Changed heads or terminal results
wake repair. Issue intake paginates the REST API. PR intake has an explicit
CLI limit and fails rather than silently discarding a full result set.

A control-plane worker edits a PR or issue branch through the GitHub Git Data
API. Candidate sources remain API data: no local checkout, installation, import
or execution. All candidate tests execute on hosted GitHub runners without the
local Codex account. API publication avoids candidate Git hooks and updates
branch refs with force=false to preserve concurrent commits.
Its brief preserves other sessions, requires meaningful tests and real push
receipts, and delegates hosted waiting back to the dispatcher. The dispatcher
arms protected squash auto-merge only after the current merge gate succeeds.
GitHub enforces the required checks. There is no admin merge or fabricated review.

Orca worker-start may exit1 with ok=true and a durable outcome_unknown Dispatch.
The native readiness probe did exactly this, then completed successfully.
The dispatcher records that Dispatch and does not start a replacement. A lost
launch response is replayed with the same durable request UUID.

## Native evidence

Run run_4d56f51dd357, task task_01accd2b86d3, dispatch ctx_c938a6352cfc:
GitHub returned cdeust/Cortex, exit0; Codex login status returned
Logged in using ChatGPT, exit0. The worker reported succeeded through Orca.
Its owned terminal was released and delivery delivery_5fc5229cdbd4 acknowledged.
This proves account access and worker lifecycle, not a completed automatic fix.

## Installation

Run scripts/install_ci_autopilot.py with --repo pointing at the main checkout,
--control pointing at the dedicated registered control worktree,
--runtime pointing at a durable per-user directory, --contract pointing at the
installed dispatch-contract SKILL.md, and --interval giving the
observation cadence in seconds. Pass --coordinator-terminal with the handle of
the service's own dedicated live Orca terminal. launchd has no active sender;
Orca rejects worker-start with no_active_sender_terminal unless its sender is
explicit. The installer persists ORCA_TERMINAL_HANDLE for this service only.
Create a dedicated terminal with orca terminal create and bind it to the Run
with orchestration run-use. Preserve it as a service resource. Do not borrow
another session's terminal. --enable bootstraps the per-user launchd service.
The installed dispatcher enables one maintainer-owned status comment per item,
updating marker cortex-autopilot-status at dispatch and accepted settlement.
It reports the live remote head and links hosted checks. A comment API error is
logged and does not stop repair. Workers report through Orca rather than posting
comments from a host that prohibits them. A user-retained terminal is preserved
after accepted task completion and does not block the next work item.
The installer copies the reviewed dispatcher and worker brief and records their
SHA256 hashes, so disposing the development worktree does not remove the service.
The service label is com.cortex.codex-autopilot. Stop with launchctl bootout
for that label in the current gui domain. No system daemon or sudo is used.

## Sources

- [Codex GitHub task delegation](https://learn.chatgpt.com/docs/third-party/github)
- [Codex noninteractive authentication](https://learn.chatgpt.com/docs/non-interactive-mode)
- Orca CLI version-matched orchestration and recovery guides, read 2026-10-27.
- macOS launchd.plist(5): ProgramArguments, StartInterval and RunAtLoad.
