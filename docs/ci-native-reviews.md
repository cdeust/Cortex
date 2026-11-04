# Native pull-request reviews

Ready pull requests from branches in this repository start the official Claude review workflow when opened, reopened, marked ready or updated with a push. The workflow runs the checked-in review command with its five specialist reviewers and publishes progress and the final response on the PR.

Codex code and security reviews run through the ChatGPT Codex GitHub App, configured in ChatGPT's code-review settings for this repository. `Codex.yml` handles completion events and resumes a waiting merge check when the native reviews finish for the current commit. Contributors address findings and push their corrections to the same branch.

The project test categories remain defined in `ci.json`: `unit`, `regression`, `e2e`, `environment` and `install`. Successful bot execution does not replace these checks. Follow `CLAUDE.md` and the repository's contribution guidance when preparing a change.

Each PR receives at most three automatic Claude reviews (ADR-1119). The `budget` job counts the reviews already published for the PR and skips the fourth without a comment; the accepted part merges and the rest goes to a refinement PR. The review prompt defines a Blocker, limits Notes to three one-line items and ends with `Verdict: approve` or `Verdict: block`. The label `claude-rereview` allows exactly one more review. The automatic Claude workflow skips drafts and forks. Non-draft PRs from branches in this repository receive automatic reviews. Claude runs through Anthropic's action with its native App authentication and Opus 5.5; its comments are attributed to `claude[bot]`. The action skips changes to its own workflow until those changes reach the default branch, so installing this configuration requires a subsequent PR to verify the complete automatic path.

Sources: [.github/workflows/claude-review.yml](../.github/workflows/claude-review.yml), [scripts/ci_review_budget.py](../scripts/ci_review_budget.py), [.github/workflows/Codex.yml](../.github/workflows/Codex.yml), [ci.json](../ci.json).
