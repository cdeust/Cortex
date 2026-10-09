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


def stdin_violations(source: str, allow_buffer: bool = False) -> list[int]:
    """Line numbers where ``source`` reaches stdin other than via the reader.

    Allowed: ``sys.stdin.isatty()`` (inspects the stream) and, when
    ``allow_buffer``, ``sys.stdin.buffer`` and assigning ``sys.stdin`` (the
    reader's own ``install_event_stdin``). Everything else is flagged:
    any other use of ``sys.stdin`` (reads, iteration, ``json.load``,
    assignment), ``from sys import stdin``, aliases of either, ``fileinput``,
    ``input()`` and ``open(0)``.
    """
    tree = ast.parse(source)
    names = _stdin_names(tree)
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    hits: set[int] = set()
    for node in ast.walk(tree):
        is_stdin_attr = (
            isinstance(node, ast.Attribute)
            and node.attr == "stdin"
            and isinstance(node.value, ast.Name)
            and node.value.id in names
        )
        is_stdin_name = (
            isinstance(node, ast.Name) and node.id in names and node.id != "sys"
        )
        if is_stdin_attr or is_stdin_name:
            parent = parents.get(node)
            allowed = {"isatty"} | ({"buffer"} if allow_buffer else set())
            installs = allow_buffer and isinstance(node.ctx, ast.Store)
            if not installs and not (
                isinstance(parent, ast.Attribute) and parent.attr in allowed
            ):
                hits.add(node.lineno)
        if isinstance(node, ast.ImportFrom) and node.module == "sys":
            if any(a.name == "stdin" for a in node.names):
                hits.add(node.lineno)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = [a.name for a in node.names] + [getattr(node, "module", "")]
            if "fileinput" in modules:
                hits.add(node.lineno)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            first = node.args[0] if node.args else None
            if node.func.id == "input" or (
                node.func.id == "open"
                and isinstance(first, ast.Constant)
                and first.value == 0
            ):
                hits.add(node.lineno)
    return sorted(hits)


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
        "import sys\nsys.stdin.buffer.read()\n",
    ],
)
def test_guard_fires_on_every_bypass_pattern(source: str) -> None:
    assert stdin_violations(source) != []


def test_guard_allows_isatty_and_the_binary_buffer_where_permitted() -> None:
    assert stdin_violations("import sys\nsys.stdin.isatty()\n") == []
    buffer_read = "import sys\nsys.stdin.buffer.read()\n"
    assert stdin_violations(buffer_read, allow_buffer=True) == []
