# Issue #685: named degradation failures

Approved request: "Named degrade paths in remember, sqlite search and
rebuild_profiles report only to an unread counter".
The approved comment adds hot-memory reads in query_methodology.

Inspected base: `3f4ffb822b50938732766cde0a566c6e1f0bca19`.

| Reference | Exact implementation | Decision |
| --- | --- | --- |
| Dedup failure becomes create | remember_helpers.try_curation | Record and re-raise the original exception. |
| SQLite dedup dependency | SqliteSearchMixin.search_vectors | Propagate query failures so try_curation can see them. |
| FTS signal disappears | SqliteSearchMixin._signal_fts | Record and re-raise before fusion returns partial rankings. |
| Vector signal disappears | SqliteRecallSignalsMixin._signal_vector | Already propagates on this base (ADR-1109); retain and test. |
| Freshness failure becomes rebuild | rebuild_profiles._check_skip | Record and re-raise before discovery or saving. |
| Hot-memory read becomes empty list | query_methodology._get_hot_memories | Remove the exception-to-empty boundary; instrument re-raises. |
| Unread counters | silent_failure.status | Read last, through doctor's shared backend check lists. |

The symptom is successful-looking results after a dependency failed.
The goal is a visible error at each named boundary and readable diagnostics.
Other fallback families, ranking algorithms, profile accumulation policy, and
telemetry persistence are outside this revision. PR #697 already implements
accumulated-profile preservation; PR #698 implements chain-head read defaults.
Neither removes the named freshness or hot-memory read catch on this base.

Execution strategy: context engineering binds the sites to fetched source;
verification uses external static tools and hosted execution.
No candidate source was checked out, saved locally, imported, or executed.

## Gates and current evidence

Trusted local text checks on the final Python payload:
nine files parsed by Python's AST parser, formatted with Ruff through stdin,
and checked with Ruff's repository-selected lint rules through stdin.
All nine lint invocations returned zero. These are static checks.

Hosted execution must establish:
- Dedup search/merge errors raise rather than authorize a new row.
- A real missing SQLite vector table reaches dedup's caller.
- A real missing FTS table reaches recall's caller.
- An injected vector-signal error reaches recall's caller.
- Unreadable profiles and invalid freshness timestamps stop before scan/save.
- Hot-memory reads raise through the public handler across selection paths.
- Doctor prints recorded failures and returns nonzero.
- check_setup exposes component/count/last-error and is not ready.

Tests:
`tests_py/handlers/test_named_degrade_paths_685.py`,
`tests_py/infrastructure/test_sqlite_signal_failures_685.py`,
`tests_py/test_doctor_recorded_failures_685.py`.

No pytest, benchmark, or fail-before execution result is claimed here.
The PR's GitHub-hosted Pipeline runs the unit command from ci.json, including
these regression tests. The coordinator owns subsequent results and native
review events. Before/after hosted regression evidence remains to be collected;
the vector failure and unreadable-profile cases also protect behavior already
correct on the inspected base.

The diagnostic counter is process-local and records historical failures during
that process lifetime. A separate doctor process cannot inspect another MCP
process's counters. Reading diagnostics does not clear the counters or invent
a recovery verdict.
