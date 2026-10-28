"""Setup's managed-PostgreSQL step: install, initialise, start, prove, then select.

Run by the Setup hook (``launcher_setup``) after the base set is installed, so
psycopg is importable. In order, under the cluster root's install lock:

1. the pinned archives (``launcher_pg_assets``), sha256-verified, into the
   plugin's data (``<data>/pg/dist``);
2. a cluster, once, under ``~/.claude/methodology/managed-pg`` (next to the
   backend marker, so uninstalling the plugin never deletes memories):
   ``initdb --pwfile`` (the password never reaches argv), scram-sha-256,
   UTF8, C locale, TCP on 127.0.0.1 only, no unix socket;
3. the server, through the same supervisor every launch attaches to;
4. the ``cortex`` database, ``vector`` and ``pg_trgm``, pgvector's iterative
   scan, the schema (``setup_db._init_schema``: any failed statement fails);
5. only then ``provisioned.json`` and, for an eligible store, the ``managed``
   marker. A failure before that writes no selection: the store stays SQLite,
   and the cause is returned as the SQLite fallback Setup records (D3).

A configured database (``database_url`` or an explicit ``CORTEX_*`` backend)
wins before anything else, even over a ``managed`` marker: nothing managed
is installed or started (ADR-1114 §4a).

source: ADR-1114
source: ADR-1108
"""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import launcher_pg_assets
from mcp_server.infrastructure import managed_pg

_PASSWORD_BYTES = 24  # source: ADR-1114 (192 random bits)
# source: ADR-1114 (loopback TCP only; an empty list disables unix sockets,
# whose path limit the plugin data directory can exceed)
_SERVER_CONF = "\nlisten_addresses = '127.0.0.1'\nunix_socket_directories = ''\n"
_EXTENSIONS = ("vector", "pg_trgm")  # source: mcp_server/infrastructure/pg_schema.py


@dataclass(frozen=True)
class StepOutcome:
    """``failed``: the cause Setup must fail with; ``fallback``: why the store
    stays SQLite although it was eligible (recorded and shown, D3)."""

    failed: str = ""
    fallback: str = ""


def _password(paths: managed_pg.PgPaths) -> Path:
    if not paths.password.is_file():
        fd = os.open(paths.password, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(secrets.token_hex(_PASSWORD_BYTES) + "\n")
    return paths.password


def _initdb(paths: managed_pg.PgPaths, tree: Path) -> None:
    """Create the cluster once, atomically: a failed initdb leaves no cluster."""
    if (paths.cluster / "PG_VERSION").is_file():
        return
    scratch = paths.root / f".cluster-{os.getpid()}"
    shutil.rmtree(scratch, ignore_errors=True)
    done = subprocess.run(
        [str(tree / "bin" / "initdb"), "-D", str(scratch), "-U", managed_pg.USER,
         f"--pwfile={_password(paths)}", "--auth=scram-sha-256", "--encoding=UTF8",
         "--locale=C", "--no-instructions"],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False,
    )  # fmt: skip
    if done.returncode:
        shutil.rmtree(scratch, ignore_errors=True)
        output = f"{done.stdout}{done.stderr}".strip()
        raise managed_pg.ManagedPgError(f"initdb exited {done.returncode}: {output}")
    with (scratch / "postgresql.conf").open("a", encoding="utf-8") as conf:
        conf.write(_SERVER_CONF)
    shutil.rmtree(paths.cluster, ignore_errors=True)  # no PG_VERSION: not a cluster
    os.replace(scratch, paths.cluster)


def _prepare_database(url: str) -> None:
    """The ``cortex`` database, both extensions, pgvector's check, the schema."""
    import psycopg  # noqa: PLC0415 — in the base set, importable once Setup installed it
    import setup_db  # noqa: PLC0415 — sibling script, stdlib at import time
    from psycopg import sql  # noqa: PLC0415 — same dependency as above
    from psycopg.conninfo import make_conninfo  # noqa: PLC0415 — same dependency as above

    with psycopg.connect(
        make_conninfo(url, dbname="postgres"), autocommit=True
    ) as conn:
        found = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (managed_pg.DATABASE,)
        ).fetchone()
        if found is None:
            conn.execute(
                sql.SQL("CREATE DATABASE {}").format(
                    sql.Identifier(managed_pg.DATABASE)
                )
            )
    with psycopg.connect(url, autocommit=True) as conn:
        for name in _EXTENSIONS:
            conn.execute(
                sql.SQL("CREATE EXTENSION IF NOT EXISTS {}").format(
                    sql.Identifier(name)
                )
            )
        conn.execute(setup_db.ITERATIVE_SCAN_CHECK)
    ok, error = setup_db._init_schema(url)
    if not ok:
        raise managed_pg.ManagedPgError(f"schema initialization failed: {error}")


def provision(paths: managed_pg.PgPaths, dist: Path) -> None:
    """Install, initialise, start and prove the managed server; record it ready.

    Raises ``launcher_pg_assets.UnsupportedError`` on a host without a pinned
    archive, ``AssetError``/``ManagedPgError``/``OSError``/psycopg errors on any
    failure; ``provisioned.json`` is then left as it was.
    """
    target = launcher_pg_assets.host_triple()
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.root.chmod(0o700)
    install = managed_pg.open_lock(paths.lock("install"))
    try:
        managed_pg.flock(install, exclusive=True)  # one install at a time, any key
        tree = launcher_pg_assets.install(dist, target)
        _initdb(paths, tree)
        managed_pg.write_json(paths.installed, {"tree": str(tree), "target": target})
        try:
            _prepare_database(managed_pg.attach(paths, os.environ))
        finally:
            managed_pg.detach()
        record = {
            "state": "ready",
            "version": launcher_pg_assets.PG_VERSIONS[target],
            "target": target,
        }
        managed_pg.write_json(paths.provisioned, record)
    finally:
        os.close(install)


def _select(paths: managed_pg.PgPaths) -> str:
    """Write the ``managed`` marker unless a launch chose a store meanwhile.

    Eligibility is checked again here, right before the write: a first launch
    during provisioning writes its own marker (and may create the SQLite
    store), which must not be overwritten. Returns why nothing was written."""
    from mcp_server.infrastructure import backend_marker  # noqa: PLC0415 — resolvable once plugin_root is on sys.path
    import launcher_pg_select  # noqa: PLC0415 — needs mcp_server on sys.path

    marker_path = backend_marker.BACKEND_MARKER_PATH
    marker = backend_marker.read_backend_marker(marker_path)
    why = launcher_pg_select.why_not_eligible(os.environ, marker, marker_path)
    if why:
        return why
    backend_marker.write_backend_marker(
        backend_marker.MANAGED,
        launcher_pg_select.WRITTEN_BY,
        marker_path,
        root=str(paths.root),
    )
    return ""


def _target() -> tuple[managed_pg.PgPaths | None, bool, str]:
    """``(root, already managed, why not)`` for this Setup's managed step.

    A configured store decides first (B1): with a ``managed`` marker too, the
    user's database wins and nothing managed is started."""
    import launcher_backend  # noqa: PLC0415 — sibling script
    import launcher_pg_select  # noqa: PLC0415 — needs mcp_server on sys.path
    from mcp_server.infrastructure import backend_marker  # noqa: PLC0415 — resolvable once plugin_root is on sys.path

    configured = dict(os.environ)
    launcher_backend.map_database_option(configured)
    if backend_marker.environment_decides(configured):
        why = "database_url or a CORTEX_* backend setting selects the store"
        return None, False, f"{why}; the managed server is not started"
    marker_path = backend_marker.BACKEND_MARKER_PATH
    marker = backend_marker.read_backend_marker(marker_path)
    if marker is not None and marker["backend"] == backend_marker.MANAGED:
        return managed_pg.PgPaths(Path(marker["root"])), True, ""
    why = launcher_pg_select.why_not_eligible(os.environ, marker, marker_path)
    if why:
        return None, False, why
    return managed_pg.root_under(marker_path.parent), False, ""


def setup_step(data_dir: str, say) -> StepOutcome:
    """Setup's managed-PostgreSQL step.

    A store already on the managed server must stay reachable, so its failure
    fails Setup. For an eligible store a failure is printed and returned as
    the SQLite fallback's cause (ADR-1114, D3); anything else is untouched.
    """
    paths, managed, why = _target()
    if paths is None:
        say(f"managed PostgreSQL not selected: {why}")
        return StepOutcome()
    try:
        provision(paths, Path(data_dir) / "pg" / "dist")
    except launcher_pg_assets.UnsupportedError as exc:
        cause = f"managed PostgreSQL unavailable here ({exc})"
        if managed:  # the store stays on the managed server: Setup fails
            managed_pg.write_json(
                paths.provisioned, {"state": "failed", "error": cause}
            )
            return StepOutcome(failed=str(exc))
        say(f"{cause}; memories stay in SQLite")
        return StepOutcome(fallback=cause)
    except Exception as exc:  # noqa: BLE001 — every failure is printed with its cause; selection decides fatality
        cause = f"managed PostgreSQL did not start: {type(exc).__name__}: {exc}"
        managed_pg.write_json(paths.provisioned, {"state": "failed", "error": cause})
        if managed:
            return StepOutcome(failed=cause)
        say(f"{cause}; memories stay in SQLite (log: {paths.log})")
        return StepOutcome(fallback=cause)
    why = "" if managed else _select(paths)
    if why:
        say(f"managed PostgreSQL started but not selected: {why}")
        return StepOutcome()
    say(f"managed PostgreSQL ready at {paths.root}")
    return StepOutcome()
