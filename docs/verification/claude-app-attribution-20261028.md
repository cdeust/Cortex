# Claude App attribution correction

Explicit GITHUB_TOKEN caused comments by github-actions[bot]. Removing github_token restores the installed Claude App identity, confirmed upstream:
https://github.com/anthropics/claude-code-action/issues/396#issuecomment-3150844606

Use upstream pull_request with id-token: write. The previous pull_request_target exchange failed401, matching:
https://github.com/anthropics/claude-code-action/issues/713

The same-repository, non-draft predicate remains; fork PRs are excluded. Checkout remains on main without persisting its token. The pinned action restores sensitive base configuration before launching Claude. GitHub documents that repository writers can already access repository secrets:
https://docs.github.com/en/actions/reference/security/secure-use

Previous finding4392971185 assumed a same-repository writer lacked secret access. The GitHub repository-secret model contradicts that premise. No environment protection or repository rule changes here. Untrusted contributors must use forks.

The official action skips App authentication for workflow changes until the workflow exists on main (src/github/token.ts129-135 at8041f1d17e0e7d2f2cfe35002962e9f26237c0bb). This configuration PR cannot establish its own new App-auth review. After protected merge, an ordinary push to the contributor documentation PR must produce an actual claude[bot] comment. No extra merge gate is introduced.

Regression initially failed twice for explicit token and target event. Hosted attribution remains pending.
