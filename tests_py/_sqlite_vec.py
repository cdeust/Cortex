"""Capability gate for real vector tests (issue #691).

source: https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.enable_load_extension
"""

import sqlite3

import pytest


def require_sqlite_vec() -> None:
    """Skip a missing capability; leave an unexpected load failure visible."""
    if not hasattr(sqlite3.Connection, "enable_load_extension"):
        pytest.skip(
            "sqlite-vec requires sqlite3.Connection.enable_load_extension; "
            "use Homebrew or uv-managed Python built with loadable extensions"
        )
    pytest.importorskip("sqlite_vec", reason="sqlite-vec package is required")
