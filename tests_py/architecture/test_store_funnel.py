"""Every database access goes through the store (ADR-1112 increment 2).

Outside ``mcp_server/infrastructure/`` no module holds a connection: it may
not reach a store's connection or pools, nor import the PostgreSQL driver,
and every function it hands to ``store.call`` / ``store.call_batch`` must be
a marked store operation (the only names the broker will resolve). Static
scan of the source tree plus an import of each named operation.

The diagnostics that must work when the store does not (``doctor*``) and the
migration probe keep their own short connections; they are listed here with
the reason, and the broker increments revisit them.

source: ADR-1112
"""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

from mcp_server.infrastructure.store_operations import is_store_operation

_ROOT = Path(__file__).resolve().parents[2] / "mcp_server"
# source: ADR-1112 (diagnostics and the migrate probe reach PostgreSQL directly)
_DRIVER_ALLOWED = {
    "doctor.py": "diagnoses the server even when no store can open",
    "doctor_mcp.py": "same diagnostics behind the check_setup tool",
    "doctor_pgvector.py": "probes the extension the store depends on",
    "migrate.py": "connectivity probe of the explicit migration step",
}
# source: ADR-1112 (store internals that only infrastructure may touch)
_CONNECTION_ACCESS = re.compile(
    r"\._conn\b|\.acquire_batch\(|\.acquire_interactive\(|\.batch_pool\b"
    r"|\.interactive_pool\b|\._execute\(|\._execute_on_conn\("
)


def _outside_infrastructure(root: Path = _ROOT) -> list[Path]:
    infra = root / "infrastructure"
    return [p for p in root.rglob("*.py") if infra not in p.parents]


def _code_lines(path: Path) -> list[tuple[int, str]]:
    """Source lines without comments or docstrings (they may name pools)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr):
            value = body[0].value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                skip.update(range(body[0].lineno, body[0].end_lineno + 1))
    lines = path.read_text(encoding="utf-8").splitlines()
    return [
        (i, line.split("#", 1)[0]) for i, line in enumerate(lines, 1) if i not in skip
    ]


def connection_offenders(root: Path = _ROOT) -> list[str]:
    """``path:line`` of every store-internal access outside infrastructure."""
    return [
        f"{path.relative_to(root)}:{i}"
        for path in _outside_infrastructure(root)
        for i, line in _code_lines(path)
        if _CONNECTION_ACCESS.search(line)
    ]


def driver_importers(root: Path = _ROOT) -> set[str]:
    """Modules outside infrastructure that import the PostgreSQL driver."""
    importers = set()
    for path in _outside_infrastructure(root):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(n == "psycopg" or n.startswith("psycopg.") for n in names):
                importers.add(str(path.relative_to(root)))
    return importers


def test_no_module_outside_infrastructure_touches_a_connection():
    assert connection_offenders() == []


def test_only_listed_diagnostics_import_the_driver():
    importers = driver_importers()
    assert importers <= set(_DRIVER_ALLOWED), sorted(importers - set(_DRIVER_ALLOWED))


def _called_operations(path: Path) -> list[tuple[str, int]]:
    """(name, line) of the first argument of every ``.call``/``.call_batch``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"call", "call_batch"}
            and node.args
            and isinstance(node.args[0], ast.Name)
        ):
            found.append((node.args[0].id, node.lineno))
    return found


def test_every_operation_handed_to_the_store_is_marked():
    unmarked = []
    for path in _ROOT.rglob("*.py"):
        calls = _called_operations(path)
        if not calls:
            continue
        module = ".".join(path.relative_to(_ROOT.parent).with_suffix("").parts)
        namespace = vars(importlib.import_module(module))
        for name, line in calls:
            fn = namespace.get(name)
            if fn is None or not callable(fn):
                continue  # a parameter or local, not a module-level operation
            if not is_store_operation(fn):
                unmarked.append(f"{path.relative_to(_ROOT)}:{line} {name}")
    assert unmarked == []


def test_no_lower_layer_builds_a_shared_store():
    """The store broker runs infrastructure and core code; if any of it built
    a store through the factory, the broker would connect to itself
    (ADR-1112 decision 1)."""
    builders = [
        f"{path.relative_to(_ROOT)}:{i}"
        for package in ("infrastructure", "core", "shared")
        for path in (_ROOT / package).rglob("*.py")
        if path.name != "memory_store.py"
        for i, line in _code_lines(path)
        if "get_shared_store(" in line
        or "MemoryStore("
        in line.replace("PgMemoryStore(", "").replace("SqliteMemoryStore(", "")
    ]
    assert builders == []


# source: ADR-1112 increment 6 (the broker holds the only per-process pools)
_STORE_BUILDERS = {
    "hooks/store_broker.py": "the broker: the one process that holds the pools",
    "infrastructure/memory_store.py": "the factory, with CORTEX_STORE_IN_PROCESS=1",
}


def test_only_the_broker_and_the_gated_factory_build_a_pg_store():
    """Per-process pools are gone: a PgMemoryStore (and with it the
    interactive and batch pools) exists only in the broker, or in a process
    that explicitly runs the store in process (the broker, the tests)."""
    builders = {
        str(path.relative_to(_ROOT))
        for path in _ROOT.rglob("*.py")
        for _, line in _code_lines(path)
        if "PgMemoryStore(" in line and "class PgMemoryStore(" not in line
    }
    assert builders == set(_STORE_BUILDERS), sorted(builders ^ set(_STORE_BUILDERS))
