# Pull request (cdeust/Cortex), documentation only

## Description

Title: docs(ci): the notes of the review of #997, the clean copy of rule 8, and the runs ADR-1133 and ADR-1134 waited for

## Summary

Follow-up to #997, documentation only. Review 2 of #997 left three notes marked "no action before merge"; rule 6 sends them to a follow-up pull request. Two records also waited for runs that have now happened, and one sentence of rule 8 was found false while it was being copied to another repository.

- **Rule 9, ADR-1134 (notes 1 and 3).** The replay is asked before a pull request is opened and before each push to it, as rule 8 asks for its checks. "What fails without the key" carries its gloss: a validator that requires the key, or a reader that refuses its absence.
- **ADR-1131 (note 2).** Its status names ADR-1134, which amends one sentence of its consequences, as ADR-1097 and ADR-1106 name the record that amends them.
- **ADR-1133.** It said the job names of a one-element matrix were not proven. #997 was the first documentation-only pull request: its Pipeline runs 43154988108 (draft) and 43157084794 (ready) started `environment (ubuntu-latest)` and `install (ubuntu-latest)` and no macOS or Windows job, six machines for the draft and seven once ready, and the resolver merged it on that matrix (run 43158939841).
- **ADR-1134.** It said the next merge would cover `c84dfb5`, which went through no test job in its own run after merge. The next merge was #994: run 43156874217 ended with success at 05:06 UTC. The run after it, 43158939841 for #997, was read job by job and is green on the three systems.
- **Rule 8.** It offered a worktree or a `git archive` as the clean copy. On an archive, tests of the `unit` command ask git about the tree and fail. The rule names the worktree alone.

No workflow, script or test changes. No changelog entry: nothing a user of the repository sees changes; the entry of rule 9 under Unreleased still describes it.

No issue.

## Type of change

- [x] Documentation only

## Test plan

Run on the head of this branch, in this session (rule 8):

| Command | Result |
|---|---|
| The selector of `pipeline.yml` (`select`) on the seven changed paths | `['ubuntu-latest']`, "all 7 changed paths lie under docs_paths" |
| `python3 scripts/check_ci_gate_complete.py` | exit 0 |
| `python3 scripts/check_project_wiki.py` | exit 0 |
| `python3 scripts/check_doc_claims.py` | exit 0 |
| `python3 scripts/check_craftsmanship.py` | exit 0 |
| `ruff check .` and `ruff format --check .` (0.17.3) | pass |
| `python3 -m unittest discover -s scripts/tests` | 1 passed |

The measurement behind the change to rule 8, on `c84dfb5`: `pytest tests_py/scripts` in a worktree gives 3 failed, 1924 passed; on a `git archive` of the same commit, 6 failed, 1920 passed. The three more are `test_ci_native_claude_settings.py::SettingsAgainstMentionJob::test_settings_local_is_not_tracked`, and `test_every_uv_sync_installs_the_lock_as_it_is` and `test_no_dependency_file_but_the_lock_is_left_for_dependabot` of `test_uv_lock_single_source.py`. `scripts/ci_unit.sh` runs pytest on `tests_py`, so the `unit` command runs them. The count for the whole `unit` suite was not measured, so the rule gives none.

Not run here: the `unit` and `regression` commands of `ci.json`. Their dependency download is refused by this session's network, and `initdb` refuses the root user.

- [ ] All existing tests pass. Not shown here: the hosted Pipeline decides.
- [x] New tests added for new behavior. None: no behaviour changes.
- [x] Mutation survival check: not applicable, no code.
- [x] Manual verification: each run cited was read through the GitHub API.

## Risk and rollback

- Risk: no code, workflow, script or test changes, so nothing the product runs can change. If a sentence is wrong, an agent follows a wrong instruction: the worktree asked by rule 8 is the stricter of the two copies the rule used to allow.
- How to revert: `git revert <sha>`. The mirrors under `docs/adr/` are reverted with it.

## Audit notes

- Fresh-context read of the two first commits before this pull request was opened, by an agent told to refute each sentence against the runs and the git history. One blocker, taken in `0b05332`: the record named run 43158939841 as the one that covered `c84dfb5`, while #994's run had done so first; it also read as if `unit`, `regression` and `e2e` had run on three systems. It checked the job counts of the two Pipeline runs of #997, the place of the amended sentence in ADR-1131, and that the three tests call git.
- Two notes of an earlier review of the selection tests are not in this pull request, which is documentation only: `test_ci_platform_selection.py` checks the inline matrix of the Pipeline after merge as text, and one mutation of the selector's `main()` passes every test (the resolver would refuse the merge it leads to).
- Outstanding: rule 9 is not enforced by a check (ADR-1134, alternatives).

## Coding-standards compliance

Not applicable: no code.

## Breaking changes

None.

## Screenshots / logs

None.

## Reviewer checklist

- [ ] CHANGELOG.md updated under the appropriate section. Not updated: see Summary.
- [x] Documentation updated (`docs/agent-guidance.md`, ADR-1131, ADR-1133, ADR-1134).
- [x] No secrets / credentials / PII in the diff.
- [ ] CI passes on the latest commit.

---
_Generated by [Claude Code](https://claude.ai/code/session_018kyZYtEfyyt6kEbR9NawFb)_

## Diff

```diff
diff --git a/docs/adr/ADR-1131-the-resolver-reads-the-low-risk-file-names-from-ci-json.md b/docs/adr/ADR-1131-the-resolver-reads-the-low-risk-file-names-from-ci-json.md
index d4cd753..ca9d987 100644
--- a/docs/adr/ADR-1131-the-resolver-reads-the-low-risk-file-names-from-ci-json.md
+++ b/docs/adr/ADR-1131-the-resolver-reads-the-low-risk-file-names-from-ci-json.md
@@ -12,7 +12,7 @@ title: The resolver reads the low-risk file names from ci.json
 
 ## Status
 
-accepted. Amends ADR-1126 (a Dependabot minor or patch update of the dependency files merges without a review): the file names leave the workflow.
+accepted. Amends ADR-1126 (a Dependabot minor or patch update of the dependency files merges without a review): the file names leave the workflow. One sentence of its consequences amended by ADR-1134 (how another repository takes `low_risk_files`).
 
 ## Context
 
diff --git a/docs/adr/ADR-1133-a-documentation-only-pull-request-runs-environment-and-install-on-linux-alone.md b/docs/adr/ADR-1133-a-documentation-only-pull-request-runs-environment-and-install-on-linux-alone.md
index f4b5d6f..c2d0a33 100644
--- a/docs/adr/ADR-1133-a-documentation-only-pull-request-runs-environment-and-install-on-linux-alone.md
+++ b/docs/adr/ADR-1133-a-documentation-only-pull-request-runs-environment-and-install-on-linux-alone.md
@@ -42,7 +42,7 @@ The resolver required the three legs of both jobs by name (`_validate_jobs`), an
 - The selector and the resolver count the same thing, paths, so that a pull request the selector sends to Linux alone is not refused for its size by the resolver.
 - `scripts/ci_pipeline_source_contract.py` pins the text of the resolver, not its behaviour. In review, ten hand changes to the resolver went past it; the tests caught nine, and the tenth now has a pinned clause and a mutation case.
 - Two scripts still name the six legs (`scripts/ci_codex_review_resume.py`, `scripts/ci_autopilot_queue.py`). No job of the Pipeline calls them (read, not run).
-- Not proven before the merge: no hosted run has yet shown the job names GitHub gives a one-element `fromJSON` matrix. The resolver expects `environment (ubuntu-latest)` and `install (ubuntu-latest)`; the first documentation-only pull request will show it, and a different name would be refused, not merged.
+- Not proven before the merge: the job names GitHub gives a one-element `fromJSON` matrix. Shown since on pull request 997, the first documentation-only one. Its two Pipeline runs (43154988108 as a draft, 43157084794 once ready) started `environment (ubuntu-latest)` and `install (ubuntu-latest)` and no macOS or Windows job, six machines for the draft and seven once ready, and the resolver merged it on that matrix (run 43158939841).
 
 ## Alternatives considered
 
diff --git a/docs/adr/ADR-1134-a-pull-request-that-changes-the-ci-json-validator-leaves-a-tree-the-earlier-validator-passes.md b/docs/adr/ADR-1134-a-pull-request-that-changes-the-ci-json-validator-leaves-a-tree-the-earlier-validator-passes.md
index 2c51771..98b2886 100644
--- a/docs/adr/ADR-1134-a-pull-request-that-changes-the-ci-json-validator-leaves-a-tree-the-earlier-validator-passes.md
+++ b/docs/adr/ADR-1134-a-pull-request-that-changes-the-ci-json-validator-leaves-a-tree-the-earlier-validator-passes.md
@@ -49,7 +49,7 @@ Rule 8 arrived with 996 itself. It asks an author to run what a change needs bey
 ## Decision
 
 1. Rule 9 of the CI contract: a pull request that changes the validator leaves a tree the earlier validator still passes. The validator is the script of the step "Validate ci.json", embedded in `pipeline.yml` and `pipeline-post-merge.yml`.
-2. Such a pull request replays the step before it is opened: the validator as it was before the pull request's commits, on the tree after them. A pull request that leaves the validator alone needs no replay: its own `contract` job runs that validator.
+2. Such a pull request replays the step before it is opened and before each push to it: the validator as it was before the pull request's commits, on the tree after them. A pull request that leaves the validator alone needs no replay: its own `contract` job runs that validator.
 3. For a key, it follows that the key enters `ci.json` in a pull request after the one that taught the validator to accept it. What fails without the key, a validator that requires it or a reader that refuses its absence, comes with the key or after it. A key the validator requires leaves `ci.json` after the validator stopped requiring it.
 4. ADR-1131 said a repository that takes the two workflows "must add `low_risk_files` to its `ci.json` in the same pull request". That is the case measured on claude-mods. Such a repository first teaches its own validator to accept the keys it lacks, in a pull request of its own.
 
@@ -59,7 +59,7 @@ Rule 8 arrived with 996 itself. It asks an author to run what a change needs bey
 - The rule does not forbid a pull request that changes `ci.json` and the validator when the earlier validator passes the result: a command value, or the revert of 996 in one commit.
 - The replay uses the validator the branch started from. The Pipeline after merge uses the validator of the main branch at the merge. The two differ when the main branch changed its validator in between, which an author does not check (rule 4).
 - Rule 9 names the validator because it is the case measured. Every other step of the Pipeline after merge also comes from the earlier commit. Whether one of them has failed for that reason was not looked for.
-- `c84dfb5`, the merge commit of 996, has been through no test job after its merge. The next merge covers it: the Pipeline after merge runs the three systems on a merge commit that contains it.
+- `c84dfb5`, the merge commit of 996, went through no test job in its own run after merge. The next merge covered it: run 43156874217 merged pull request 994 on top of it as `22523c4` and ended with success at 05:06 UTC on 12 November 2026. The run after it, 43158939841 for pull request 997, was read job by job on `5ea8b83`: `unit`, `regression` and `e2e` on Linux, `environment` and `install` on the three systems, and `tag`, all green.
 - The rule is not enforced by a check.
 
 ## Alternatives considered
diff --git a/docs/agent-guidance.md b/docs/agent-guidance.md
index f47a136..3e3c03d 100644
--- a/docs/agent-guidance.md
+++ b/docs/agent-guidance.md
@@ -196,8 +196,9 @@ the repository's own standards apply. They never widen what a prompt allows.
    `ci/budget-counts-contract-reviews`, anything labelled `hold` or `do-not-merge`, a draft.
 8. **The work is verified before the pull request exists** (ADR-1132). Before opening a
    pull request, and before each push to one, run the `unit` and `regression` commands of
-   `ci.json` on a clean copy of the commit (a worktree under `.claude/worktrees/` or a
-   `git archive`), plus what the change needs beyond them, and put each command with
+   `ci.json` on a clean copy of the commit, a worktree under `.claude/worktrees/` (a
+   `git archive` is not one: tests of the `unit` command ask git about the tree and fail
+   on it), plus what the change needs beyond them, and put each command with
    its passed, failed and skipped counts in the pull request body. A command the
    session cannot run (a host its network refuses, `initdb` under the root user) is
    named there with the reason. The hosted Pipeline stays the gate; it is not the place
@@ -210,11 +211,12 @@ the repository's own standards apply. They never widen what a prompt allows.
    the version file it names, with the validator of that earlier commit. The two pull
    requests that added a key to `ci.json` together with the validator that accepts it
    (982, 996) each merged, then failed that job, and the test jobs of that run were skipped.
-   Such a pull request replays the step before it is opened: the validator as it was
-   before its commits, on the tree after them. So a key enters `ci.json` in a pull
-   request after the one that taught the validator to accept it; what fails without the
-   key comes with the key or after it; a key the validator requires leaves `ci.json`
-   after the validator stopped requiring it.
+   Such a pull request replays the step before it is opened and before each push to it:
+   the validator as it was before its commits, on the tree after them. So a key enters
+   `ci.json` in a pull request after the one that taught the validator to accept it;
+   what fails without the key, a validator that requires it or a reader that refuses
+   its absence, comes with the key or after it; a key the validator requires leaves
+   `ci.json` after the validator stopped requiring it.
 
 ## What NOT to do
 
diff --git a/wiki/adr/cortex/1131-the-resolver-reads-the-low-risk-file-names-from-ci-json.md b/wiki/adr/cortex/1131-the-resolver-reads-the-low-risk-file-names-from-ci-json.md
index 7045fa8..f55d0a8 100644
--- a/wiki/adr/cortex/1131-the-resolver-reads-the-low-risk-file-names-from-ci-json.md
+++ b/wiki/adr/cortex/1131-the-resolver-reads-the-low-risk-file-names-from-ci-json.md
@@ -10,7 +10,7 @@ title: The resolver reads the low-risk file names from ci.json
 
 ## Status
 
-accepted. Amends ADR-1126 (a Dependabot minor or patch update of the dependency files merges without a review): the file names leave the workflow.
+accepted. Amends ADR-1126 (a Dependabot minor or patch update of the dependency files merges without a review): the file names leave the workflow. One sentence of its consequences amended by ADR-1134 (how another repository takes `low_risk_files`).
 
 ## Context
 
diff --git a/wiki/adr/cortex/1133-a-documentation-only-pull-request-runs-environment-and-install-on-linux-alone.md b/wiki/adr/cortex/1133-a-documentation-only-pull-request-runs-environment-and-install-on-linux-alone.md
index db51bb2..1d4960d 100644
--- a/wiki/adr/cortex/1133-a-documentation-only-pull-request-runs-environment-and-install-on-linux-alone.md
+++ b/wiki/adr/cortex/1133-a-documentation-only-pull-request-runs-environment-and-install-on-linux-alone.md
@@ -40,7 +40,7 @@ The resolver required the three legs of both jobs by name (`_validate_jobs`), an
 - The selector and the resolver count the same thing, paths, so that a pull request the selector sends to Linux alone is not refused for its size by the resolver.
 - `scripts/ci_pipeline_source_contract.py` pins the text of the resolver, not its behaviour. In review, ten hand changes to the resolver went past it; the tests caught nine, and the tenth now has a pinned clause and a mutation case.
 - Two scripts still name the six legs (`scripts/ci_codex_review_resume.py`, `scripts/ci_autopilot_queue.py`). No job of the Pipeline calls them (read, not run).
-- Not proven before the merge: no hosted run has yet shown the job names GitHub gives a one-element `fromJSON` matrix. The resolver expects `environment (ubuntu-latest)` and `install (ubuntu-latest)`; the first documentation-only pull request will show it, and a different name would be refused, not merged.
+- Not proven before the merge: the job names GitHub gives a one-element `fromJSON` matrix. Shown since on pull request 997, the first documentation-only one. Its two Pipeline runs (43154988108 as a draft, 43157084794 once ready) started `environment (ubuntu-latest)` and `install (ubuntu-latest)` and no macOS or Windows job, six machines for the draft and seven once ready, and the resolver merged it on that matrix (run 43158939841).
 
 ## Alternatives considered
 
diff --git a/wiki/adr/cortex/1134-a-pull-request-that-changes-the-ci-json-validator-leaves-a-tree-the-earlier-validator-passes.md b/wiki/adr/cortex/1134-a-pull-request-that-changes-the-ci-json-validator-leaves-a-tree-the-earlier-validator-passes.md
index c371fbc..d7d84d4 100644
--- a/wiki/adr/cortex/1134-a-pull-request-that-changes-the-ci-json-validator-leaves-a-tree-the-earlier-validator-passes.md
+++ b/wiki/adr/cortex/1134-a-pull-request-that-changes-the-ci-json-validator-leaves-a-tree-the-earlier-validator-passes.md
@@ -47,7 +47,7 @@ Rule 8 arrived with 996 itself. It asks an author to run what a change needs bey
 ## Decision
 
 1. Rule 9 of the CI contract: a pull request that changes the validator leaves a tree the earlier validator still passes. The validator is the script of the step "Validate ci.json", embedded in `pipeline.yml` and `pipeline-post-merge.yml`.
-2. Such a pull request replays the step before it is opened: the validator as it was before the pull request's commits, on the tree after them. A pull request that leaves the validator alone needs no replay: its own `contract` job runs that validator.
+2. Such a pull request replays the step before it is opened and before each push to it: the validator as it was before the pull request's commits, on the tree after them. A pull request that leaves the validator alone needs no replay: its own `contract` job runs that validator.
 3. For a key, it follows that the key enters `ci.json` in a pull request after the one that taught the validator to accept it. What fails without the key, a validator that requires it or a reader that refuses its absence, comes with the key or after it. A key the validator requires leaves `ci.json` after the validator stopped requiring it.
 4. ADR-1131 said a repository that takes the two workflows "must add `low_risk_files` to its `ci.json` in the same pull request". That is the case measured on claude-mods. Such a repository first teaches its own validator to accept the keys it lacks, in a pull request of its own.
 
@@ -57,7 +57,7 @@ Rule 8 arrived with 996 itself. It asks an author to run what a change needs bey
 - The rule does not forbid a pull request that changes `ci.json` and the validator when the earlier validator passes the result: a command value, or the revert of 996 in one commit.
 - The replay uses the validator the branch started from. The Pipeline after merge uses the validator of the main branch at the merge. The two differ when the main branch changed its validator in between, which an author does not check (rule 4).
 - Rule 9 names the validator because it is the case measured. Every other step of the Pipeline after merge also comes from the earlier commit. Whether one of them has failed for that reason was not looked for.
-- `c84dfb5`, the merge commit of 996, has been through no test job after its merge. The next merge covers it: the Pipeline after merge runs the three systems on a merge commit that contains it.
+- `c84dfb5`, the merge commit of 996, went through no test job in its own run after merge. The next merge covered it: run 43156874217 merged pull request 994 on top of it as `22523c4` and ended with success at 05:06 UTC on 12 November 2026. The run after it, 43158939841 for pull request 997, was read job by job on `5ea8b83`: `unit`, `regression` and `e2e` on Linux, `environment` and `install` on the three systems, and `tag`, all green.
 - The rule is not enforced by a check.
 
 ## Alternatives considered
```
