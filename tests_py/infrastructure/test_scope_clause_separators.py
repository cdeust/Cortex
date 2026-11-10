"""The SQL project scope compares the same normalized paths as Python (#692).

``memory_matches_project`` (ADR-1080) normalizes both the stored
``directory_context`` and the session root: backslashes become slashes and a
trailing separator is dropped. The SQL predicates compared that normalized
ancestor list with the raw column, so a memory recorded on Windows
(``C:\\work\\repo``) matched no session in SQL while Python accepted it: the
Windows measurement saw file priming leave such rows at heat 0.5
(run 38008915302, ``test_file_priming_aliases``). These tests write the
Windows spelling on any platform, so Linux CI covers the defect.

source: ADR-1080
source: ADR-1086
"""

import pytest

from mcp_server.infrastructure.file_memory_priming import prime_file_memories
from mcp_server.infrastructure.memory_store import get_shared_store
from mcp_server.shared.project_scope import memory_matches_project, project_ancestors
from tests_py.infrastructure.test_file_memory_priming import _insert, _rows

_ROOT = "C:\\work\\repo"

_STORED = [
    _ROOT,
    _ROOT + "\\",
    "C:/work/repo",
    "C:\\work",
]


@pytest.mark.parametrize("stored", _STORED)
def test_priming_scope_accepts_what_the_python_rule_accepts(stored):
    assert memory_matches_project(stored, False, _ROOT)
    store = get_shared_store()
    local = _insert(store, "cue.py", directory=stored)
    foreign = _insert(store, "cue.py", directory="C:\\work\\other")
    # The cue path uses "/" so Path.name finds "cue.py" on every platform.
    assert prime_file_memories(store, ["C:/work/repo/cue.py"], _ROOT, 0.1) == 1
    rows = _rows(store)
    assert rows[local]["heat_base"] == pytest.approx(0.6)
    assert rows[foreign]["heat_base"] == 0.5


@pytest.mark.parametrize("stored", _STORED)
def test_hot_memories_scope_accepts_what_the_python_rule_accepts(stored):
    store = get_shared_store()
    local = _insert(store, "hot", directory=stored)
    _insert(store, "hot", directory="C:\\work\\other")
    hot = store.get_hot_memories(
        min_heat=0.0, directory_ancestors=project_ancestors(_ROOT)
    )
    assert [m["id"] for m in hot] == [local]


def test_no_query_compares_the_raw_directory_column():
    """The hooks' PostgreSQL queries cannot run here without pgvector; this
    pins that every scope predicate goes through the normalized expression."""
    import re
    from pathlib import Path

    raw = re.compile(r"directory_context\s*(?:=\s*ANY|IN\s*\()")
    root = Path(__file__).resolve().parents[2] / "mcp_server"
    found = [
        str(path.relative_to(root))
        for path in sorted(root.rglob("*.py"))
        if raw.search(path.read_text(encoding="utf-8"))
    ]
    assert found == []
