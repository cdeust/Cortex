"""Every script that reaches the memory store reads the backend marker first.

Issue #704 removed the default PostgreSQL URL, so a command that opens the
store without ``settle_for_command`` gets an empty SQLite store, silently,
when the marker selects PostgreSQL. PR #865 review 4 (B2) found three such
scripts that reach ``get_shared_store`` through a handler and were missed by
a list kept by hand. This test scans ``scripts/`` instead.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
_STORE_REACHING = re.compile(
    r"^\s*from mcp_server\.handlers|get_shared_store|MemoryStore\(", re.M
)
_SETTLE_EXEMPT = {
    # Refuses to start unless DATABASE_URL names its own nonexistent socket.
    "collect_response_budget_payloads.py",
    # Imports only handlers.wiki_rename, which edits wiki files, not the store.
    "wiki_bulk_migrate.py",
}


def test_every_script_reaching_the_store_settles_the_backend():
    missing = [
        path.name
        for path in sorted(_SCRIPTS.glob("*.py"))
        if path.name not in _SETTLE_EXEMPT
        and _STORE_REACHING.search(path.read_text())
        and "settle_for_command(" not in path.read_text()
    ]
    assert missing == []


@pytest.mark.parametrize("name", ["groomer", "cortex_ingest", "dev_run_ingest"])
def test_handler_driven_scripts_settle_before_main(name):
    """These reach get_shared_store through a handler, so the settle call
    guards the entry point, ahead of main()."""
    source = (_SCRIPTS / f"{name}.py").read_text()
    entry = source.index('if __name__ == "__main__":')
    settle = source.index(f'settle_for_command("{name}")', entry)
    assert settle < source.index("main()", settle)
