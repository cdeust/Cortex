---
allowed-tools: Bash(gh pr comment:*),Bash(gh pr diff:*),Bash(gh pr view:*)
description: Review a pull request
---

Perform a comprehensive code review using subagents for key areas:

- code-quality-reviewer
- performance-reviewer
- test-coverage-reviewer
- documentation-accuracy-reviewer
- security-code-reviewer

Instruct each to only provide noteworthy feedback. Once they finish, review the feedback and post only the feedback that you also deem noteworthy.

Instruct code-quality-reviewer and documentation-accuracy-reviewer, in addition, to try to refute the pull request, not to confirm it (ADR-1135):

- For every factual statement the diff or the description adds (in documentation, records, rules, comments, changelog), find its primary source: the files of the repository, the diff itself, or a run, commit or pull request it cites. Report each statement that is false, unsupported, contradicted by another statement of the same pull request, or stronger than its evidence.
- For every rule or procedure the pull request adds, give a concrete case that follows the rule and still fails, or a harmless case the rule forbids.
- For every change to a workflow, a CI script, or a file CI reads: say which commit's version of each workflow runs each job, before and after the merge, and whether the tree the pull request leaves passes every step that will run on it.

Provide feedback using inline comments for specific issues.
Use top-level comments for general observations or praise.
Keep feedback concise.

---
