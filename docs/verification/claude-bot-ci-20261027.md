# claude[bot] code and security reviews beside Codex

Decision: ADR-1116. Owner direction 2026-10-27: restore genuine claude[bot]
reviews on every same-repository PR push, alongside the native Codex gate, with
no pending hardlock and no fabricated approval. Branch `fix/claude-bot-review`,
cut from `origin/main` b207d8c007553eb706ad3eb3aaccc1d89bafa9a2.

## Upstream, read at the source

`anthropics/claude-code-action@8041f1d17e0e7d2f2cfe35002962e9f26237c0bb`
(tag v1.0.263), the commit whose 225 files were read in full for
`ci-codex-only-20261027.md`. Every `uses:` in claude.yml pins this SHA.

| Fact | Source at 8041f1d |
|---|---|
| Without `github_token`, auth is a GitHub OIDC token (audience `claude-code-github-action`, needs `id-token: write`) exchanged for a claude[bot] App token | `src/github/token.ts:58`, `:121` |
| Exchange refusal `workflow_not_found_on_default_branch`, or 401 "workflow validation failed", is a soft skip: warning, step green, nothing posted | `src/github/token.ts:24-54`, `:135`; `src/entrypoints/run.ts:179-180` |
| The server requires the workflow to exist with identical content on the default branch | `test/token.test.ts:75` |
| Agent mode refuses non-User `GITHUB_ACTOR` unless listed in `allowed_bots` | `src/modes/agent/index.ts:30`, `src/github/validation/actor.ts` |
| On `workflow_run`, write access is checked for the actor and the upstream run's actor; `[bot]` actors pass | `src/github/validation/permissions.ts:37`, `:114` |
| The App token (contents, pull-requests, issues: write) is revoked when the action step ends | `action.yml:448` |
| `--add-dir` in `claude_args` is honoured | `base-action/src/parse-sdk-options.ts:22`, `:210` |

Consequences: a green Claude job is never evidence; only a claude[bot] review
on the exact head is. `github_token` is never passed (the identity would become
github-actions[bot]). Claude must publish inside its own step, so its single
allowed write is the exact `gh api ... /pulls/N/reviews -f commit_id=<head>`
command; `Bash(gh api:*)` would let an injected prompt push with contents:write.

## Why workflow_run

`workflow_run` always runs the default-branch copy of claude.yml, so the OIDC
exchange accepts it even when the PR edits CI, and the PR is read only as a
diff file. `pull_request_review` runs the workflow from `refs/pull/N/merge`
(GitHub events reference), so an Actions-write job under it would be
PR-controlled; the repository already forbids that for Codex.yml. Completion
therefore runs in the same `workflow_run` run: `resume` (needs target and
review) calls the shared coordinator; Codex.yml's existing Pipeline-completed
catch covers the race where the Pipeline finishes after the reviews, because
both use the same combined proof and the same per-PR concurrency group.

## Evidence model

`scripts/ci_claude_reviews.py` (embedded in pipeline.yml, run with `python3 -I`):
claude[bot] (`type` Bot) reviews whose `commit_id` is the live head and whose
first body line is `<!-- claude-review:v1 kind=code|security findings=N -->`.
Per kind: success (N=0), unresolved (N>0, blocked until a new head), pending
(absent, stale head, other author), failed (malformed marker, non-COMMENTED
state, or two reviews of one kind on one head). The Pipeline review job waits
(`pending`, job green, merge named `merge pending review`); the required
`merge` context appears only after both sources complete and the coordinator
reruns the gate. `combined_proof` in `scripts/ci_codex_review_resume.py` keeps
the Codex proof unchanged while Claude is not required.

## Bootstrap and activation

The trust anchor is main: the reader lists `.github/workflows` at `ref=main`
and reads `CLAUDE_REVIEW_GATE` from main's claude.yml. Absent or `observe`
gives the distinct state `not_required` (Codex-only, never a success claim);
`required` makes Claude a prerequisite. This PR installs claude.yml with
`observe`, so it is Codex-only and cannot be blocked by the gate it installs;
by construction it cannot receive a claude[bot] review either, because main has
no claude.yml yet. After merge, every PR push is reviewed and verified but not
gated. Activation is a one-line follow-up PR (`observe` to `required`) once a
hosted claude[bot] review is recorded; that PR is still Codex-only because main
says `observe`.

## Threat model (STRIDE) of the privileged path

| Threat | Vector | Guard |
|---|---|---|
| Spoofing | Marker review by github-actions[bot], a User or a look-alike login | login `claude[bot]` and type `Bot` required; tests per identity |
| Spoofing | `findings=0` posted later to override findings | duplicate kind on one head fails |
| Tampering | PR rewrites the Actions-write job | resume runs only under `workflow_run` from main; no `pull_request_review` trigger |
| Tampering | Injected Claude edits the checkout to fake validation | verify and resume are separate fresh jobs; Claude may edit only its review file |
| Tampering | Stale review satisfies a new head | `commit_id` must equal the live head, rechecked before and after reads |
| Repudiation | Which run reviewed which head | review on `commit_id`, run-name carries the Pipeline run id |
| Information disclosure | Secrets reach PR code | PR never checked out or executed; `persist-credentials: false`; no `github_token` |
| Denial of service | Rerun loop while Claude pends | combined proof: no rerun until both sources complete (regression test) |
| Denial of service | Gate installed broken blocks every PR | staged activation; installing PR is Codex-only |
| Elevation of privilege | `actions: write` misused | one job, re-reads every fact from the REST API, reruns only the matching gate job |

Residual: the @claude tag job also posts as claude[bot] with broad tools for a
human with write access; its reviews are indistinguishable by identity. A
duplicate-kind review it posts fails closed (blocked until a new head).

## Three pillars

- Research: done. Upstream read at the pinned SHA (table above); repository
  invariants and the Codex completion design read in `scripts/ci_codex_*`.
- SSDLC: done. SHA pins, `permissions: {}` at workflow level with per-job
  grants, one Actions-write job, STRIDE table above, regression tests that fail
  on `origin/main` and pass on this branch, ruff, craftsmanship and actionlint.
- Operations: not applicable at infrastructure level: no new runtime service,
  data store or credential; the existing `CLAUDE_CODE_OAUTH_TOKEN` secret is
  only named. Hosted verification is planned at: the first same-repository PR
  push after this merges; the coordinator records the run id and the two
  claude[bot] review ids before the activation PR.

## Local gates

Measured on commit 7b6e13a2 (only this section was amended after;
markdown only). Before: the final `tests_py/scripts/test_ci_claude_*.py` files
copied onto `git archive origin/main`:

```
53 failed, 5 passed, 12 subtests passed in 1.85s
FAILED ...::CodexCoordinatorTests::test_codex_completion_waits_for_required_claude_review
E   AssertionError: Tuples differ: ({'action': 'review', 'job_id': 20}, [call(['gh', 'api[109 chars]ue)]) != ({'action': 'none'}, [])
```

The last line is the rerun loop on `origin/main`: with Claude required and
pending, the Codex catch reruns the green waiting job. After, on this branch:

```
pytest tests_py/scripts/test_ci_claude_*.py: 51 passed, 58 subtests passed in 2.06s
pytest (full suite): 10993 passed, 23 skipped, 2 warnings, 865 subtests passed in 478.05s; exit=0
uvx ruff@0.16.6 check .: All checks passed!; exit=0
uvx ruff@0.16.6 format --check .: 3824 files already formatted; exit=0
python scripts/check_craftsmanship.py --base origin/main: Craftsmanship gate: OK; exit=0
actionlint claude.yml pipeline.yml Codex.yml: no output; exit=0
python scripts/check_doc_claims.py: doc claims OK; exit=0
```

Environment of the run: a worktree-local venv synced from `uv.lock` (the main
checkout's shared venv had drifted), and `UV_PYTHON=/opt/homebrew/bin/python3.13`
because `uv venv` otherwise selects an x86_64 managed CPython that cannot run
on this arm64 host (`Bad CPU type in executable`), which
`tests_py/scripts/test_launcher_platform_coverage.py` needs.

## Official sources

- [Events that trigger workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)
- [Pull request reviews REST API](https://docs.github.com/en/rest/pulls/reviews)
- [Repository contents REST API](https://docs.github.com/en/rest/repos/contents)
- [Rerun a job and its dependents](https://docs.github.com/en/rest/actions/workflow-runs#re-run-a-job-from-a-workflow-run)
- [Claude Code GitHub Actions](https://code.claude.com/docs/en/github-actions)
