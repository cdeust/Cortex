# Native pull-request reviews

Ready pull requests from branches in this repository start the official Claude review workflow when opened, reopened, marked ready or updated with a push. The workflow runs the checked-in review command with its five specialist reviewers and publishes progress and the final response on the PR.

Codex code and security reviews run through the connected repository account. The Codex completion workflow resumes a waiting merge check when the native reviews finish for the current commit. Contributors address findings and push their corrections to the same branch.

The project test categories remain defined in `ci.json`. Successful bot execution does not replace the unit, regression, end-to-end, environment and installation checks. Follow `CLAUDE.md` and the repository's contribution guidance when preparing a change.

The automatic Claude workflow skips drafts and forks. Partnership contributors using repository branches receive the automatic review path. Claude runs through Anthropic's action; its automatic comments use the workflow token and are published by GitHub Actions.

Sources: [.github/workflows/claude-review.yml](../.github/workflows/claude-review.yml), [.github/workflows/Codex.yml](../.github/workflows/Codex.yml), [ci.json](../ci.json).
