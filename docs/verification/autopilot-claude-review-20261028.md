# Claude PR816 review follow-up

Source review: https://github.com/cdeust/Cortex/pull/816#issuecomment-6458968789
Base: 1b774076731547dfc76de48e366a6463c8e26c1e.
Scope: local autopilot issue attribution, repair classification and tests.
No installed runtime, model, launchd service or user terminal changed.

## Separate title attribution

The live GitHub schema describes Issue.editor as the actor who edited the
comment, and exposes RenamedTitleEvent actor/currentTitle separately. A read-only
query observed microsoft/vscode issue334398 with editor=null,lastEditedAt=null
and rename event RTE_lADOAn8RLM8AAAABPoAPuM8AAAAHKzvMsg at
2026-09-08T23:01:43Z. The event's currentTitle matched the issue title. Its actor
was the original author; no foreign-writer exploit was performed or claimed.

The original authorizer accepted a synthetic pristine owner issue with a valid
foreign-user rename event. The new title tests reject this case. Initial owner
titles and latest owner renames remain accepted. Missing/truncated history,
login/ID mismatch, null actors and a mismatched currentTitle fail closed.
Title-event evidence is returned with body metadata in every relevant query and
compared across comment pages.

Latest-event ordering was checked on anthropics/claude-code-action issue1445:
two recorded renames existed; first:1 did not match the current title and last:1
did. The exact new production GraphQL query was also verified read-only with
bounded one-node Cortex pages. No issue bodies or credentials were printed.

## One native rerun issuer

Only GitHub's workflow issues native gate reruns. The local helper no longer
calls event.resume or any POST endpoint. Integration tests run the real native
reader and policy: a ready merge or readiness gate waits with zero POST calls;
a genuine completed review toolchain failure can still request repair after
fresh run-ID, attempt, head and proof checks. Unknown/incomplete/running native
proof does not authorize a model.

The helper returns fixed diagnostic categories api, protocol, environment and
eligibility. Raw child stderr and arbitrary exception text are not forwarded.
Known evidence failures remain per-PR waits so other work can proceed; unrelated
programming errors continue to fail visibly.

## Verification

Focused regressions cover both comment identity-spoof directions, valid foreign
editors, author/editor/time/title drift between pages, exact pagination failure
causes, a truncated last page, EXPECTED_PR mismatch and all repair rechecks.
The installer test compares copied bytes and manifest hashes to independent
source-file hashes. Two actual installed Python -I helper processes exercise
environment rejection and an eligible read followed by closed-PR rejection;
their PATH contains no model tools. External GitHub I/O in the latter is a
bounded local fixture accepting only the expected GET, with no live writes.

Verification: 74 autopilot tests passed locally. The parent independently ran
the final combined CI suites: 301 tests passed in 8.386 seconds, including the
18 scheduled/CLI reconciliation tests. Ruff check/format, the actual Cortex
300-line/40-line craftsmanship gate and diff checks passed. Runtime installation
and default-branch hosted acceptance remain separate from these fixture results.
