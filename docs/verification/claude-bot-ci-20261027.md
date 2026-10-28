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

The mention job no longer sets a permission mode. The action's acceptEdits mode allows edits only in the workspace. Its allowlist adds `git add`, `git commit`, `git rm` and the `git-push.sh` wrapper, which accepts only origin and no flags. Edit and Write are not added to `--allowedTools`; the upstream comment says that would allow writes anywhere on the runner. The review job keeps `contents: read` and its scoped `gh pr` allowlist. The mention trigger still requires an owner sender on an owner-authored thread, and the action also checks write permission. The PR description records a local before/after result for the original mention test at 835b9c2 and an actionlint result. Those historical results do not verify the later test revisions; the hosted results below are the evidence for those revisions.

The end-to-end check needs this workflow on main. An owner `@claude` fix request must then produce a claude[bot] commit on the PR branch, and the run log must show `permission_denials_count` 0.

## Follow-up review evidence (2026-10-28)

The mention regression now pins the exact action SHA, input keys, argument tokens and complete normalized owner predicate. This catches equals-form flags, additional permission/settings flags, wildcard tool grants and a prompt input that would change mode. The separate automatic-review guard pins the complete argument list, including auto permission mode, so a later duplicate mode or added settings flag fails the assertion. Existing exact permission and tool-set tests cover the review allowlist.

The security review's PR-head settings premise was checked against [run.ts at the pinned action SHA](https://github.com/anthropics/claude-code-action/blob/8041f1d17e0e7d2f2cfe35002962e9f26237c0bb/src/entrypoints/run.ts): after tag preparation, PR runs restore configuration from the base before starting Claude. [parse-sdk-options.ts](https://github.com/anthropics/claude-code-action/blob/8041f1d17e0e7d2f2cfe35002962e9f26237c0bb/base-action/src/parse-sdk-options.ts) loads user, project and local settings by default. Trusted base settings include `Bash(uv *)`, which permits arbitrary commands such as `uv run sh -c` and can bypass the intent of a direct `Bash(curl *)` denial. The pytest allowance also executes PR-head `conftest.py` and plugins. An owner-authored PR can contain collaborator or bot commits, so the owner-on-owner trigger restricts who starts the run, not who wrote all code that it executes. Combined with workspace edits, these permissions permit arbitrary command execution on PR-head code on the runner with an App token capable of pushing. acceptEdits limits file-edit approval; it does not sandbox test execution or cap the App token. This capability is restricted to the existing owner-on-owner trigger. The workflow does not add blanket tool grants.

[Hosted unit job 122685766069](https://github.com/cdeust/Cortex/actions/runs/40649407965/job/122685766069) at 835b9c200dcc698dc1ff5bfc5a108ed9582b2464 failed before pytest: bundled PostgreSQL 18.6.0 could not load libxml2.so.2. That run provides no test result for these guards. The follow-up changes have only static text verification until hosted CI executes them; no local candidate code was executed. The next hosted unit attempt, [job 122737182615](https://github.com/cdeust/Cortex/actions/runs/40664989006/job/122737182615) at 4ce19f90d159236259630c53653d8e86a2042b3c, failed with the same missing `libxml2.so.2` before pytest on Ubuntu 26.04.1. Neither hosted attempt establishes a passing test result. The complete-arguments guard and wording correction prepared after that head require fresh hosted checks.
