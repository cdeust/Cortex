# Pull request (cdeust/Cortex), documentation only

## Description

docs(ci): the notes of the review of #997, the clean copy of rule 8, and the runs ADR-1133 and ADR-1134 waited for (#998)

* docs(ci): the work is verified before the pull request exists (ADR-1132)

The CI contract held the review side of the practice Anthropic describes
(three reviews, one push per verdict, a verdict tied to the head) and
nothing about what an author does before the pull request exists.

- Rule 8 of the contract: before opening a pull request, and before each
  push to one, run the unit and regression commands of ci.json on a clean
  copy of the commit and put the commands and their counts in the body,
  with what was not run. A journal, changelog or documentation entry
  travels in the commit of the change it records.
- The pull request template gains "Risk and rollback".

Measured gap: 9 Pipeline runs for 6 commits on cdeust/ci-autonome on
11 November (two for one-file journal entries pushed alone, none run
locally first); 21 of 69 Pipeline runs on Cortex pull requests cancelled
by a later push between 10 and 12 November.

No workflow and no gate change.


* docs(ci): rule 8 names what a session cannot run; ADR-1132 corrected

What a fresh-context review of 0dff2a1 found, before any pull request.

- ADR-1132 and the message of 0dff2a1 said none of the six ci-autonome
  commits had been run locally first. That was false: the first one had
  been. The record now gives what the run list shows: three of the nine
  Pipeline runs repeated a commit (draft, then ready), two were for
  one-file journal entries.
- Rule 8 collided with "Review rounds" when a Blocker is itself a
  documentation entry, and with rule 4 after a conflict merge. It now
  says which governs.
- Rule 8 could not be followed by a cloud session: the dependency
  download of the unit command is refused by its network and initdb
  refuses the root user. Such a command is named in the body with the
  reason.
- The number 1132 had been given to a decision withdrawn before it was
  pushed; the record says so.


* ci: a documentation-only pull request runs environment and install on Linux alone (ADR-1133)

Every push to a pull request started the same eleven jobs, two of them
on macOS and two on Windows, whatever the change. Meta's selection
(engineering.fb.com, 2018) runs what a change can fail and keeps the
exhaustive run after it lands; the part that needs no history of test
outcomes is taken here.

- ci.json takes an optional docs_paths: directories and files whose
  change cannot alter what a test job runs. The validator embedded in
  both workflows refuses an entry that leaves the repository, starts
  with a dot or a slash, or is ci.json.
- The contract job selects the systems: Linux alone when every changed
  path of the pull request, a rename under both names, lies under
  docs_paths; the three systems for any other event or change, an
  unreadable file list, or a list at GitHub's limit.
- The resolver accepts the three systems, or Linux alone on both jobs.
  For Linux alone it reads docs_paths from the default branch and the
  files of the pull request, and refuses the merge unless it finds the
  pull request documentation-only itself.
- The Pipeline after merge is unchanged: three systems on the merge
  commit.
- scripts/ci_pipeline_source_contract.py pinned "every OS" word for
  word; it now pins the new rule, with a mutation case per clause.
- Cortex lists docs/, wiki/ and CHANGELOG.md.

Checked here: tests_py/scripts/test_ci_*.py and test_check_ci_*.py,
622 passed; the 6 failures of test_ci_mutation_scope.py are the same
on origin/main in this session. check_ci_gate_complete,
check_project_wiki, check_doc_claims, check_craftsmanship, ruff check
and ruff format --check pass. Not run: the unit and regression commands
of ci.json (dependency download refused by this session's network), and
no hosted run yet.


* ci: the selection counts paths, refuses names Windows cannot hold (ADR-1133)

What an adversarial fresh-context review of fdc38f3 found before any pull
request was opened. It found no way to merge with fewer systems than a
change needs; these are its notes.

- The selector counted files and the resolver counted paths, so 1500
  renames inside docs_paths were sent to Linux alone and then refused at
  every push. Both now count paths.
- A documentation file whose name Windows cannot hold (a reserved
  character or device name, a trailing dot or space) would have failed
  only after the merge, on the three systems. Such a path is never
  documentation.
- A file row without a usable name: the selector kept the three systems,
  the resolver skipped the row. Both now treat it as not documentation.
- A cut-short HTTP answer failed the contract job; it now keeps the three
  systems like any other unreadable list.
- The message of fdc38f3 said "a mutation case per clause": the clause
  `full = {...}` had none. It has one, and the call that passes the
  default branch's docs_paths is pinned and has one too.
- ADR-1133 said check_project_wiki.py runs in the Linux jobs of the
  Pipeline. It does not; the record now says where it runs.

The contract tests move to their own file to stay under the 300-line cap.

Checked here: tests_py/scripts/test_ci_*.py and test_check_ci_*.py,
622 passed, 764 subtests; the same 6 failures of
test_ci_mutation_scope.py as on origin/main in this session. The six
gates named in fdc38f3 pass. Not run: unit and regression of ci.json.


* docs(ci): the ci.json of a pull request passes the validator of the commit before its merge (ADR-1134)

The Pipeline after merge of pull request 996 failed at its first job
after the merge: run 43149580342, contract, "Validate ci.json",
`docs_paths: unknown key`. That run uses the workflow of the commit
before the merge, whose validator did not know the key 996 added to
ci.json. unit, regression, e2e, environment, install and tag were
skipped: c84dfb5 has had no test after its merge. Pull request 982
(low_risk_files, run 42968565597) failed the same way, and pull request
72 of claude-mods failed at the same step (run 42975150439).

- Rule 9 of the CI contract: the ci.json a pull request leaves passes
  the validator of the commit before its merge. A key enters ci.json in
  a pull request after the one that taught the validator to accept it; a
  required key leaves after the validator stopped requiring it; a pull
  request that changes both files replays the step first.
- ADR-1134 records the three runs and the replay of the step on each
  tree, and amends one sentence of ADR-1131: another repository no
  longer adds low_risk_files in the pull request that brings the
  workflows.

No workflow, script or test changes. The five paths lie under
docs_paths.

Checked here: the selector on the five paths (Linux alone);
check_ci_gate_complete, check_project_wiki, check_doc_claims,
check_craftsmanship, ruff check, ruff format --check; scripts/tests
(1 passed); tests_py/scripts without test_ci_mutation_scope.py: 1924
passed, 3 failed, 10 skipped, 54 errors, the same test ids as in a
worktree of c84dfb5. Not run: the unit and regression commands of
ci.json (dependency download refused by this session's network; initdb
refuses the root user).


* docs(ci): rule 9 is stated on the validator, not on ci.json alone (ADR-1134)

What a second fresh-context pass on d5c8d42 found, before any pull
request was opened.

- The rule spoke of ci.json alone. The validator also reads the version
  file ci.json names, so a pull request that changes the validator and
  that file, with ci.json untouched, fails the same step after its merge
  and triggered no replay. Rule 9 now reads: a pull request that changes
  the validator leaves a tree the earlier validator still passes, and
  such a pull request replays the step.
- "The first pull request changes nothing that reads the key" barred a
  reader that accepts the key's absence, as the selector of 996 does. It
  now reads: what fails without the key comes with the key or after it.
- "Their merge commit had no test after the merge" was false for 982: a
  later run tested a commit that contains it. Rule 9 and the changelog
  now say every test of that run was skipped.
- "Not done here: it is a change to both workflows" was false: the
  resolver is in pipeline-post-merge.yml alone.
- The runs not read now include ai-architect-mcp-codebase 509.
- An alternative was rejected because the two copies of the validator
  would differ; one text can read the event. That reason is removed and
  the one that holds is given.
- The message of d5c8d42 said another repository no longer adds
  low_risk_files in the pull request that brings the workflows. ADR-1134
  says something else: that repository first teaches its own validator
  to accept the key, in a pull request of its own.

The ADR file takes its new title; the five paths still lie under
docs_paths. The gates and scripts/tests named in d5c8d42 pass.


* docs(ci): ADR-1134 says which jobs were skipped, not that nothing was tested

What the third fresh-context pass found; it found no sequence that
follows rule 9 and still fails the step, and no harmless change the rule
forbids.

"Every test of that run was skipped", "the run tested nothing" and
"c84dfb5 has had no test after its merge" (also in the message of
d5c8d42) were false to the letter: in both runs the contract job ran
the guard test_no_main_comparison.py on the merge commit before it
failed. What was skipped is unit, regression, e2e, environment, install
and tag. Rule 9, the changelog and the ADR now say the test jobs were
skipped and that c84dfb5 has been through no test job after its merge.

The gates and scripts/tests named in d5c8d42 pass.


* docs(ci): rule 9 asks for the replay before each push; ADR-1133 records its first run

The three notes of review 2 of pull request 997, marked "no action
before merge", and what that pull request showed.

- Rule 9 and ADR-1134 asked for the replay before a pull request is
  opened. Rule 8 asks for its checks before each push as well; so does
  rule 9 now. A commit pushed later that adds the key would otherwise
  bring back the case the rule is written against.
- Rule 9 said "what fails without the key" without saying what that is.
  It now carries the words of ADR-1134: a validator that requires the
  key, or a reader that refuses its absence.
- The status of ADR-1131 names ADR-1134, which amends one sentence of
  it, as ADR-1097 and ADR-1106 name the record that amends them.
- ADR-1133 said the job names of a one-element matrix were not proven.
  Pull request 997 was the first documentation-only one: its Pipeline
  runs 43154988108 (draft) and 43157084794 (ready) started
  `environment (ubuntu-latest)` and `install (ubuntu-latest)` and no
  macOS or Windows job, and the resolver merged it on that matrix (run
  43158939841).

No workflow, script or test changes. check_ci_gate_complete,
check_project_wiki, check_doc_claims, check_craftsmanship, ruff check,
ruff format --check and scripts/tests pass.


* docs(ci): rule 8 names the worktree as the clean copy; ADR-1134 records the run that covered c84dfb5

- Rule 8 offered a worktree or a `git archive` as the clean copy on
  which the unit and regression commands are run. On an archive, three
  tests of tests_py/scripts, which the unit command runs, ask git about
  the tree and fail:
  test_ci_native_claude_settings.py::test_settings_local_is_not_tracked
  and two tests of test_uv_lock_single_source.py. Measured on c84dfb5:
  the same suite in a worktree does not have these three failures. The
  rule names the worktree alone.
- ADR-1134 said the next merge would cover c84dfb5, which went through
  no test job in its own run after merge. It names the run: 43158939841,
  after the merge of pull request 997, green on 5ea8b83 for unit,
  regression, e2e, environment and install on the three systems, and
  tag.

check_ci_gate_complete, check_project_wiki, check_doc_claims,
check_craftsmanship, ruff check, ruff format --check and scripts/tests
pass.


* docs(ci): ADR-1134 names the run that first covered c84dfb5

What a fresh-context read of b26281e and b71ff86 found before any pull
request was opened; it found nothing else to correct.

- b71ff86 named run 43158939841 as the one that covered c84dfb5. That
  run is green on a commit that contains it, but it was not the first:
  the next merge after 996 was pull request 994, run 43156874217, which
  ended with success at 05:06 UTC. The record names both, and says
  which jobs of 43158939841 ran on Linux and which on the three
  systems; b71ff86 read as if all had run on the three.
- Rule 8 said three tests of the unit command fail on a `git archive`.
  Three were measured in tests_py/scripts; the whole unit suite cannot
  be run in this session, so the rule gives no count.

The gates and scripts/tests named in b71ff86 pass.


---------


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
