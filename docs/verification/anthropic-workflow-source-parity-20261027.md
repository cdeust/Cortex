# Anthropic workflow source parity

Source commit: [8041f1d17e0e7d2f2cfe35002962e9f26237c0bb](https://github.com/anthropics/claude-code-action/tree/8041f1d17e0e7d2f2cfe35002962e9f26237c0bb).

The five reviewer files below match the pinned upstream Git blobs byte for byte (checked again on 13 November 2026 with `git hash-object`). The command file matched its blob when it was installed and has changed twice since; the changes are listed under the table. The MIT notice of the six files is preserved in [anthropic-review-license.txt](anthropic-review-license.txt).

| Copied file | Verified Git blob |
|---|---|
| `.claude/commands/review-pr.md` | `a83d8e35c29e90d3390eeceabf62fc69fb24608f` |
| `.claude/agents/code-quality-reviewer.md` | `ff2577a6f06790e29ec1c9bb9169e56963933bcb` |
| `.claude/agents/documentation-accuracy-reviewer.md` | `c694d718be141baafe614ef0c0729d381b2a61a3` |
| `.claude/agents/performance-reviewer.md` | `6a8e9a7382d09ef2fb39819ccce16d5098f81578` |
| `.claude/agents/security-code-reviewer.md` | `c9e64e7014d2b0444cabd2a0952399c3495ebeab` |
| `.claude/agents/test-coverage-reviewer.md` | `30c5f50fbf4a2ddd8dcdce0cfe2042eba4721a4e` |

`.claude/commands/review-pr.md` no longer matches its blob. On 13 November 2026, `git diff a83d8e35c29e90d3390eeceabf62fc69fb24608f HEAD:.claude/commands/review-pr.md` shows six lines added and one removed:

- added by ADR-1135 (pull request 1000): the instruction that has two reviewers try to refute the pull request;
- removed by ADR-1139 (pull request 1026): the `allowed-tools` line of the frontmatter.

## Workflow installation

The layout follows upstream [claude-review.yml](https://github.com/anthropics/claude-code-action/blob/8041f1d17e0e7d2f2cfe35002962e9f26237c0bb/.github/workflows/claude-review.yml) and [claude.yml](https://github.com/anthropics/claude-code-action/blob/8041f1d17e0e7d2f2cfe35002962e9f26237c0bb/.github/workflows/claude.yml). Cortex supplies its Ubuntu runner and OAuth account, pinned actions, trusted-base execution, supported GitHub token, isolation and owner authorization. Scoped gh permissions and publication instructions come from upstream solutions.md.

[PR 810](https://github.com/cdeust/Cortex/pull/810) installed these files as main commit 49302a5cc16d668b6949af08bd7d3485b1e176bc after [Pipeline 40580160923](https://github.com/cdeust/Cortex/actions/runs/40580160923) passed all required jobs. The unit job reported 10,990 passed and 26 skipped, with 90.81 percent coverage. The installed tree matches reviewed head 8dd40e775c8931aa970e7b04965af3eb98285a04: `5b6c0f00b79ff4c29b918b14e269a22dd0d8f902`.

This documentation PR supplies a fresh event to verify automatic Claude publication after installation. Earlier SDK-success runs without a published review are not acceptance evidence.
