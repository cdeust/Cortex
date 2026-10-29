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
to be null. Missing metadata on relevant owner content, a different editor or an
inconsistent owner ID cannot authorize a worker. Unrelated deleted-author
discussion does not block an otherwise authenticated owner request. An altered
owner-authored comment blocks that issue,
including when its approval marker has been removed. Other authors still need
an authenticated owner approval of the exact current snapshot digest. Existing
approvals using the earlier snapshot shape must be renewed for the new digest.

Title ownership is checked separately because body-edit metadata does not prove
who last changed the title. The same query reads the latest filtered
RenamedTitleEvent. An owner-authored issue requires either a complete empty
rename history or a latest event whose immutable actor identity is the owner
and whose currentTitle matches the returned issue title. Incomplete history,
foreign rename actors and title provenance changing between pages are rejected.
External issues retain explicit owner approval of the exact snapshot title.

Comment pagination stays in GraphQL so body and last-editor metadata belong to
the same returned row. Incomplete/duplicate comments, repeated cursors, GraphQL
errors, or an issue revision changing between pages fail closed. This is current
GitHub edit attribution, not a cryptographic signature or a guarantee that all
paginated rows form an atomic snapshot.

The existing local polling loop also recognizes a completed review-only wait.
Only PRs whose named test/environment/install prerequisites are green and whose
other checks have no unrelated failures qualify for an authenticated evidence
read. Drafts, holds, forks, active owners and pending checks remain excluded.
A per-PR isolated Python subprocess reads the current native proof and classifies
repair or wait for the exact repository, PR and expected head. GitHub's workflow
is the sole issuer of native gate reruns; the local helper never calls resume or
POST. It reuses the existing coordinator's read-only run/job/proof policy. This
avoids a race between the local dispatcher and GitHub's per-PR concurrency group.

Missing, running, failed or invalid review proof remains a wait; genuine current
unresolved findings can enter the existing serialized repair path. When proof is
clean, the helper reads the trusted latest run and effective attempt jobs. A
ready native gate waits for the GitHub workflow. A completed review job's
non-readiness failure, or a completed merge job's non-readiness failure after
a successful review, can request infrastructure repair. Both require green
test prerequisites and no unrelated failures. It reuses the native policy's
readiness predicate and rechecks the run, head and proof before doing so. A
waiting PR does not block other actionable work. Unchanged repair snapshots cannot
start another worker. Completed review waits are revisited because resolving a
thread does not necessarily change the PR head or check fingerprint.

Known evidence errors carry fixed api, protocol, environment or eligibility
categories in JSON. The dispatcher logs the category and PR, preserving useful
diagnostics without copying raw child stderr or exception text. Unknown program
errors still surface as failures rather than authorizing a repair.

The installer copies and hashes the native evidence/event modules alongside the
dispatcher. It does not copy candidate sources. Installation and launchd enabling
remain separate operations. This service configuration still handles one
repository and one durable active dispatch; it does not create parallel workers
for the other repositories. Keep the existing control worktree and user-retained
terminals when reconciling an accepted completion.

The installer passes its polling interval both as launchd StartInterval and as
the dispatcher's --interval. Values must be positive integers. The optional CLI
flag defaults to the existing 60-second service interval, preserving earlier
--inspect commands. Each helper runs in its own POSIX session. Its nominal
communication budget is one configured interval; on failure or timeout only
that owned group is terminated, its pipes are closed and its leader wait is
bounded separately by one interval. This is not a guarantee of 60 seconds total:
exceptional cleanup has its own bounded budget. Other user sessions are not
signalled, and the installed service is not altered by source validation.

Primary field verification: a read-only GitHub GraphQL query on 2026-10-28
returned cdeust/Cortex issue683's owner and author as User
MDQ6VXNlcjMxNjc3Njc=, with editor=null and lastEditedAt=null.
[GitHub IssueComment fields](https://docs.github.com/en/graphql/reference/objects#issuecomment)
and [Issue fields](https://docs.github.com/en/graphql/reference/objects#issue)
describe the attribution consumed here.

A read-only probe of [VS Code issue334398](https://github.com/microsoft/vscode/issues/334398)
found a recorded title rename with editor=null and lastEditedAt=null. This proves
that body attribution alone does not cover the title; the observed rename actor
was the original author, not a reproduced foreign-writer attack.
[RenamedTitleEvent fields](https://docs.github.com/en/graphql/reference/objects#renamedtitleevent)
provide the separate attribution. On official claude-code-action issue1445,
last:1 selected the current title from two rename events while first:1 did not.

## Convergence without the owner (2026-10-29)

Owner rule, 2026-10-29: "Le CI doit être autonome, ma revue ne devrait jamais
être nécessaire." On that morning seven PRs were stalled with every test green
or with the automation's own hold. Their API states are the fixtures of
`tests_py/scripts/fixtures/ci_autopilot_converge_prs.json` (REST pulls, files,
issue comments and GraphQL reviewThreads, captured 07:22Z):

- #830 at `e5117943`: the review job printed `"reason": "review_pending"` with
  `code_review.commit_sha` `7d10a05e` (the first commit, pushed 23 s earlier).
  Codex reviewed only the first commit; nothing requested a review of the head,
  so the job stayed `merge pending review` and the required `merge` context
  never ran.
- #828: `code_review` `running` on the head since 2026-10-28T18:20Z, every check
  finished. #772 and #765: `code_review` all null on the head.
- #833: `security_review` completed on the head with null verdict flags.
- #826 and #829: `autopilot:hold` applied by the hourly routine with "décision
  humaine requise"; #831 held the same way for a security finding on
  `.github/workflows/claude.yml`, a path the PR no longer changed.

Second owner rule, same day: `hold` and `autopilot:hold` mean "reviews
incomplete". `scripts/ci_autopilot_converge_plan.py` therefore lifts a review
hold, and reruns a merge job that failed on "Verify live PR eligibility", only
when Codex (both kinds complete on the head, no open finding) and Claude (a
`claude-review-verdict:v1` marker for the head with `merge: true`, no open
inline finding) both conclude to merge. A missing reviewer is launched again:
a stale Codex review is requested once per head and kind (marker
`ci-autopilot-converge:v1 request`), a failed Claude review job is rerun once.
A second unusable verdict on the same head is named: `review_stale_after_request`,
or `codex_security_verdict_missing: <summary link>` for a null verdict, the state
measured twice on cdeust/ci-autonome#1 (07:51:07Z and 07:57:01Z, fixture
`tests_py/scripts/fixtures/codex_null_verdict_ci_autonome_pr1.json`). "Running"
counts as stale only after every check of that head finished, an ordering
rather than a duration. A non-security finding on a path absent from
`pulls/{n}/files` is answered with that proof and resolved; a security finding
on such a path gets a fresh `@codex security review` instead, because only the
owner or a new Codex verdict clears one (`_trusted_resolver`). The planner never
merges and never touches `do-not-merge`, a "do not merge" title, a draft or a
fork.

The Claude review does not emit the verdict marker yet: `.claude/commands/review-pr.md`
is rendered from the zetetic-team-subagents template and only asks for
comments. Until the template emits it, a completed Claude review is the red
cause `claude_verdict_unreadable` and no review hold is lifted; the planner
does not add holds, so the Pipeline gate keeps merging on Codex alone as before.

Live receipts: `@codex review` comments posted from the owner's account on
#828, #772 and #765 at 2026-10-29T07:31:55Z-07:31:59Z were followed by native
reviews and gate merges at 07:34:13Z-07:34:17Z. On #830 a push of `fe32c7d0` started both reviews on the
new head (summary updated 07:31:25Z); the code review completed clean and the
security review completed with null flags, the #833 state, which a
`@codex security review` comment then targeted.

Requests posted by the workflow token come from github-actions[bot]. Every
review trigger observed in this repository came from the owner's account, so a
bot request is not proven to start a review. The optional
`CODEX_REQUEST_TOKEN` secret (a token of a Codex-linked user, issues write)
makes the workflow post as that user; without it a spent request is reported
as `review_stale_after_request ... CODEX_REQUEST_TOKEN unset` on the PR status.
The routine prompt of record is `docs/ci-autopilot-routine.md`; the routine's
configuration on claude.ai is outside this repository.
