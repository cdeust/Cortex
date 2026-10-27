# Local Codex autonomous maintenance

The owner selected their existing Codex account on 2026-10-27. GitHub runs the
CI tests and native Codex reviews. A per-user macOS launchd dispatcher observes
PR results and open issues, then starts one supervised Codex worker in Orca.
It uses the existing local account, with no API key uploaded to GitHub.
The Mac and Orca must be running for local repair and issue intake.

The dispatcher uses a filesystem lock and one durable active Dispatch. Pending
CI, drafts, holds and branches owned by existing Orca agents are excluded.
Identical snapshots do not launch an LLM. Changed heads or terminal results
wake repair. Issue intake paginates the REST API. PR intake has an explicit
CLI limit and fails rather than silently discarding a full result set.

A worker fixes the current PR branch, or implements an issue in its own PR.
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
--runtime pointing at a durable per-user directory, --contract pointing at the
installed dispatch-contract SKILL.md, and --interval giving the
observation cadence in seconds. --enable bootstraps the per-user launchd service.
The installer copies the reviewed dispatcher and worker brief and records their
SHA256 hashes, so disposing the development worktree does not remove the service.
The service label is com.cortex.codex-autopilot. Stop with launchctl bootout
for that label in the current gui domain. No system daemon or sudo is used.

## Sources

- [Codex GitHub task delegation](https://learn.chatgpt.com/docs/third-party/github)
- [Codex noninteractive authentication](https://learn.chatgpt.com/docs/non-interactive-mode)
- Orca CLI version-matched orchestration and recovery guides, read 2026-10-27.
- macOS launchd.plist(5): ProgramArguments, StartInterval and RunAtLoad.
