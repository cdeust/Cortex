# Codex parity review fixes

PR #631 review found that a cooldown key could combine distinct query scopes.
A read through a directory alias could suppress a subsequent read through the
real path. The fix uses the query's lexical project identity in the cooldown.
Existing file-path normalization remains in place.

Fresh Codex hook processes now use the MCP store factory to choose a backend
when no backend or database URL is configured. The selected backend is made
available to the hook's existing query path. Configured backends skip this
selection. Both PostgreSQL URL aliases remain explicit targets; an unavailable
explicit target raises an error unless the operator has opted into fallback.

## Completion ledger

| Changed path | Evidence |
|---|---|
| Distinct alias scopes, with first read matching or missing | `test_file_priming_aliases.py::test_alias_cooldowns_follow_queried_scope`, both path orders |
| Repeated read within the same scope | The same test asserts that the third read adds no heat |
| Fresh auto selection falls back to SQLite and delivers stored context | `test_entry.py::test_codex_auto_hook_uses_actual_sqlite_store_without_marker` |
| Auto selection retains PostgreSQL and its selected URL | `test_entry.py::test_codex_auto_hook_keeps_postgres_when_store_selects_it` |
| Actual console entry invokes auto selection | `test_entry.py::test_packaged_codex_entry_selects_sqlite_before_hook_wiring` |
| Explicit settings bypass auto selection | `test_entry_backend_parity.py::test_resolved_backend_skips_auto_store_probe` |
| Either explicit URL reaches hooks without silent fallback | `test_entry_backend_parity.py::test_explicit_postgres_target_never_falls_back_to_sqlite` |
| MCP namespaced URL remains an explicit target | `test_entry_backend_parity.py::test_mcp_namespaced_postgres_target_is_explicit` |
| Existing marker selection and operator fallback override | `test_backend_marker.py`, `test_shared_backend_bootstrap.py`, `test_sqlite_backend.py` |

The four mixed-alias cases fail if the resolved-path cooldown key is restored.
Removing the backend resolver call from the console entry causes its subprocess
regression to fail because the disposable SQLite store is not created. These
mutations test the changed behavior and the entry-point wiring.

The PostgreSQL-unavailable tests replace the connection boundary with a
deterministic failure. They use disposable SQLite files. They do not contact
the user's database. The briefing regression inserts a decision through the
shared store and asserts that the hook emits its content.

These checks exercise Python entry points and shared persistence. They do not
constitute a new native Codex or Claude application run. The prior native
artifact evidence in `codex-native-4.23.2.md` applies to its recorded revision.

## Validation on 2026-09-22

Python 3.13 local checks used disposable stores. The PostgreSQL selection ran
113 affected tests with no failures or skips. The SQLite selection ran all hook
tests plus the shared-store, backend and Codex contract suites: 773 passed,
18 skipped, and 13 subtests passed. Its two warnings came from the existing
fork-based consolidation shutdown tests. Ruff lint and formatting passed for
the repository; the repository craftsmanship gate passed against `origin/main`.

The launcher comparison initially failed with a copied Python 3.14 dependency
binary under the Python 3.13 runner. Replacing the isolated worktree copy with
matching pinned Python 3.13 dependencies made the unchanged comparisons pass.
The editable checkout pointer was excluded and the imported Cortex source path
was verified to be this worktree. No installed host configuration was changed.

The first CI run exposed a test fixture that left the backend set to SQLite
when it had originally been unset. The fixture now snapshots its environment
around the resolver and restores it before clearing cached settings. With the
backend unset, the affected hook and PostgreSQL persistence suites passed all
51 tests locally against a disposable database. The two entry-point suites
also passed all 27 tests with SQLite selected; sandboxed PostgreSQL discovery
emitted one availability warning in that run.
