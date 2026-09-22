"""Fixtures pytest injects by name across tests_py/scripts — issue #621.

``launcher_site`` is re-exported here rather than imported in each test
module: importing a fixture by name into a test module makes that name a
module-level binding, and every test function that then takes
``launcher_site`` as a parameter reads as a redefinition of it (ruff
F811). Discovery through conftest has no such collision.
"""

from __future__ import annotations

from tests_py.scripts._launcher_site_fixture import launcher_site  # noqa: F401 — re-exported for pytest's fixture discovery

__all__ = ["launcher_site"]
