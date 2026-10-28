# Autopilot owner attribution and native review reconciliation

Base: Cortex main a928391654d045509ae7b23fdf080dbf92301009 (PR815).
Scope: local dispatcher, issue intake, trusted runtime installation and tests.
No installed runtime, launchd service, user terminal or control worktree changed.

## Security evidence

Original ci_autopilot_issues.authorize accepted both an owner-authored approval
and owner-authored requirements after a foreign user's edit. The reproducer used
the original string-owner interface and printed FORGED_ROW_ACCEPTED=True for
both cases. New tests reject these same rows using the repository owner's
immutable User identity and same-response editor metadata. Valid pristine and
owner-edited rows remain accepted. Missing relevant metadata, a conflicting ID,
another editor, and malformed timestamps are rejected. Explicit null authors on
unrelated deleted-user discussion do not wake or block an owner issue.

GraphQL issue and comment pagination stays explicit and preserves editor fields;
partial errors, duplicate comment IDs, missing pages, repeated cursors and changed
issue revisions fail closed. External issue approval remains bound to the exact
snapshot digest. No bot comment was edited or fabricated.

## Reconciliation evidence

New local scheduling tests demonstrate review-only waits, no model while pending,
no duplicate identical repair, preserved accepted retained terminals and continued
processing of later work after an unverifiable PR. Known evidence failures become
an observable per-PR wait; programming errors remain visible.

Integration tests use the real authenticated reader, event coordinator and job
policy from PR815. Only external GitHub API/POST boundaries are mocked. Clean
current proof reruns exactly the waiting merge job. A human-edited bot summary
cannot rerun or repair. An exact readiness failure reruns the existing review job;
a completed non-readiness review toolchain failure can enter repair only with
clean current proof, green prerequisites and unchanged head/run/proof rereads.
Missing review completion, a running workflow or an unrelated build failure does
not request review infrastructure repair.

The real installer copy is exercised in an automatically removed temporary
directory. Every native dependency hash matches its copied bytes; Python -I -B
imports the copied dispatcher, event and comments modules without candidate code.
No model or live workflow rerun occurred in these tests.

## Verification

- Python 3.14 standard-library CI suites: 267 tests passed, including 58 autopilot
  tests and 119 native Codex tests (python3 -B -m unittest discover -s
  tests_py/scripts -p 'test_ci_*.py' -q; 8.79 seconds).
- ruff check and format checks on every changed Python file.
- Actual scripts/check_craftsmanship.py, including new files: clean 300/40 caps.
- git diff --check: clean.
- Exact production GraphQL query verified against public Cortex with one-node
  pages: owner User identity and issue/comment editor metadata present. No bodies
  or credentials were printed.

The full Cortex application suite is delegated to the combined PR's hosted CI.
The local service remains one repository/one durable active dispatch. Installation
and reactivation require reconciliation of the existing accepted PR776 dispatch
and a fresh dedicated coordinator identity, preserving the retained terminal.
