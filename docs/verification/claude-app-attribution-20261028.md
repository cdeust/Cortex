# Claude App attribution correction

Explicit GITHUB_TOKEN caused comments by github-actions[bot]. Removing github_token restores the installed Claude App identity, confirmed upstream:
https://github.com/anthropics/claude-code-action/issues/396#issuecomment-3150844606

Use upstream pull_request with id-token: write. The previous pull_request_target exchange failed with a 401, matching:
https://github.com/anthropics/claude-code-action/issues/713

The same-repository, non-draft predicate remains; fork PRs are excluded. Checkout remains on main without persisting its token. The pinned action restores sensitive base configuration before launching Claude. GitHub documents that repository writers can already access repository secrets:
https://docs.github.com/en/actions/reference/security/secure-use

Previous finding (4392971185) assumed a same-repository writer lacked secret access. The GitHub repository-secret model contradicts that premise. No environment protection or repository rule changes here. Untrusted contributors must use forks. PR-head workflow edits now take effect before merge; this configuration relies on the documented repository-writer trust model rather than treating branch protection as secret isolation.

The official action skips App authentication for workflow changes until the workflow exists on main ([src/github/token.ts:129](https://github.com/anthropics/claude-code-action/blob/8041f1d17e0e7d2f2cfe35002962e9f26237c0bb/src/github/token.ts#L129)). This configuration PR cannot establish its own new App-auth review. After protected merge, an ordinary PR push must produce an actual claude[bot] comment. No extra merge gate is introduced.

The filename uses the local Europe/Paris date, October 28. UTC was still October 27 during initial publication.

The regenerated Pipeline also replaces four version-only global CLI installs with npm ci against committed SHA512 package integrity hashes. The canonical renderer ships the private CLI manifest and lockfile to each native-profile consumer. Actual isolated installation returned Claude Code 2.1.306 without invoking a model; evidence is preserved in native-cli-integrity-20261028.json.

Regression initially failed twice for explicit token and target event. Hosted attribution remains pending.

Owner model selection: both workflows use `claude-opus-5-5`, verified against the [official Opus 5.5 model identifier](https://platform.claude.com/docs/en/models/opus-5-5/overview). The five unchanged Anthropic reviewer definitions use `model: inherit`.
