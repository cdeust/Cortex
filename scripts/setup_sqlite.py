"""SQLite interpreter preflight before dependency installation (issue #691)."""

from collections.abc import Callable


def check_sqlite_extension_loading(fail: Callable[[str], None]) -> None:
    """Reject an interpreter without the SQLite vector capability before install.

    source: issue #691; CPython sqlite3 docs, enable_load_extension.
    """
    import sqlite3  # noqa: PLC0415 — stdlib preflight, before dependency installation

    if not hasattr(sqlite3.Connection, "enable_load_extension"):
        fail(
            "SQLite vector search requires sqlite3.Connection.enable_load_extension; "
            "this Python was built without loadable SQLite extensions. "
            "Use Homebrew Python or a uv-managed Python with extension loading "
            "enabled, then rerun setup with that interpreter."
        )
