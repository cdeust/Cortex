# Native Claude PR reviews

PR 807 replaces the custom workflow_run system from PR 805 with Anthropic's direct PR review workflow with the trusted-base trigger documented in upstream security.md, as requested by the repository owner.

## Primary sources

The configuration follows [claude-review.yml](https://github.com/anthropics/claude-code-action/blob/8041f1d17e0e7d2f2cfe35002962e9f26237c0bb/.github/workflows/claude-review.yml). The review command and its five agent definitions are copied verbatim from the same upstream commit. Attribution and the upstream MIT licence are in [anthropic-review-license.txt](anthropic-review-license.txt).

The [README](https://github.com/anthropics/claude-code-action/blob/8041f1d17e0e7d2f2cfe35002962e9f26237c0bb/README.md) links the Solutions Guide for automatic PR reviews and progress tracking.

## Repository adaptations

- Use the standard Ubuntu runner, existing OAuth secret and SHA-pinned actions.
- Check out trusted main for the reviewer configuration; read the PR through GitHub. This fixes native security finding 4392874807.
- Review opened, synchronized, reopened and ready PRs from this repository; exclude drafts.
- Retain the official review command, five agents, permission mode and model. Restore the existing allowlist for Claude, Codex and Dependabot actors.
- Install bubblewrap while retaining subprocess environment scrubbing. [Run 40553919216](https://github.com/cdeust/Cortex/actions/runs/40553919216) failed before the review because bubblewrap was absent.
- Preserve owner-only mention invocation on owner-authored threads, addressing native findings 4389808387 and 4390480666.
- Owner mentions inherit tag mode's acceptEdits; only automatic reviews retain auto permission mode. This qualifies the shared permission-mode sentence in ADR-1117's Official workflow layout.

## Gate migration and bootstrap

The custom Claude markers, activation declaration, embedded readers and combined-proof coordinator are retired. Codex keeps its native review evidence and PR 806 trusted-resolver protection. Claude reports through its native Actions check and PR comments.

The upstream App token exchange validates the workflow against the default branch. A PR changing this workflow can soft-skip Claude until the configuration reaches main. A green skipped action does not establish review completion. Verify a real Claude comment and successful execution on a fresh head after bootstrap before declaring hosted acceptance or adding any new required check.

## Verification

Bridge retirement and trusted-checkout correction: 212 targeted CI unit tests pass; actionlint passes for Pipeline. Final workflow checks and hosted results must be recorded against the exact final head. Historical PR 805 merged before its final Pipeline gate completed and is not green-CI evidence.

Security regression test_ci_native_claude fails before the checkout fix with None != main, then passes after it. The direct Claude bootstrap run 40563433337 confirmed the upstream default-branch workflow validation skip; it did not execute a review.

Native findings 4392934757 and 4392934767: the pinned detector forces tag mode when track_progress is enabled, and tag preparation checks out the PR head. The official workflow omits that option. Cortex now omits it too, preserving the trusted checkout through agent-mode preparation. The prior explicit bot allowlist is restored. Two regression tests fail before these corrections and pass afterward. Sources: upstream src/modes/detector.ts, src/modes/agent/index.ts, src/modes/tag/index.ts and src/github/validation/actor.ts at 8041f1d.

Native security finding 4392971185: workflow YAML itself must come from the trusted base. Use pull_request_target, as documented in upstream docs/security.md, with ref:main and explicit-prompt agent mode. Upstream context.ts normalizes this event to pull_request for mode detection. A regression test fails with the prior PR-controlled trigger and passes with the trusted-base event. No workflow_run is used. This workflow reports through Actions and PR comments; branch protection must not require a base-commit check as if it belonged to the PR head.

## First fresh PR and OIDC correction

PR 808 triggered target run 40570016061 from installed main. It selected agent mode, then failed before Claude execution with 401 Invalid OIDC token. Upstream issue 713 documents the rejected target-event exchange. The correction uses the supported github_token input with the short-lived workflow token and removes unused id-token permission. The automatic reviewer remains Claude, but its GitHub comments publish as github-actions[bot]; owner mention mode retains App authentication. No claim of a claude[bot] automatic review is made. The new regression fails before this correction and passes after. 213 targeted CI tests pass.

## Hosted authentication correction and review

PR 808 merged as 51229df65c05f4248379d5b9fdec026cb9fd28a4 after [Pipeline 40571158980](https://github.com/cdeust/Cortex/actions/runs/40571158980) passed all required jobs. The unit job reported 10,988 passed and 26 skipped, with 90.81 percent coverage. Native Codex code and security reviews completed without findings on ad9bedd8807ee285bc5c889860ac4eb190034b61.

[Claude review 6451810776](https://github.com/cdeust/Cortex/pull/808#issuecomment-6451810776), run 40571232755, validated the authentication correction. The SDK result reported success, is_error false, 20 turns and zero permission denials. Its four test/documentation remarks are addressed in this followup: owner-mention authentication invariants, the complete automatic-review permission mapping, a stable ADR link valid in both mirrors, and readable numeric identifiers. Automatic review acceptance is checked against this fresh PR event after the authentication correction reached main.

## Official workflow files

The final layout follows the two owner-supplied upstream workflow files: claude-review.yml for automatic reviews and claude.yml for owner mentions. The automatic invocation retains /review-pr, its five copied reviewer definitions, the upstream model and auto permission mode. Cortex supplies its runner/authentication and trusted-base safeguards. Scoped gh pr view/diff/comment pre-approvals and the publication instruction follow upstream solutions.md. Earlier SDK-success runs with no published review remain incomplete evidence. All 215 targeted CI tests pass; hosted publication must be verified after this configuration installs.

## Owner mentions could not edit (2026-10-28)

Owner `@claude` fix requests on PR 772 ([run 40645284158](https://github.com/cdeust/Cortex/actions/runs/40645284158), [comment 6462511400](https://github.com/cdeust/Cortex/pull/772#issuecomment-6462511400)) and PR 820 ([run 40645479186](https://github.com/cdeust/Cortex/actions/runs/40645479186), [comment 6462540371](https://github.com/cdeust/Cortex/pull/820#issuecomment-6462540371)) pushed nothing. The SDK results reported `permission_denials_count` 6 and 3. Claude quoted the Edit refusal: "Claude requested permissions to write to … but you haven't granted it yet". On PR 820 it reported: "Every `Write`/`Edit` call … came back with a pending permission prompt that this non-interactive run can't approve."

Both runs passed the actor check (`Permission level retrieved: admin`, `Verified human actor: cdeust`). They obtained the App token and set the remote to push as claude[bot]. Authentication and job permissions were not the cause. At 8041f1d, `src/modes/tag/index.ts` lines 159-214 leave Edit, MultiEdit and Write out of `--allowedTools`. Tag mode allows workspace edits only through `--permission-mode acceptEdits`, then appends the workflow `claude_args`. `base-action/src/parse-sdk-options.ts` does not accumulate `permission-mode`, so the last value wins. PR 810 added `--permission-mode auto` to the mention job, which replaced acceptEdits. The [permission-modes documentation](https://code.claude.com/docs/en/permission-modes) says a session starts in Manual mode when auto mode is unavailable to it. A headless run has no prompt handler, so Manual mode denies edits. Auto mode itself approves edits in the working directory. The quoted refusals therefore match Manual mode, not an auto classifier block. The run logs hide the SDK init output, so the effective mode is inferred from the refusals, not printed. claude[bot] commits up to 2026-10-26 were made under the earlier explicit allowlist.

The mention job no longer sets a permission mode. Tag mode requests acceptEdits for workspace file edits. The current permission-mode documentation also describes automatic approval of common filesystem Bash commands in the working directory; that broader behavior has not been verified against the CLI resolved by this action. Its allowlist adds `git add`, `git commit`, `git rm` and the `git-push.sh` wrapper, which accepts only origin and no flags. Edit and Write are not added to `--allowedTools`; the upstream comment says that would allow writes anywhere on the runner. The review job keeps `contents: read` and its scoped `gh pr` allowlist. The mention trigger still requires an owner sender on an owner-authored thread, and the action also checks write permission. The PR description records a local before/after result for the original mention test at 835b9c2 and an actionlint result. Those historical results do not verify the later test revisions; the hosted results below are the evidence for those revisions.

The end-to-end check needs this workflow on main. An owner `@claude` fix request must then produce a claude[bot] commit on the PR branch, and the run log must show `permission_denials_count` 0.

## Mention safeguards and hosted evidence (2026-10-28)

The mention regression pins the action SHA, complete input-key set, argument tokens and normalized owner predicate. The automatic-review guard pins its five input keys and complete argument list, including auto permission mode. The exact argument assertion covers the review allowlist; job permissions are checked separately and do not cap the App token.

Native security finding [4399707392](https://github.com/cdeust/Cortex/pull/822#discussion_r4399707392) identified third-party comments reaching an owner-triggered session with edit and push authority. The mention action now sets `include_comments_by_actor: ${{ github.repository_owner }}`. The pinned [action.yml](https://github.com/anthropics/claude-code-action/blob/8041f1d17e0e7d2f2cfe35002962e9f26237c0bb/action.yml) declares this input and passes it through INCLUDE_COMMENTS_BY_ACTOR. Its [fetcher.ts](https://github.com/anthropics/claude-code-action/blob/8041f1d17e0e7d2f2cfe35002962e9f26237c0bb/src/github/data/fetcher.ts#L435-L468) filters issue and PR comments; [lines 529–545](https://github.com/anthropics/claude-code-action/blob/8041f1d17e0e7d2f2cfe35002962e9f26237c0bb/src/github/data/fetcher.ts#L529-L545) apply the same actor filter to review bodies and inline review comments before prompt and image processing. The regression requires the owner expression and includes the input in the exact key set. The automatic-review workflow is unchanged.

Owner requests for one issue or PR run one at a time with `cancel-in-progress: false` and `queue: max`. [GitHub's concurrency documentation](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency) specifies up to 100 pending jobs; excess requests are canceled and queue order follows when jobs start waiting. This does not prevent pushes from outside the workflow. No measured runtime cap is established here.

The pinned [run.ts](https://github.com/anthropics/claude-code-action/blob/8041f1d17e0e7d2f2cfe35002962e9f26237c0bb/src/entrypoints/run.ts) restores PR configuration from the base before starting Claude. [parse-sdk-options.ts](https://github.com/anthropics/claude-code-action/blob/8041f1d17e0e7d2f2cfe35002962e9f26237c0bb/base-action/src/parse-sdk-options.ts) loads user, project and local settings by default. Base settings allow `Bash(uv *)`, including arbitrary commands through `uv run sh -c`, and pytest can execute PR-head `conftest.py` and plugins. An owner-authored PR can contain collaborator or bot commits. The actor filter restricts supplied discussion context; it does not establish trust in PR code, sandbox tests or cap the App token. The origin-only push wrapper validates arguments rather than origin configuration. Protection of .git/hooks and .git/config has not been verified against the resolved CLI.

Earlier unit attempts failed before pytest because PostgreSQL 18.6.0 could not load libxml2.so.2. The temporary distribution-package workaround at b3e6c04 was removed when main ee450957 supplied the audited Linux 18.6.1 archive with bundled runtime libraries; unit and environment jobs again use that archive and pinned pgvector 0.8.7.

For head c5a011f645177b9c25cd17f0ad57c4b81ec48dda, [hosted unit job 122771813512](https://github.com/cdeust/Cortex/actions/runs/40675208580/job/122771813512) reported `11137 passed, 26 skipped, 2 warnings, 920 subtests passed` and 90.83% line coverage against the unchanged 90% minimum. Contract, regression, e2e, environment and install checks also succeeded. The [merge job](https://github.com/cdeust/Cortex/actions/runs/40675208580/job/122782246084) failed with `reason: review_unresolved` for the native security finding above. These receipts verify the preceding guards and queue assertion; fresh hosted checks and native review are required for the actor-filter correction.

ADR-1117's shared permission-mode sentence still needs correction through the canonical Cortex wiki and its regenerated mirror: automatic reviews retain auto mode, while owner mentions inherit tag-mode acceptEdits. The original end-to-end owner-mention check requires the workflow on main, a real claude[bot] push and zero permission denials.

## CI failure ladder (2026-10-28)

[Pipeline run 40670241477](https://github.com/cdeust/Cortex/actions/runs/40670241477) (2026-10-28T10:12Z, PR 826 head b60810ca merged onto main) failed in the unit job on Runner Image `ubuntu-26.04`: `postgresql-18.6.0-x86_64-unknown-linux-gnu/bin/postgres: error while loading shared libraries: libxml2.so.2: cannot open shared object file`, then `initdb: error: program "postgres" is needed by initdb but was not found`. `git diff origin/main...HEAD -- scripts .github` was empty for that PR, so the PR did not cause it. A Claude bot answered "I can't make any of these. My GitHub App can't edit .github/workflows… See the FAQ" and stopped, proposing a `runs-on: ubuntu-24.04` pin, an apt install of libxml2, or a PostgreSQL build change. The pin contradicts the owner decision of 2026-10-28 (no runner pin; Linux uses the bundled 18.6.1).

origin/main already carried the fix: ee450957 `fix(pg): run theseus 18.6.1 on Linux, which bundles libxml2 (Ubuntu 26.04 runners) (#823)`. Once the PR branch merged main (head 7a4424d8), [Pipeline run 40743111494](https://github.com/cdeust/Cortex/actions/runs/40743111494) succeeded at 18:13Z. The missed exit was within the bot's authority: merge origin/main into the PR branch and push.

The upstream [FAQ entry](https://github.com/anthropics/claude-code-action/blob/8041f1d17e0e7d2f2cfe35002962e9f26237c0bb/docs/faq.md) "Why won't Claude update workflow files when I ask it to?" (lines 60-62 at the pinned commit) states that the GitHub App has no workflow write access. Step 6 of the ladder in `docs/agent-guidance.md` answers it with a posted diff that an actor with workflow write access applies; the check stays red with that named cause meanwhile, and no hold label is applied (owner rule 2026-10-29: no PR waits for the owner). `gh run view <run> --log-failed` can print only provisioning lines, so step 1 requires the per-job log and the `Runner Image` line.

The mention bot's tools were read from the pinned action source: tag mode adds `git add`, `git commit`, `git rm`, the `git-push.sh` wrapper and the three `mcp__github_ci__*` tools (`src/modes/tag/index.ts:162-185`), and installs the `github_ci` server only for a PR with `actions: read` (`src/mcp/install-mcp-server.ts:175-206`). Mention run 40758911185 on #830 was denied `git fetch origin main`, a `python3` heredoc and `Edit` on a tracked doc, so each ladder step names the tool it needs and treats a denial as a hard stop.

Codex finding PRRT_kwDORqU88s6xSqOR on #830 showed that the first draft classified failures as infrastructure from a diff filtered to `scripts .github ci.json pyproject.toml uv.lock`, while `scripts/ci_environment.py` imports and runs `mcp_server.doctor`, `backend_marker` and `managed_pg`. Step 2 now reads the unfiltered diff and the modules the failing step executes.

Codex security finding PRRT_kwDORqU88s6xdRLJ (P1) on #830 showed that step 3 told an agent to run the PR's own `ci.json` command, which a local agent would execute on the maintainer host with the `uv *` and `pytest` approvals of `.claude/settings.json`. Step 3 now leaves PR-head commands to hosted CI or a disposable sandbox without maintainer tokens, with the command taken from `origin/main:ci.json`, and an every-step rule states the same boundary as `scripts/ci_autopilot.py`.

Acceptance still open: no hosted bot run has exercised the ladder yet. It is accepted by a bot comment that shows step 4 or step 5 taken, or a hard stop quoting its denial.
