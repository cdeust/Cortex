# Exact replay review corrections, 2026-10-28

Target: https://github.com/cdeust/Cortex/pull/827
Original head: 53261c9e21c15f02df8d6273283ca3881270442f.
Main synchronization parent: 8e1c131faa54347fce96b2a78d43b25aadd144c0.

## Before

Hosted unit job: https://github.com/cdeust/Cortex/actions/runs/40687846221/job/122814815963

```text
FAILED tests_py/handlers/test_memory_portability.py::test_a_secret_stored_before_the_gate_leaves_the_store_redacted[sqlite] - sqlite3.OperationalError: unknown function: md5()
FAILED tests_py/handlers/test_remember_supersede.py::TestRememberSupersedes::test_human_edit_never_lost_forced_duplicate - AssertionError: {'stored': False, 'action': 'rejected', 'reason': 'exact_duplicate', 'memory_id': 638}
2 failed, 11168 passed, 26 skipped, 2 warnings, 920 subtests passed in 784.30s
```

Native findings: https://github.com/cdeust/Cortex/pull/827#discussion_r4400573470
and https://github.com/cdeust/Cortex/pull/827#discussion_r4400573476.
The existing review discussion also identifies the full-table collapse lock,
correlated update, shared no-pool transaction, and tool-schema inconsistencies.

## Correction

- Replace SQLite's application-function expression index with a native content
  index; drop the old index during initialization, including on upgrades.
- Preserve explicit supersession, normalize preflight domain identity, exclude
  benchmark rows, and match replica tags with exact JSON membership.
- Keep no-pool PostgreSQL writes on owned connections and isolate advisory locks
  in the two-key namespace. Refuse nested SQLite writes without committing the caller.
- Join the ranked collapse result directly and probe for candidates before taking
  a write lock. PostgreSQL uses NOWAIT so conflicting writers produce a visible
  partial-maintenance failure instead of an unbounded lock wait.
- Refresh tool documentation and unchanged code-analysis/backfill metadata using
  the existing id returned for an exact replay. Document retained-copy erasure.
- Preserve main's supersession deletion repair and its tests through a two-parent merge.

The transaction choices follow the SQLite transaction documentation:
https://www.sqlite.org/lang_transaction.html.
The index restriction is documented at https://www.sqlite.org/expridx.html.
PostgreSQL lock behavior follows
https://www.postgresql.org/docs/current/sql-lock.html and the distinct advisory
key spaces in https://www.postgresql.org/docs/current/functions-admin.html#FUNCTIONS-ADVISORY-LOCKS.

## Verification

Candidate sources were handled as GitHub API text in memory. No candidate files,
dependencies, imports, tests, repository scripts, builds, or hooks ran on the Mac.
Trusted static checks used Python AST parsing and installed Ruff 0.15.20 with the
repository's selected rules and test-file exclusions. All 17 changed Python sources
parsed and passed that lint selection; changed sources were formatted through stdin.

Runtime acceptance remains hosted. The Exact replay regression evidence workflow
replays both old failures, records a clean single-process 100000-row collapse
measurement before and after, and runs final-head regression tests on both stores.
The final unit, regression, security and native review results are pending at publication.
No passing runtime, performance improvement, or complete-mutation claim is made here.
