"""Isolate `shared.domain_mapping`'s dev-root scan from the real filesystem.

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

source: ADR-0882"""

from __future__ import annotations


def isolate_dev_root_scan() -> None:
    """Permanently replace `_candidate_dev_roots` with an empty-list stub
    for the whole test session (see module docstring for why)."""
    from mcp_server.shared import domain_mapping as dm

    dm._candidate_dev_roots = lambda: []
    dm._build_registry.cache_clear()
