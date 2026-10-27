# Native Claude PR reviews

PR807 replaces the custom workflow_run system from PR805 with Anthropic's direct PR review workflow with the trusted-base trigger documented in upstream security.md, as requested by the repository owner.

## Primary sources

The configuration follows [claude-review.yml](https://github.com/anthropics/claude-code-action/blob/8041f1d17e0e7d2f2cfe35002962e9f26237c0bb/.github/workflows/claude-review.yml). The review command and its five agent definitions are copied verbatim from the same upstream commit. Attribution and the upstream MIT licence are in [anthropic-review-license.txt](anthropic-review-license.txt).

The [README](https://github.com/anthropics/claude-code-action/blob/8041f1d17e0e7d2f2cfe35002962e9f26237c0bb/README.md) links the Solutions Guide for automatic PR reviews and progress tracking.

## Repository adaptations

- Use the standard Ubuntu runner, existing OAuth secret and SHA-pinned actions.
- Check out trusted main for the reviewer configuration; read the PR through GitHub. This fixes native security finding4392874807.
- Review opened, synchronized, reopened and ready PRs from this repository; exclude drafts.
- Retain the official review command, five agents, permission mode and model. Restore the existing allowlist for Claude, Codex and Dependabot actors.
- Install bubblewrap while retaining subprocess environment scrubbing. [Run40553919216](https://github.com/cdeust/Cortex/actions/runs/40553919216) failed before the review because bubblewrap was absent.
- Preserve owner-only mention invocation on owner-authored threads, addressing native findings4389808387 and4390480666.

## Gate migration and bootstrap

The custom Claude markers, activation declaration, embedded readers and combined-proof coordinator are retired. Codex keeps its native review evidence and PR806 trusted-resolver protection. Claude reports through its native Actions check and PR comments.

The upstream App token exchange validates the workflow against the default branch. A PR changing this workflow can soft-skip Claude until the configuration reaches main. A green skipped action does not establish review completion. Verify a real Claude comment and successful execution on a fresh head after bootstrap before declaring hosted acceptance or adding any new required check.

## Verification

Bridge retirement and trusted-checkout correction: 212 targeted CI unit tests pass; actionlint passes for Pipeline. Final workflow checks and hosted results must be recorded against the exact final head. Historical PR805 merged before its final Pipeline gate completed and is not green-CI evidence.

Security regression test_ci_native_claude fails before the checkout fix with None != main, then passes after it. The direct Claude bootstrap run40563433337 confirmed the upstream default-branch workflow validation skip; it did not execute a review.

Native findings4392934757 and4392934767: the pinned detector forces tag mode when track_progress is enabled, and tag preparation checks out the PR head. The official workflow omits that option. Cortex now omits it too, preserving the trusted checkout through agent-mode preparation. The prior explicit bot allowlist is restored. Two regression tests fail before these corrections and pass afterward. Sources: upstream src/modes/detector.ts, src/modes/agent/index.ts, src/modes/tag/index.ts and src/github/validation/actor.ts at8041f1d.

Native security finding4392971185: workflow YAML itself must come from the trusted base. Use pull_request_target, as documented in upstream docs/security.md, with ref:main and explicit-prompt agent mode. Upstream context.ts normalizes this event to pull_request for mode detection. A regression test fails with the prior PR-controlled trigger and passes with the trusted-base event. No workflow_run is used. This workflow reports through Actions and PR comments; branch protection must not require a base-commit check as if it belonged to the PR head.

## First fresh PR and OIDC correction

PR808 triggered target run40570016061 from installed main. It selected agent mode, then failed before Claude execution with401 Invalid OIDC token. Upstream issue713 documents the rejected target-event exchange. The correction uses the supported github_token input with the short-lived workflow token and removes unused id-token permission. The automatic reviewer remains Claude, but its GitHub comments publish as github-actions[bot]; owner mention mode retains App authentication. No claim of a claude[bot] automatic review is made. The new regression fails before this correction and passes after;213 targeted CI tests pass.
