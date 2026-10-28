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
wake repair. Issue intake paginates GraphQL issue and comment connections. PR intake has an explicit
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
The installed dispatcher enables one maintainer-owned status comment per PR,
updating marker cortex-autopilot-status at dispatch and accepted settlement.
It reports the live remote head and links hosted checks. A comment API error is
logged and does not stop repair. Workers report through Orca rather than posting
comments from a host that prohibits them. A user-retained terminal is preserved
after accepted task completion and does not block the next work item.
Issue status stays in Orca so automated owner comments cannot create new approved
issue revisions and trigger another model call.
The installer copies the reviewed dispatcher and worker brief and records their
SHA256 hashes, so disposing the development worktree does not remove the service.
The service label is com.cortex.codex-autopilot. Stop with launchctl bootout
for that label in the current gui domain. No system daemon or sudo is used.

## Sources

- [Codex GitHub task delegation](https://learn.chatgpt.com/docs/third-party/github)
- [Codex noninteractive authentication](https://learn.chatgpt.com/docs/non-interactive-mode)
- Orca CLI version-matched orchestration and recovery guides, read 2026-10-27.
- macOS launchd.plist(5): ProgramArguments, StartInterval and RunAtLoad.

## Authenticated revisions and review reconciliation (2026-10-28)

Issue intake obtains the repository owner's immutable GitHub User ID and each
issue/comment's author, editor and lastEditedAt in GraphQL responses. Automatic
owner requirements require the same owner identity at authorship and, when
edited, at the last edit. Pristine content requires both editor and lastEditedAt
to be null. Missing metadata on relevant owner content, a different editor or an inconsistent
owner ID cannot authorize a worker. Unrelated deleted-author discussion does not
block an otherwise authenticated owner request. An altered owner-authored comment blocks that issue,
including when its approval marker has been removed. Other authors still need
an authenticated owner approval of the exact current snapshot digest. Existing
approvals using the earlier snapshot shape must be renewed for the new digest.

Comment pagination stays in GraphQL so body and last-editor metadata belong to
the same returned row. Incomplete/duplicate comments, repeated cursors, GraphQL
errors, or an issue revision changing between pages fail closed. This is current
GitHub edit attribution, not a cryptographic signature or a guarantee that all
paginated rows form an atomic snapshot.

The existing local polling loop also recognizes a completed review-only wait.
Only PRs whose named test/environment/install prerequisites are green and whose
other checks have no unrelated failures qualify for an authenticated evidence
read. Drafts, holds, forks, active owners and pending checks remain excluded.
A per-PR isolated Python subprocess reads the current native proof and invokes
ci_codex_review_event.resume with the exact repository, PR and expected head.
The existing coordinator rechecks the live head, workflow run, attempts, jobs and
proof before requesting a selected job rerun. This local step does not synthesize
a GitHub event, request another native review or invoke a model.

Missing, running, failed or invalid review proof remains a wait; genuine current
unresolved findings can enter the existing serialized repair path. When proof is
clean but the native resumption policy returns no action, the helper reads the
trusted latest run and effective attempt jobs. Only a completed review job's
non-readiness failure, with all test prerequisites green and no unrelated
failures, can request infrastructure repair. It reuses the native policy's
readiness predicate and rechecks the run, head and proof before doing so. A waiting PR
does not block other actionable work. Unchanged repair snapshots still cannot
start another worker. Completed review waits are revisited because resolving a
thread does not necessarily change the PR head or check fingerprint.

The installer copies and hashes the native evidence/event modules alongside the
dispatcher. It does not copy candidate sources. Installation and launchd enabling
remain separate operations. This service configuration still handles one
repository and one durable active dispatch; it does not create parallel workers
for the other repositories. Keep the existing control worktree and user-retained
terminals when reconciling an accepted completion.

Primary field verification: a read-only GitHub GraphQL query on 2026-10-28
returned cdeust/Cortex issue683's owner and author as User
MDQ6VXNlcjMxNjc3Njc=, with editor=null and lastEditedAt=null.
[GitHub IssueComment fields](https://docs.github.com/en/graphql/reference/objects#issuecomment)
and [Issue fields](https://docs.github.com/en/graphql/reference/objects#issue)
describe the attribution consumed here.
