# Reject blocked review executions

Cortex PR796, run40200974594 attempt2, review job121876760991 returned a
successful SDK result with one denied tool operation. Its rendered report
acknowledged a manual partial review in place of the native skill's agents.
The job passed and the protected resolver merged the PR. Independent Codex
code and security reviews subsequently completed without findings on the exact
head `5fa52b6711ffffe765800a3814871b68c98bb995`.

The review job now validates each action's raw SDK execution file. It rejects
missing or malformed evidence, failed execution, denied permissions and tool
errors. Review additionally requires a completed synchronous Agent or Task
call linked to its successful result. Fix has no agent requirement. This
checks execution completeness; it does not establish the quality or full
semantic coverage of a review. Codex review results remain separate evidence.

Both action invocations write the same filename. Validation therefore runs
immediately after each action, before the next can overwrite its evidence.
The validator emits categories rather than transcript bodies. Access denial
rules, allowed tools, protected checks, coverage floor and resolver are kept.

This is a Cortex extension of the generated pipeline. The existing generated
source SHA remains in its header; the adjacent extension marker identifies
the additional behavior so regeneration cannot silently claim exact parity.

Sources at the pinned official action commit:

- [Output contract](https://github.com/anthropics/claude-code-action/blob/aa8a7738e48bf30a40ee499ce818bef081c5ab5e/action.yml)
- [Raw execution writer](https://github.com/anthropics/claude-code-action/blob/aa8a7738e48bf30a40ee499ce818bef081c5ab5e/base-action/src/execution-file.ts)
- [SDK success predicate](https://github.com/anthropics/claude-code-action/blob/aa8a7738e48bf30a40ee499ce818bef081c5ab5e/base-action/src/run-claude-sdk.ts)
- [Incident run](https://github.com/cdeust/Cortex/actions/runs/40200974594/attempts/2)
- [Codex review summary](https://github.com/cdeust/Cortex/pull/796#issuecomment-6398685131)
