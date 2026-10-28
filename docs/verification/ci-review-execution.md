# Native Codex CI review evidence

Owner decision on 2026-10-27: replace Claude review and repair automation with
Codex. Closed PR797 at source commit 1a21a96abbe6cd79d4be94dc3a358a545fd5e4ef
is preserved in the replacement branch. The requested closure comment is
[recorded on PR797](https://github.com/cdeust/Cortex/pull/797#issuecomment-6432168534).

Both native Codex code and security reviews must complete on the current PR
head. The review job accepts completed findings for downstream correction;
the merge gate requires no unresolved findings. Missing, malformed, stale or
failed evidence blocks integration. The authenticated canonical bot summary,
not prose acknowledgements, supplies the evidence.

The review job has read permissions and no checkout. Its embedded evidence
reader runs with isolated Python and has exact parity tests against
scripts/ci_codex_reviews.py. Candidate Python modules cannot replace it.
All existing contract, unit, regression, end-to-end, environment and install
requirements remain. The protected merge resolver still checks the current
head, holds and completed prerequisites.

Codex.yml receives authenticated native summary edits and completed Pipeline
failures. It checks trusted main code and reconstructs the effective job graph
from all authenticated attempts before resuming a waiting gate. A newer
expanded matrix supersedes its older skipped placeholder. Unexpected failures
remain in the graph and continue to block integration.

Regression evidence: native Codex finding4384491846 was reproduced before the
change: an older skipped environment/install placeholder prevented review
resumption despite successful newer matrix children. The focused fixture
failed before implementation and passed after it. The existing unrelated
failure and partial-rerun fixtures are retained.

## Official sources

- [Native Codex reviews and task delegation](https://learn.chatgpt.com/docs/third-party/github)
- [Codex Security Review](https://learn.chatgpt.com/docs/security/security-review)
- [Workflow job attempt API](https://docs.github.com/en/rest/actions/workflow-jobs#list-jobs-for-a-workflow-run-attempt)
- [Job conditions precede matrix expansion](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idif)
- [Rerun a job and its dependents](https://docs.github.com/en/rest/actions/workflow-runs#re-run-a-job-from-a-workflow-run)

## Upstream source reading

The complete anthropics/claude-code-action repository was read before removing
its automation: all 225 files, 1,535,212 bytes, at immutable commit
8041f1d17e0e7d2f2cfe35002962e9f26237c0bb. Coverage across 62 literal reading
batches was checked without gaps and each file SHA256 verified. This source
inspection does not substitute for hosted validation of the replacement.
