"""No hook-event reader may bypass ``stdin_event`` (issue #664).

The guard is an AST predicate with its own negative tests: each pattern a
reader could use to get the locale-decoded text stream must make it fire.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
# Files whose only legitimate stdin use is the binary buffer (the reader
# itself, and the stdlib-only Codex intake that cannot import mcp_server).
BUFFER_READERS = {"stdin_event.py", "session_queue.py"}


def _stdin_names(tree: ast.AST) -> set[str]:
    """Names bound to ``sys`` or to ``sys.stdin`` by imports in ``tree``."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.asname or a.name for a in node.names if a.name == "sys"}
        if isinstance(node, ast.ImportFrom) and node.module == "sys":
            names |= {a.asname or a.name for a in node.names if a.name == "stdin"}
    return names


def _is_sys_stdin(node: ast.AST, names: set[str]) -> bool:
    """``sys.stdin`` / ``sys.__stdin__`` (any alias), or an imported ``stdin``."""
    if isinstance(node, ast.Attribute):
        return (
            node.attr in {"stdin", "__stdin__"}
            and isinstance(node.value, ast.Name)
            and node.value.id in names
        )
    return isinstance(node, ast.Name) and node.id in names and node.id != "sys"


def _stream_use_hits(tree: ast.AST, names: set[str], allow_buffer: bool) -> set[int]:
    """Uses of the text stream other than ``.isatty`` (and the permitted buffer)."""
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    allowed = {"isatty"} | ({"buffer"} if allow_buffer else set())
    hits: set[int] = set()
    for node in ast.walk(tree):
        if not _is_sys_stdin(node, names):
            continue
        installs = allow_buffer and isinstance(getattr(node, "ctx", None), ast.Store)
        parent = parents.get(node)
        if not installs and not (
            isinstance(parent, ast.Attribute) and parent.attr in allowed
        ):
            hits.add(node.lineno)
    return hits


def _import_hits(tree: ast.AST) -> set[int]:
    """``from sys import stdin`` and any ``fileinput`` import."""
    hits: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "sys":
            if any(a.name in {"stdin", "__stdin__"} for a in node.names):
                hits.add(node.lineno)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = [a.name for a in node.names] + [getattr(node, "module", "")]
            if "fileinput" in modules:
                hits.add(node.lineno)
    return hits


def _is_const(node: ast.AST | None, value: object) -> bool:
    return isinstance(node, ast.Constant) and node.value == value


def _call_hits(tree: ast.AST, names: set[str]) -> set[int]:
    """``input()``, ``open(0)``, ``os.read(0, ...)``, ``getattr(sys, "stdin")``."""
    hits: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        first = node.args[0] if node.args else None
        second = node.args[1] if len(node.args) > 1 else None
        func = node.func
        if isinstance(func, ast.Name):
            direct = func.id == "input" or (func.id == "open" and _is_const(first, 0))
            via_getattr = (
                func.id == "getattr"
                and isinstance(first, ast.Name)
                and first.id in names
                and (_is_const(second, "stdin") or _is_const(second, "__stdin__"))
            )
            if direct or via_getattr:
                hits.add(node.lineno)
        if isinstance(func, ast.Attribute) and func.attr == "read":
            if isinstance(func.value, ast.Name) and func.value.id == "os":
                if _is_const(first, 0):
                    hits.add(node.lineno)
    return hits


def stdin_violations(source: str, allow_buffer: bool = False) -> list[int]:
    """Line numbers where ``source`` reaches stdin other than via the reader.

    Allowed: ``sys.stdin.isatty()`` (inspects the stream) and, when
    ``allow_buffer``, ``sys.stdin.buffer`` and assigning ``sys.stdin`` (the
    reader's own ``install_event_stdin``). Everything else is flagged, one
    predicate per bypass family: stream uses (``sys.stdin``, ``sys.__stdin__``,
    aliases), imports (``from sys import stdin``, ``fileinput``) and calls
    (``input()``, ``open(0)``, ``os.read(0, ...)``, ``getattr(sys, "stdin")``).
    """
    tree = ast.parse(source)
    names = _stdin_names(tree)
    hits = _stream_use_hits(tree, names, allow_buffer)
    return sorted(hits | _import_hits(tree) | _call_hits(tree, names))


def _guarded_files() -> list[Path]:
    hooks = (ROOT / "mcp_server" / "hooks").glob("*.py")
    launchers = (ROOT / "scripts").glob("launcher*.py")
    plugins = (ROOT / "plugins").glob("*/scripts/*.py")
    return sorted([*hooks, *launchers, *plugins])


def test_guard_covers_the_hook_event_readers() -> None:
    names = {path.name for path in _guarded_files()}
    assert {"entry.py", "launcher_capture.py", "session_queue.py"} <= names


def test_no_hook_event_reader_bypasses_the_stdin_reader() -> None:
    offenders = []
    for path in _guarded_files():
        source = path.read_text(encoding="utf-8")
        for line in stdin_violations(source, path.name in BUFFER_READERS):
            offenders.append(f"{path.relative_to(ROOT)}:{line}")
    assert offenders == []


@pytest.mark.parametrize(
    "source",
    [
        "import sys\nsys.stdin.read()\n",
        "import sys\nsys.stdin.readline()\n",
        "import sys, json\njson.load(sys.stdin)\n",
        "import sys\nfor line in sys.stdin:\n    pass\n",
        "import sys\nlines = iter(sys.stdin)\n",
        "from sys import stdin\n",
        "from sys import stdin as pipe\nprint(pipe.read())\n",
        "import sys as s\ns.stdin.read()\n",
        "import fileinput\n",
        "from fileinput import input as fi\n",
        "line = input()\n",
        "open(0).read()\n",
        "import sys\nsys.stdin = object()\n",
        'import sys\ndata = getattr(sys, "stdin").read()\n',
        "import sys\ndata = sys.__stdin__.read()\n",
        "import os\ndata = os.read(0, 4096)\n",
        "import sys\nsys.stdin.buffer.read()\n",
    ],
)
def test_guard_fires_on_every_bypass_pattern(source: str) -> None:
    assert stdin_violations(source) != []


def test_guard_allows_isatty_and_the_binary_buffer_where_permitted() -> None:
    assert stdin_violations("import sys\nsys.stdin.isatty()\n") == []
    buffer_read = "import sys\nsys.stdin.buffer.read()\n"
    assert stdin_violations(buffer_read, allow_buffer=True) == []
