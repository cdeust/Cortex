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

`scripts/ci_claude_reviews.py` (embedded in pipeline.yml, run with `python3 -I`)
accepts a claude[bot] (`type` Bot) review on the live head only when its first
line `<!-- claude-review:v2 kind=code|security findings=N run=<id>-<attempt> -->`
cites a run attempt that the Actions API shows is `.github/workflows/claude.yml`,
event `workflow_run`, branch `main`, this repository, with a job named
`review <head sha>` (the name is set by main's workflow from the server-derived
head) whose step `Validate <kind> review execution` concluded `success`. That
step runs main's code right after Claude: `ci_review_execution.py` proves the
skill and agents ran without permission denials (an empty execution file from
a soft skip fails), and `ci_claude_review_event.py --published <kind>` proves
this attempt published exactly the verdict file the trusted preparation step
pre-created (absent or empty fails). Markers without such a producer,
including a citation of a run that does not exist (gh prints the 404 body and
exits 1; read as an answer), are ignored: they neither satisfy nor suppress the
CI review.

Per kind, over the bound reviews of the head:

1. A review whose attempt completed with that kind's validation not `success`
   is superseded. If every bound review of the kind is superseded, the kind is
   `failed` with `retry`, and the next attempt reviews that kind again.
2. Exactly one remaining review: `pending` while its attempt runs, then
   `success` (N=0) or `unresolved` (N>0, blocked until a new head).
3. Two or more remaining reviews fail closed: `unresolved` if they come from
   different validated attempts and one has findings (a later `findings=0` never
   overrides real findings), otherwise `failed` without `retry` (two reviews of
   one attempt, a forged duplicate). A malformed marker citing an attempt with no
   failed validation also fails the head.

Recovery on the same head: the owner re-runs the claude.yml run (attempt 2);
its kinds step asks again only for kinds whose every attempt failed, publishes
markers citing `<id>-2`, and its own validation decides.
The Pipeline review job waits (`pending`, job green, merge named
`merge pending review`); the required `merge` context appears only after both
sources complete and the coordinator reruns the gate. `combined_proof` in
`scripts/ci_codex_review_resume.py` keeps the Codex proof unchanged while
Claude is not required.

## Bootstrap and activation

The trust anchor is main: `scripts/ci_claude_review_gate.py` lists
`.github/workflows` at `ref=main` and reads `CLAUDE_REVIEW_GATE` from main's
claude.yml; an unrecognised declaration (trailing comment, quotes, duplicates)
fails loudly. Absent or `observe` gives the distinct state `not_required`
(Codex-only, never a success claim); `required` makes Claude a prerequisite.
This PR installs claude.yml with `observe`, so it is Codex-only and cannot be
blocked by the gate it installs; by construction it cannot receive a claude[bot]
review either, because main has no claude.yml yet. After merge, every PR push
is reviewed and verified but not gated. Activation is a one-line follow-up PR
(`observe` to `required`) once a hosted claude[bot] review is recorded.

## Hosted proof and activation (after this PR merges)

Merging this PR changes nothing that gates: main says `observe`. Ordinary PRs
may already be merged when their `workflow_run` fires, so the proof uses the
activation PR itself, held open on purpose:

1. Open the one-line activation PR (`CLAUDE_REVIEW_GATE: observe` → `required`)
   held by the `hold` label (or "do not merge" in the title): those are the
   markers the merge step (`pipeline.yml` merge job), the completion handler
   (`scripts/ci_codex_review_event_source.py:96`) and the post-merge resolver
   (`pipeline-post-merge.yml:322-328`) honour; a `[hold]` title prefix alone is
   not one of them. Main still says `observe`, so its Pipeline is Codex-only and
   cannot hardlock, and claude.yml still reviews a held PR (its target ignores
   holds).
2. Its Pipeline request triggers main's claude.yml. Record: the claude.yml run
   id and attempt, the `review <head>` job id and both `Validate <kind> review
   execution` step conclusions, the two claude[bot] review ids on the head, the
   `verify` job conclusion, and the Pipeline run id with its review job state.
3. Condition for `required`: both kinds `success` or `unresolved` with run-bound
   evidence, `verify` green, no manual marker and no empty push. Then remove
   the hold and let the protected merge activate the gate.
4. If a Dependabot PR is open, record whether its claude.yml run received the
   secret before relying on `required` for Dependabot PRs.

## Review findings and fixes

| Finding | Verdict | Regression (fails on 005dc258) | Fix |
|---|---|---|---|
| Codex 4389070506: allowlist not exclusive, project settings loaded | valid: `settingSources` default user+project+local (`base-action/src/parse-sdk-options.ts:340-345`), `.claude/settings.json` allows `Bash(uv *)` | `test_ci_claude_workflow.py::test_review_sessions_ignore_repository_settings_and_deny_unlisted_tools` | `--setting-sources user --permission-mode dontAsk` on both review actions (CLI 2.1.311, `src/entrypoints/run.ts:80`, lists `dontAsk`) |
| Codex 4389070516: markers accepted despite failed execution validation | valid | `test_ci_claude_review_event.py::ResumeTests::test_failed_execution_validation_never_resumes`, `::test_marker_only_reviews_cannot_satisfy_the_required_gate`, `test_ci_claude_bootstrap.py::test_marker_only_or_forged_citation_never_satisfies_required_gate` | run-bound evidence in `scripts/ci_claude_reviews.py` (`_review_job`, `_kind_state`), shared by Pipeline, verify and both completion handlers |
| Codex 4389070526: stale run cancels newer head's reviewer | valid (group entry order is not dispatch order) | `test_ci_claude_workflow.py::test_review_concurrency_is_per_head_and_never_cancels` | review group keyed by head SHA, `cancel-in-progress: false` |
| Codex 4389092806: OAuth secret reachable from comment-driven commands | valid | `test_ci_claude_workflow.py::test_tag_job_is_owner_only_and_scrubs_subprocess_secrets` | tag job only when `github.event.sender.login == github.repository_owner`; `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB: "1"` on every action step (best effort per `action.yml:41-43`, passed at `:301`) |
| Coordinator msg_6cee25591704: tag/manual markers satisfy the gate | valid | as for 4389070516 | as for 4389070516 |
| Coordinator msg_037967ba0159 (a): publication check counts unbound markers; bind to run attempt | valid | `test_ci_claude_review_publication.py::test_unbound_or_other_attempt_markers_do_not_fail_this_attempt`, `test_ci_claude_reviews.py::ProvenanceTests::test_citation_of_another_attempt_is_unbound` | marker cites `<run id>-<attempt>`; jobs read from `/attempts/<n>/jobs`; `published()` counts only this attempt's markers |
| Coordinator msg_037967ba0159 (b): verdict files may never be created | valid (scoped Edit creating an absent file under dontAsk is unproven) | `test_ci_claude_workflow.py::test_trusted_preparation_creates_both_verdict_files`, `test_ci_claude_review_publication.py::test_absent_verdict_file_fails_closed` | preparation step pre-creates both files; absent or empty fails `--published` |
| Coordinator msg_bf2bf23dfa88: a failed attempt hardlocks the head (no retry, duplicate with the retry) | valid | `test_ci_claude_recovery.py` (5 of 6 fail on af490f5d; the same-attempt conflict guard passes on both) | `_validation`/`_kind_state` in `scripts/ci_claude_reviews.py` supersede failed attempts; `missing()` retries `retry` kinds |
| Own review: gate variants silently disable the gate | valid | `test_ci_claude_review_gate.py::test_gate_line_decides_activation` | `declares_required` fails loudly on unrecognised lines |

## Threat model (STRIDE) of the privileged path

| Threat | Vector | Guard |
|---|---|---|
| Spoofing | Marker review by github-actions[bot], a User or a look-alike login | login `claude[bot]` and type `Bot` required; tests per identity |
| Spoofing | @claude session or manual post writes markers as claude[bot] | evidence requires a validated claude.yml attempt; tag job owner-only |
| Spoofing | `findings=0` posted later citing a genuine attempt | two bound reviews of one kind fail; `--published` fails on a second marker |
| Tampering | PR rewrites the Actions-write job | resume runs only under `workflow_run` from main; no `pull_request_review` trigger |
| Tampering | Injected Claude runs tools beyond the review | `dontAsk`, user settings only, exact publish command, Edit only on its verdict file |
| Tampering | Stale review satisfies a new head | `commit_id` and job name `review <head>` must match the live head |
| Repudiation | Which run reviewed which head | marker cites `<run id>-<attempt>`, attested through the Actions API |
| Information disclosure | Secrets reach PR code or a non-owner prompt | PR never checked out or executed; owner-only tag job; subprocess scrub |
| Denial of service | Rerun loop while Claude pends | combined proof: no rerun until both sources complete (regression test) |
| Denial of service | Forged citation turns the gate red | a 404 is an answer (unbound), not an API error |
| Denial of service | Gate installed broken blocks every PR | staged activation; installing PR is Codex-only |
| Elevation of privilege | `actions: write` misused | one job, re-reads every fact from the REST API, reruns only the matching gate job |

Residual, recorded rather than closed here: a marker citing a genuine attempt
of the same head, posted by the owner's @claude session, fails that kind closed
(blocked until a new head); GitHub's Dependabot-on-Actions documentation
treats `workflow_run` runs started by Dependabot as Dependabot-triggered (no
Actions secrets), so before `required` the first hosted Dependabot PR must show
a claude[bot] review or a Dependabot secret must be configured (activation
precondition); a review body above GitHub's size limit is rejected by the POST
and stays pending (verify turns red).

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

Final state: commit 953ed145 (base `origin/main` 0a711837 after merging PR804;
this section was written after the run, markdown only). Before-runs copy the
final test files onto `git archive` of the earlier commit.

Round 1, before (`origin/main` b207d8c0): 53 failed, 5 passed; the decisive
line is the rerun loop of the Codex catch while Claude pends:

```
FAILED ...::CodexCoordinatorTests::test_codex_completion_waits_for_required_claude_review
E   AssertionError: Tuples differ: ({'action': 'review', 'job_id': 20}, [call(['gh', 'api[109 chars]ue)]) != ({'action': 'none'}, [])
```

Round 2, before (PR head 005dc258), the twelve regressions named in the table
above: `12 failed, 2 passed in 1.21s` (counting failed subtests). The two that
pass on 005dc258 are `test_failed_execution_validation_never_resumes`, because
005dc258 already rejected v2 markers as malformed, and
`test_marker_only_or_forged_citation_never_satisfies_required_gate`, whose
subtests fail. Failing lines include
`AssertionError: Tuples differ: ('false', 'true') != ('true', 'true')` (a tag
marker suppressed the CI review) and
`AttributeError: module 'ci_claude_reviews' has no attribute 'attest'`.

Round 3, before (af490f5d), `test_ci_claude_recovery.py`: `5 failed, 1 passed`,
for example `AssertionError: {'action': 'none'} != {'action': 'review',
'job_id': 20}` (a validated retry could not resume). The one that passes is the
same-attempt conflict guard, unchanged by design.

After, on 953ed145:

```
pytest (full suite): 11048 passed, 23 skipped, 2 warnings, 886 subtests passed in 499.58s; exit 0
uvx ruff@0.17.1 check . / format --check .: All checks passed! / 3837 files already formatted; exit 0 / 0
uvx ruff@0.16.6 check . / format --check .: All checks passed! / 3837 files already formatted; exit 0 / 0
python scripts/check_craftsmanship.py --base origin/main: Craftsmanship gate: OK; exit 0
actionlint claude.yml pipeline.yml Codex.yml: no output; exit 0
python scripts/check_doc_claims.py: doc claims OK
```

Ruff: no workflow or `ci.json` invokes Ruff since #786 (51fe5479 removed
`ci.yml` lines 709-719). The repository pins `ruff==0.17.1`
(`pyproject.toml:652`, `uv.lock:1497`), so both that pin and 0.16.6 were run.

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
