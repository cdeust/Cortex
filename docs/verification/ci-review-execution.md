# Reject blocked review executions

Cortex PR796, run40200974594 attempt2, review job121876760991 returned a
successful SDK result with one denied tool operation. Its rendered report
acknowledged a manual partial review in place of the native skill's agents.
The job passed and the protected resolver merged the PR. Independent Codex
code and security reviews subsequently completed without findings on the exact
head `5fa52b6711ffffe765800a3814871b68c98bb995`.

The review job now validates each action's raw SDK execution file. It rejects
missing or malformed evidence, failed execution, denied permissions and tool
errors. Separate automatic code and security actions each invoke their real
native Skill tool exactly once and validate it before the next action starts.
Code review requires seven completed synchronous agents, following steps 1-4
of the official code-review command. Security review requires at least one
independent completed agent as the owner's acceptance policy. This is a minimum
execution requirement, not a claim about the bundled security command's full
agent count. Every agent must have structured `status: completed` output.
An asynchronous launch acknowledgement cannot satisfy the gate, including when
the call has no explicit background flag. Fix has no agent requirement. This
checks execution completeness; it does not establish the quality or full
semantic coverage of a review. A hosted receipt from each phase remains required.
Codex review results are independently required on the same live SHA.

All action invocations write the same filename. Validation therefore runs
immediately after each action, before the next can overwrite its evidence.
The validator emits categories rather than transcript bodies. Access denial
rules, protected checks, coverage floor and resolver are kept. Review explicitly
allows the native skills' Agent, Skill, Read, Glob, Grep and bounded read commands and asks Claude
to wait for completed agents. Access deny rules still apply; no unrestricted
shell or editing capability is added to Review.

Read-only validation embeds the reviewed helper in the workflow, with exact
source parity tests. This permits initial workflow bootstrap before the helper
exists on main. Repair validation reads the event's immutable base SHA with
`git show`, never the candidate helper. The review guard first requires the base
branch to be `main`, before any Git call or secret-bearing action: immutability
alone would not make an unprotected feature branch a trusted source.
Python isolated mode (`-I`) prevents a
candidate module or `PYTHONPATH` from replacing a standard-library import.
Both checks retain shell pipe failure propagation if the trusted file is absent.

Every ready same-repository head targeting main requires both reviews,
including Claude and Dependabot heads and workflow changes. Security review is
attempted even if code review fails. Workflow changes disable automatic repair
only. Neither the direct merge gate nor the protected resolver accepts skipped
reviews for any author. Existing hold checks remain enforced.

Both Claude checkouts use `persist-credentials: false`. Checkout v7 otherwise
leaves the workflow token in `includeIf`, while the pinned action removes only
`include.path` entries before configuring its existing App token. An actual
App-authenticated push and automatic successor Pipeline remain hosted acceptance
checks; repository approval policy is unchanged.

This is a Cortex extension of the generated pipeline. The existing generated
source SHA remains in its header; the adjacent extension marker identifies
the additional behavior so regeneration cannot silently claim exact parity.

Native Cortex settings enable automatic exhaustive code review and security
review for all PRs on every push. `ci_codex_reviews.py` authenticates the native
bot's canonical summary and validates both current-head completion records.
Missing, stale, malformed, failed or unresolved evidence cannot pass merge.
Resolved findings may pass; finding flags must be typed and consistent.
The pre-Fix gate requires completion and allows real findings to reach repair.
The merge gate requires both reviews to have no unresolved findings. A YAML
anchor shares one embedded reader between the gates, with exact file parity
and malicious candidate-import regression tests.

`Codex.yml` receives native bot completion events and completed
Pipeline failures. It executes only trusted main code with Actions write
permission, never a candidate checkout or an event-body command. The coordinator
rechecks server-side PR, run, attempt, jobs and review evidence before requesting
the exact waiting job's rerun. Pending evidence, unrelated test/review failures,
held or moved heads, cancellation and approval-required runs are left blocked.
There are no review-trigger comments, polling loops or automatic approvals.
Actual four-review receipts from a single ordinary push remain the acceptance
test; local unit tests do not establish hosted behavior.

Dependabot remains a hosted acceptance gap: its PR events cannot read Actions
secrets, and this repository currently has no Dependabot secrets. Removing the
old skipped-review exception makes missing credentials block integration; it
does not grant secret access. A trusted event path using existing credentials
is being evaluated. No token is copied or extracted and no approval policy is
weakened to address this restriction.

Sources at the pinned official action commit:

- [Output contract](https://github.com/anthropics/claude-code-action/blob/aa8a7738e48bf30a40ee499ce818bef081c5ab5e/action.yml)
- [Raw execution writer](https://github.com/anthropics/claude-code-action/blob/aa8a7738e48bf30a40ee499ce818bef081c5ab5e/base-action/src/execution-file.ts)
- [SDK success predicate](https://github.com/anthropics/claude-code-action/blob/aa8a7738e48bf30a40ee499ce818bef081c5ab5e/base-action/src/run-claude-sdk.ts)
- [Agent completion versus background launch](https://code.claude.com/docs/en/agent-sdk/subagents#choose-whether-claude-waits-for-subagents)
- [Incident run](https://github.com/cdeust/Cortex/actions/runs/40200974594/attempts/2)
- [Codex review summary](https://github.com/cdeust/Cortex/pull/796#issuecomment-6398685131)
- [Native Codex security automation](https://learn.chatgpt.com/docs/security/security-review)
- [Workflow YAML anchors](https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations)
- [Rerun a job and its dependents](https://docs.github.com/en/rest/actions/workflow-runs#re-run-a-job-from-a-workflow-run)
- [Dependabot event secret restrictions](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-on-actions)
