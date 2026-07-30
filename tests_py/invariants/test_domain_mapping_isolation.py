"""Tests for tests_py/_domain_mapping_isolation.py (issue #276/#287
boy-scout follow-up — extracted from tests_py/conftest.py).

The function under test replaces `domain_mapping._candidate_dev_roots`
with a permanent empty-list stub for the whole session — see that module's
docstring for the incident (#196) this prevents. `conftest.py` already
calls it unconditionally at import time (which is what makes every other
test in the suite run isolated from the real filesystem); this file pins
the mechanism itself.
"""

from __future__ import annotations

from mcp_server.shared import domain_mapping as dm
from tests_py._domain_mapping_isolation import isolate_dev_root_scan


class TestIsolateDevRootScan:
    def test_replaces_candidate_dev_roots_with_an_empty_list(self) -> None:
        original = dm._candidate_dev_roots
        try:
            dm._candidate_dev_roots = lambda: ["/some/real/dev/root"]
            isolate_dev_root_scan()
            assert dm._candidate_dev_roots() == []
        finally:
            dm._candidate_dev_roots = original
            dm._build_registry.cache_clear()

    def test_clears_the_build_registry_cache(self) -> None:
        """A stale cached registry (built before the stub was installed)
        would still report the real dev roots' domains until cleared."""
        original = dm._candidate_dev_roots
        try:
            dm._candidate_dev_roots = lambda: []
            dm._build_registry()  # populate the cache with the stub in place
            assert dm._build_registry.cache_info().currsize == 1

            isolate_dev_root_scan()
            assert dm._build_registry.cache_info().currsize == 0
        finally:
            dm._candidate_dev_roots = original
            dm._build_registry.cache_clear()
