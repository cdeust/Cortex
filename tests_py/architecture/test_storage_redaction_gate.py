"""ADR-1110: no write path into storage bypasses the redaction gate.

Mechanical proof, by AST over every module of ``mcp_server/``:

1. every raw storage primitive (file creation or write, log file handler,
   temporary file, database connection, child process handed a file as
   stdout/stderr) sits in an audited site below, with the reason it cannot
   carry an unredacted secret; a new primitive anywhere fails the test;
2. database connections are constructed in one place,
   ``infrastructure/db_connect.py``, which only builds gated classes and
   refuses another factory; no module swaps a connection's cursor class, so a
   connection handed across a module boundary is gated wherever it goes;
3. every log file handler gets a ``RedactingFilter`` in the same function.

Runtime behaviour of each gate is pinned in
``tests_py/shared/test_redaction_gate_paths.py``.
"""

from __future__ import annotations

import ast
import collections
import sqlite3

import pytest

from tests_py.architecture._storage_primitives import MCP_SERVER_ROOT, scan_tree

# (path under mcp_server/, primitive kind) -> (count, reason)
_AUDITED = {
    ("shared/gated_files.py", "open-write"): (2, "the gate itself"),
    ("shared/gated_files.py", "write_text"): (
        1,
        "write_json calls the gated write_text",
    ),
    ("shared/gated_files.py", "os.open-write"): (1, "the gate's own temp file"),
    ("shared/private_paths.py", "os.open-write"): (
        3,
        "creates an empty 0600 file before SQLite or a log opens it; opens an "
        "entry O_RDONLY|O_NOFOLLOW to fchmod it (flags in a variable); "
        "open_lock_file, the one opener of every (empty) lock file",
    ),
    ("shared/log_rotation.py", "open-write"): (1, "yields only a RedactingStream"),
    ("infrastructure/log_relay.py", "child-stdio-file"): (
        1,
        "child stdout is the relay's stdin pipe; the relay writes via the gate",
    ),
    ("hooks/capture_worker_logging.py", "os.open-write"): (
        1,
        "pre-creates the worker log 0600, writes nothing",
    ),
    ("hooks/capture_worker_logging.py", "log-file-handler"): (
        1,
        "RedactingFilter attached (checked below)",
    ),
    ("infrastructure/pipeline_graph_ttl.py", "os.open-write"): (1, "empty lock file"),
    ("infrastructure/managed_pg.py", "os.open-write"): (
        3,
        "ADR-1114 cluster state: an empty lock file, the 0600 temp file of "
        "write_json (port, pid, state) and the supervisor log fd; no memory content",
    ),
    ("infrastructure/managed_pg.py", "open-write"): (
        1,
        "ADR-1114 write_json fills its 0600 temp file with cluster state "
        "(port, pid, state); no memory content",
    ),
    ("infrastructure/managed_pg.py", "child-stdio-file"): (
        1,
        "ADR-1114 supervisor stdout/stderr to its own 0600 log; supervisor "
        "lines carry no memory content",
    ),
    ("infrastructure/managed_pg_process.py", "os.open-write"): (
        1,
        "ADR-1114 empty lock file",
    ),
    ("infrastructure/managed_pg_server.py", "os.open-write"): (
        1,
        "ADR-1114 postgres server log fd, 0600 under the 0700 cluster root",
    ),
    ("infrastructure/managed_pg_server.py", "child-stdio-file"): (
        1,
        "ADR-1114 postgres server stdout/stderr to its 0600 log; follow-up: "
        "route through log_relay so statement text in errors is redacted",
    ),
    ("infrastructure/capture_socket.py", "os.open-write"): (1, "lease lock file"),
    ("infrastructure/pipeline_install_release.py", "write_bytes"): (
        1,
        "release tarball, sha256-verified binary, no user content",
    ),
    ("infrastructure/pipeline_install_rust.py", "tempfile"): (
        1,
        "download staging for a pinned toolchain, no user content",
    ),
    ("infrastructure/pipeline_install_release.py", "shutil-copy"): (
        1,
        "moves the sha256-verified binary into place, no user content",
    ),
    ("infrastructure/profile_store.py", "shutil-copy"): (
        1,
        "renames the existing private profiles file to its legacy backup",
    ),
    ("infrastructure/sqlite_gated_connection.py", "sql-script"): (
        2,
        "the gate: runs redact_script on the script, then the base class",
    ),
    ("infrastructure/sqlite_compat.py", "sql-script"): (
        1,
        "delegates to GatedConnection.executescript, which redacts the script",
    ),
    ("infrastructure/sqlite_connection_registry.py", "sql-script"): (
        1,
        "delegates to GatedConnection.executescript, which redacts the script",
    ),
    ("infrastructure/db_connect.py", "db-connect"): (
        3,
        "the one connection factory: sqlite3, psycopg and the pool, all gated",
    ),
}


_CURSOR_CLASS_ATTRS = {"cursor_factory", "server_cursor_factory", "<dynamic>"}
_CURSOR_CLASSES = {"Cursor", "ClientCursor", "ServerCursor", "RawCursor"}


def _assigned(node: ast.AST) -> list[ast.expr]:
    if isinstance(node, ast.Assign):
        return list(node.targets)
    if isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        return [node.target]
    return []


def _setattr_name(node: ast.AST) -> str:
    if not (isinstance(node, ast.Call) and _name_of(node.func) == "setattr"):
        return ""
    arg = node.args[1] if len(node.args) > 1 else None
    return arg.value if isinstance(arg, ast.Constant) else "<dynamic>"


def _name_of(node: ast.AST) -> str:
    return node.attr if isinstance(node, ast.Attribute) else getattr(node, "id", "")


def test_every_storage_primitive_is_an_audited_site():
    found = collections.Counter((path, kind) for path, _line, kind in scan_tree())
    expected = {key: count for key, (count, _r) in _AUDITED.items() if count}
    unexpected = {k: v for k, v in found.items() if expected.get(k) != v}
    missing = {k: v for k, v in expected.items() if found.get(k) != v}
    assert not unexpected and not missing, (
        "storage primitive outside the redaction gate (ADR-1110): route the "
        "write through mcp_server.shared.gated_files, or audit it here with a "
        f"reason.\nfound but not audited: {unexpected}\naudited but not "
        f"found: {missing}"
    )


def test_connections_come_only_from_the_gated_factory():
    """B1 of the PR #775 review: a hook opened its own psycopg connection,
    allowlisted as read-only, and passed it to a receipt writer. There is no
    ungated connection type left: db_connect is the only constructor, and it
    cannot be asked for another class."""
    from mcp_server.infrastructure import db_connect
    from mcp_server.infrastructure.sqlite_gated_connection import GatedConnection

    conn = db_connect.sqlite_connect(":memory:")
    try:
        assert isinstance(conn, GatedConnection)
    finally:
        conn.close()
    with pytest.raises(TypeError, match="always gated"):
        db_connect.sqlite_connect(":memory:", factory=sqlite3.Connection)
    with pytest.raises(TypeError, match="always gated"):
        db_connect.pg_connect("postgresql://unused", cursor_factory=object)


def test_no_module_swaps_the_cursor_class_of_a_connection():
    allowed = {"infrastructure/pg_gated_cursor.py", "infrastructure/db_connect.py"}
    offenders = []
    for path in sorted(MCP_SERVER_ROOT.rglob("*.py")):
        rel = path.relative_to(MCP_SERVER_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            swaps = (
                any(
                    isinstance(t, ast.Attribute) and t.attr in _CURSOR_CLASS_ATTRS
                    for t in _assigned(node)
                )
                or _setattr_name(node) in _CURSOR_CLASS_ATTRS
            )
            builds = (
                isinstance(node, ast.Call) and _name_of(node.func) in _CURSOR_CLASSES
            )
            if (swaps or builds) and rel not in allowed:
                offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, offenders


def test_every_log_file_handler_is_filtered_in_the_same_function():
    handler_files = {p for p, _l, kind in scan_tree() if kind == "log-file-handler"}
    for path in handler_files:
        tree = ast.parse((MCP_SERVER_ROOT / path).read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
            attrs = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
            if "RotatingFileHandler" in names | attrs or "FileHandler" in names:
                assert "RedactingFilter" in names, f"{path}:{fn.name}"


# source: review of PR #775 (N1) — each evasion listed there, as a module
_EVASIONS = {
    "import sqlite3 as s\ns.connect(p)": "db-connect",
    "from sqlite3 import connect as c\nc(p)": "db-connect",
    "import psycopg as pg\npg.connect(u)": "db-connect",
    "import sqlite3\ngetattr(sqlite3, 'connect')(p)": "db-connect",
    "import importlib\nimportlib.import_module('sqlite3').connect(p)": "db-connect",
    "m = 'w'\nopen(p, m)": "open-write",
    "from pathlib import Path\nPath(p).open(mode)": "open-write",
    "gated_files = Path(p)\ngated_files.write_text(t)": "write_text",
    "import shelve\nshelve.open(p)": "kv-store",
    "import numpy as np\nnp.save(p, a)": "array-dump",
    "a.tofile(p)": "array-dump",
    "conn.executescript(sql)": "sql-script",
    "import gzip\ngzip.open(p, 'wt')": "open-write",
}


def test_scanner_detects_each_primitive_kind():
    """The proof is only as good as the detector: pin each kind on a sample."""
    from tests_py.architecture._storage_primitives import kinds_in

    samples = {
        "p.write_text(x)": "write_text",
        "open(p, 'a')": "open-write",
        "import os\nos.open(p, os.O_CREAT | os.O_WRONLY)": "os.open-write",
        "import os\nos.open(p, flags, 0o600)": "os.open-write",
        "import logging\nlogging.FileHandler(p)": "log-file-handler",
        "import tempfile\ntempfile.mkstemp()": "tempfile",
        "import sqlite3\nsqlite3.connect(p)": "db-connect",
        "import psycopg\npsycopg.Connection[R].connect(u)": "db-connect",
        "import subprocess\nsubprocess.Popen(c, stdout=log)": "child-stdio-file",
        "import shutil\nshutil.copyfile(a, b)": "shutil-copy",
        **_EVASIONS,
    }
    for source, kind in samples.items():
        assert kinds_in(source) == [kind], source
    for harmless in (
        "open(p)",
        "from mcp_server.shared import gated_files\ngated_files.write_text(p, t)",
        "import os\nos.open(p, os.O_RDONLY)",
        "from pathlib import Path\nPath(p).open()",
        "import subprocess\nsubprocess.run(c, stdout=subprocess.DEVNULL)",
    ):
        assert kinds_in(harmless) == [], harmless


def test_only_the_gate_marks_text_as_redacted():
    """RedactedText exempts a string from a second redaction in the same
    process; a module that built one could exempt text never redacted."""
    builders = []
    for path in sorted(MCP_SERVER_ROOT.rglob("*.py")):
        rel = path.relative_to(MCP_SERVER_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            named = isinstance(node, (ast.Name, ast.Attribute))
            if named and _name_of(node) == "RedactedText":
                builders.append(rel)
    assert set(builders) <= {"shared/redaction_gate.py"}, builders
