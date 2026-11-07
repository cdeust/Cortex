"""AST detector for every primitive that can persist bytes from mcp_server/.

Shared by the storage-gate architecture tests (ADR-1110). A *primitive* is a
call that creates or writes a file, opens a database connection, runs a SQL
script, or hands a child process a file to write into. Each finding is
``(relative_path, line, kind)``.

Calls are classified by *qualified* name: imports and their aliases are
resolved per module (``import sqlite3 as s`` makes ``s.connect`` resolve to
``sqlite3.connect``), ``getattr(module, "name")`` resolves like an attribute,
and ``importlib.import_module("x")`` / ``__import__("x")`` resolve to ``x``.
A mode or flag the detector cannot read as a constant counts as writing. The
runtime guarantee is structural (``infrastructure/db_connect.py`` builds only
gated connections, ``shared/gated_files.py`` is the only writer); this
detector is the backstop that fails when new code steps around them.

source: ADR-1110"""

from __future__ import annotations

import ast
import builtins
from pathlib import Path
from typing import Iterator

MCP_SERVER_ROOT = Path(__file__).resolve().parents[2] / "mcp_server"

_WRITE_MODE_CHARS = set("wax+")
_OS_WRITE_FLAGS = {"O_WRONLY", "O_RDWR", "O_CREAT", "O_APPEND", "O_TRUNC"}
_GATED_WRITER = "mcp_server.shared.gated_files."
_UNKNOWN = "?"
# qualified name -> position of the mode argument and its default
_MODE_OPENERS = {
    "builtins.open": (1, "r"),
    "io.open": (1, "r"),
    "codecs.open": (1, "r"),
    "os.fdopen": (1, "r"),
    "gzip.open": (1, "rb"),
    "bz2.open": (1, "rb"),
    "lzma.open": (1, "rb"),
    "tarfile.open": (1, "r"),
    "zipfile.ZipFile": (1, "r"),
}
_DB_MODULES = ("sqlite3", "psycopg", "psycopg2", "psycopg_pool", "apsw")
_DB_CONSTRUCTORS = {"connect", "Connection", "ConnectionPool", "AsyncConnectionPool"}
_KV_STORES = {
    "shelve.open",
    "shelve.Shelf",
    "dbm.open",
    "dbm.gnu.open",
    "dbm.ndbm.open",
}
_ARRAY_DUMPS = {"numpy.save", "numpy.savez", "numpy.savez_compressed", "numpy.savetxt"}
_FILE_HANDLERS = {
    "FileHandler",
    "RotatingFileHandler",
    "TimedRotatingFileHandler",
    "WatchedFileHandler",
}
_TEMPFILES = {"mkstemp", "NamedTemporaryFile", "TemporaryFile", "SpooledTemporaryFile"}
_COPIES = {"copy", "copy2", "copyfile", "copytree", "copyfileobj", "move"}
_CHILD_RUNNERS = {"Popen", "run", "call", "check_call", "check_output"}
_CHILD_STD_OK = {"DEVNULL", "PIPE", "STDOUT", "None"}
_DYNAMIC_IMPORTERS = {"importlib.import_module", "builtins.__import__"}


def import_aliases(tree: ast.AST) -> dict[str, str]:
    """Local name -> fully qualified name, for every import in the module."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    aliases[a.asname] = a.name
                else:
                    head = a.name.split(".")[0]
                    aliases[head] = head
        elif isinstance(node, ast.ImportFrom) and node.module:
            for a in node.names:
                aliases[a.asname or a.name] = f"{node.module}.{a.name}"
    return aliases


def _const_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def qualify(node: ast.AST, aliases: dict[str, str]) -> str:
    """Dotted qualified name of an expression; ``?`` marks an unknown part."""
    if isinstance(node, ast.Name):
        if node.id in aliases:
            return aliases[node.id]
        return (
            f"builtins.{node.id}"
            if hasattr(builtins, node.id)
            else f"{_UNKNOWN}.{node.id}"
        )
    if isinstance(node, ast.Attribute):
        return f"{qualify(node.value, aliases)}.{node.attr}"
    if isinstance(node, ast.Subscript):  # psycopg.Connection[DictRow].connect
        return qualify(node.value, aliases)
    if isinstance(node, ast.Call):
        return _qualify_call(node, aliases)
    return _UNKNOWN


def _qualify_call(node: ast.Call, aliases: dict[str, str]) -> str:
    func = qualify(node.func, aliases)
    first = _const_str(node.args[0]) if node.args else None
    if func in _DYNAMIC_IMPORTERS:
        return first or _UNKNOWN
    if func == "builtins.getattr" and len(node.args) >= 2:
        attr = _const_str(node.args[1]) or "<dynamic>"
        return f"{qualify(node.args[0], aliases)}.{attr}"
    return f"{func}()"


def _mode_is_write(node: ast.Call, position: int, default: str) -> bool:
    mode_node = next((kw.value for kw in node.keywords if kw.arg == "mode"), None)
    if mode_node is None and len(node.args) > position:
        mode_node = node.args[position]
    if mode_node is None:
        return bool(set(default) & _WRITE_MODE_CHARS)
    mode = _const_str(mode_node)
    return mode is None or bool(set(mode) & _WRITE_MODE_CHARS)


def _os_open_kind(node: ast.Call) -> str | None:
    # read-only only when the flags are spelled out and none can write;
    # flags held in a variable count as writing
    flags = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
    read_only = "O_RDONLY" in flags and not flags & _OS_WRITE_FLAGS
    return None if read_only else "os.open-write"


def _open_kind(node: ast.Call, name: str) -> str | None:
    if name == "os.open":
        return _os_open_kind(node)
    if name in _MODE_OPENERS:
        position, default = _MODE_OPENERS[name]
        return "open-write" if _mode_is_write(node, position, default) else None
    if name.endswith(".open") and name.split(".")[0] in {_UNKNOWN, "pathlib"}:
        # Path.open and any open method on an unresolved receiver
        return "open-write" if _mode_is_write(node, 0, "r") else None
    return None


def _tail(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    return node.attr if isinstance(node, ast.Attribute) else ""


def _child_stdio_kind(node: ast.Call, name: str) -> str | None:
    if name.rsplit(".", 1)[-1] not in _CHILD_RUNNERS:
        return None
    for kw in node.keywords:
        if kw.arg not in {"stdout", "stderr"}:
            continue
        if isinstance(kw.value, ast.Constant) and kw.value.value is None:
            continue
        if _tail(kw.value) not in _CHILD_STD_OK:
            return "child-stdio-file"
    return None


def _is_db_connect(name: str) -> bool:
    parts = name.split(".")
    return parts[0] in _DB_MODULES and (
        parts[-1] in _DB_CONSTRUCTORS or parts[-1] == "<dynamic>"
    )


def _named_kind(name: str) -> str | None:
    last = name.rsplit(".", 1)[-1]
    if last in {"write_text", "write_bytes"}:
        return None if name.startswith(_GATED_WRITER) else last
    if _is_db_connect(name):
        return "db-connect"
    if last == "executescript":
        return "sql-script"
    if name in _KV_STORES:
        return "kv-store"
    if name in _ARRAY_DUMPS or last == "tofile":
        return "array-dump"
    if last in _FILE_HANDLERS:
        return "log-file-handler"
    if last in _TEMPFILES and name.split(".")[0] in {"tempfile", _UNKNOWN}:
        return "tempfile"
    if last in _COPIES and name.startswith("shutil."):
        return "shutil-copy"
    return None


def classify(node: ast.Call, aliases: dict[str, str] | None = None) -> str | None:
    """Return the primitive kind of ``node``, or None when it writes nothing."""
    name = qualify(node.func, aliases or {})
    return _named_kind(name) or _open_kind(node, name) or _child_stdio_kind(node, name)


def kinds_in(source: str) -> list[str]:
    """Primitive kinds of every call in a module's source text."""
    tree = ast.parse(source)
    aliases = import_aliases(tree)
    return [
        kind
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and (kind := classify(node, aliases))
    ]


def scan_file(path: Path) -> Iterator[tuple[str, int, str]]:
    rel = path.relative_to(MCP_SERVER_ROOT).as_posix()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    aliases = import_aliases(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            kind = classify(node, aliases)
            if kind is not None:
                yield rel, node.lineno, kind


def scan_tree() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for path in sorted(MCP_SERVER_ROOT.rglob("*.py")):
        found.extend(scan_file(path))
    return found
