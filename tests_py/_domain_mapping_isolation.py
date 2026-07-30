"""Isolate `shared.domain_mapping`'s dev-root scan from the real filesystem.

Extracted from `tests_py/conftest.py` (issue #276/#287 boy-scout follow-up
— see `tests_py/_pg_throwaway_db.py`'s docstring for the size-cap
rationale this split serves). No behavior change: `conftest.py` calls
`isolate_dev_root_scan()` at the exact point in its module-level sequence
where this code used to run inline.

ROOT CAUSE (reproduced deterministically while measuring coverage for
issue #196, 2026-07-27): `shared/domain_mapping._build_registry()` (used
transitively by `handlers/consolidation/wiki_backlog_pass.py` ->
`core/wiki_drift.py`'s `audit_wiki_drift` -> `_project_source_root` ->
`_file_exists_under`'s `os.walk` fallback) has NO test override by
default. `_candidate_dev_roots()` falls back to `$HOME/Developments`,
`$HOME/Documents/Developments`, `$HOME/dev`, `$HOME/code` — real developer
directories — and (this is the part that defeats a naive fix) is
ADDITIVE: even with `$CORTEX_DEV_ROOT` set, every one of those defaults
that exists on disk is STILL appended as an extra candidate (see
`shared/domain_mapping.py::_candidate_dev_roots` — the env var is one more
candidate, not a replacement). Setting the env var alone does NOT isolate
the scan. On a machine where one of the defaults exists and holds real git
repos (any contributor's normal dev machine), any test that exercises the
full consolidate handler (e.g.
`test_consolidate_stage_exception_does_not_crash_siblings`) transitively
walks those REAL, unrelated, potentially enormous repo trees via
`os.walk` — observed killing a `pytest --cov` run at the 300s per-test
timeout (`pyproject.toml`'s `timeout = 300`). This is invisible in CI
because none of the candidate dev roots exist on a CI runner
(`$HOME=/home/runner`), so `_candidate_dev_roots()` returns `[]` there and
`_project_source_root` always returns `None` — CI's isolation is
accidental, not designed. This plausibly explains the previously
unexplained "CI stall on 148d5a1... hung >3h... no offender identified"
that same `timeout` setting was added to catch: a local run with a
populated dev root would reproduce this hang with no per-test timeout to
bound it.

Fix: replace `_candidate_dev_roots` itself (not just the env var) so it
always returns an empty list for the whole test session, matching the
exact isolation pattern `tests_py/shared/test_domain_mapping.py` already
uses per-test (monkeypatch `_candidate_dev_roots` directly, then
`_build_registry.cache_clear()`). Those dedicated tests monkeypatch this
same attribute again inside their own test body — monkeypatch always
restores to whatever was in place when the test started, so patching it
here at collection time (not via the `monkeypatch` fixture, which only
exists inside a running test) is a permanent module-level replacement for
the whole session; the per-test monkeypatch calls inside
`test_domain_mapping.py` override it for the duration of those specific
tests and their own `_build_registry.cache_clear()` calls put the real
cache state back in sync afterward.
"""

from __future__ import annotations


def isolate_dev_root_scan() -> None:
    """Permanently replace `_candidate_dev_roots` with an empty-list stub
    for the whole test session (see module docstring for why)."""
    from mcp_server.shared import domain_mapping as dm

    dm._candidate_dev_roots = lambda: []
    dm._build_registry.cache_clear()
