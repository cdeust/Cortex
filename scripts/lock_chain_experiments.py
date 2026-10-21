"""The three experiments of scripts/repro_lock_chain.py and their summary.

Each experiment varies one thing, the code tree the client process runs
(``main`` before the fix, ``branch`` after it, ``other`` = another install),
against the same private cluster and the same schema.

source: ADR-1112
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from scripts import lock_chain_lab as lab

# source: ADR-1112 a revision no tree has, as left by another install
FOREIGN = "another-install-revision"


def prepare_database(maint: str) -> str:
    """Create the experiment database at this branch's schema, with 3 rows."""
    from mcp_server.infrastructure.pg_store import PgMemoryStore  # noqa: PLC0415 -- branch code
    from mcp_server.infrastructure.pg_migrations import apply_schema  # noqa: PLC0415 -- branch code

    with lab.connect(maint, "setup") as conn:
        conn.execute("CREATE DATABASE cortex_lock_chain")
    url = maint.rsplit("/", 1)[0] + "/cortex_lock_chain"
    apply_schema(url)
    store = PgMemoryStore(database_url=url)
    for i in range(3):
        store.insert_memory({"content": f"lock chain row {i}", "source": "test"})
    store.close()
    return url


def _branch_hash() -> str:
    from mcp_server.infrastructure.pg_schema_fingerprint import compute_ddl_hash  # noqa: PLC0415 -- branch code

    return compute_ddl_hash()


def _recorded(monitor) -> str:
    return monitor.execute("SELECT left(ddl_hash, 16) FROM schema_meta").fetchone()[0]


def _run_alter(conn, done: dict) -> None:
    try:
        conn.execute(lab.NOOP_ALTER)
        done["at"] = time.monotonic()
    except Exception as exc:  # noqa: BLE001 -- recorded as the outcome, never hidden
        done["error"] = f"{type(exc).__name__}: {exc}"


def _queue_alter_and_readers(url: str, monitor, out: dict) -> tuple:
    ddl = lab.connect(url, "ddl")
    alter_done: dict = {}
    alter = threading.Thread(target=_run_alter, args=(ddl, alter_done), daemon=True)
    alter.start()
    lab.wait_until(monitor, lambda a: bool(alter_done) or lab.lock_waiters(a, "ddl"))
    readers_done: dict[str, float] = {}
    out["readers_started"] = time.monotonic()
    readers = lab.start_readers(url, readers_done)
    lab.wait_until(
        monitor,
        lambda a: (
            len(readers_done) == lab.READERS
            or lab.lock_waiters(a, "reader-") == lab.READERS
        ),
    )
    return ddl, alter, alter_done, readers, readers_done


def _finish(
    out: dict, release: float, readers, done, alter=None, alter_done=None
) -> None:
    if alter is not None:
        alter.join(lab.WAIT_S)
        out["alter"] = alter_done or {"still_waiting": True}
    for reader in readers:
        reader.join(lab.WAIT_S)
    out["readers_completed"] = len(done)
    last = max(done.values(), default=None)
    out["readers_waited_s"] = (
        None if last is None else round(last - out.pop("readers_started"), 3)
    )
    out["readers_completed_before_release"] = sum(
        1 for t in done.values() if t < release
    )


def stream_experiment(tree: Path, name: str, url: str) -> dict:
    """Consumer paused between chunks + no-op ALTER + readers, then its write."""
    monitor = lab.connect(url, "monitor")
    probe = lab.Probe(tree, "stream", url, f"{name}-consolidation")
    out: dict = {"tree": name, "consumer_ready": probe.wait("READY") is not None}
    ddl, alter, alter_done, readers, done = _queue_alter_and_readers(url, monitor, out)
    out["chain"] = lab.capture(monitor)
    probe.send("write")
    wrote = probe.wait("WROTE", lab.DEADLOCK_WINDOW_S) is not None
    out["consumer_write_done_within_deadlock_window"] = wrote
    out["after_write"] = lab.capture(monitor)
    if wrote:
        probe.send("finish")
        probe.wait("DONE")
        out["released_by"] = "consumer finished its pass"
    else:
        out["released_by"] = "consumer process killed by the harness"
    release = time.monotonic()
    probe.stop()
    _finish(out, release, readers, done, alter, alter_done)
    ddl.close()
    monitor.close()
    return out


def open_experiment(tree: Path, name: str, url: str, log: Path) -> dict:
    """An idle reader, then a store opens on a foreign recorded revision."""
    monitor = lab.connect(url, "monitor")
    monitor.execute("UPDATE schema_meta SET ddl_hash = %s", (FOREIGN,))
    blocker = lab.connect(url, "blocker", autocommit=False)
    blocker.execute("SELECT 1 FROM memories LIMIT 1")
    offset, _ = lab.ddl_lines(log, 0, "\x00")
    app = f"{name}-store-open"
    probe = lab.Probe(tree, "open", url, app)
    # source: harness bound; a branch store opens in well under 1 s
    out: dict = {"tree": name, "opened_while_reader_idle": probe.wait("OPENED", 5.0)}
    if out["opened_while_reader_idle"] is None:
        lab.wait_until(monitor, lambda a: lab.lock_waiters(a, app) > 0)
    readers_done: dict[str, float] = {}
    out["readers_started"] = time.monotonic()
    readers = lab.start_readers(url, readers_done)
    lab.wait_until(
        monitor,
        lambda a: (
            len(readers_done) == lab.READERS
            or lab.lock_waiters(a, "reader-") == lab.READERS
        ),
    )
    out["chain"] = lab.capture(monitor)
    blocker.rollback()
    release = time.monotonic()
    first = out["opened_while_reader_idle"]
    refused = first is not None and first.startswith("REFUSED")
    out["store_outcome"] = first if refused else probe.wait("DONE")
    probe.stop()
    _finish(out, release, readers, readers_done)
    _, lines = lab.ddl_lines(log, offset, app)
    out["ddl_statements_logged"], out["ddl_sample"] = len(lines), lines[:3]
    out["recorded_revision_after"] = _recorded(monitor)
    monitor.execute("UPDATE schema_meta SET ddl_hash = %s", (_branch_hash(),))
    blocker.close()
    monitor.close()
    return out


def flipflop_experiment(trees: dict, order: list[str], url: str, log: Path) -> dict:
    """Trees with different DDL open stores alternately on one database."""
    monitor = lab.connect(url, "monitor")
    monitor.execute("UPDATE schema_meta SET ddl_hash = %s", (_branch_hash(),))
    steps = []
    for i, name in enumerate(order):
        offset, _ = lab.ddl_lines(log, 0, "\x00")
        app = f"flip-{i}-{name}"
        probe = lab.Probe(trees[name], "open", url, app)
        outcome = probe.wait("DONE", lab.WAIT_S * 4)
        probe.stop()
        _, lines = lab.ddl_lines(log, offset, app)
        steps.append(
            {
                "tree": name,
                "outcome": outcome,
                "ddl_statements_logged": len(lines),
                "recorded_revision_after": _recorded(monitor),
            }
        )
    monitor.execute("UPDATE schema_meta SET ddl_hash = %s", (_branch_hash(),))
    monitor.close()
    return {"order": order, "steps": steps}


def _chain_lines(chain: dict) -> list[str]:
    return [
        f"  - `{r['app']}` {r['state']}"
        + (f", waits {r['wait_event_type']}" if r["wait_event_type"] == "Lock" else "")
        + (f", blocked by {r['blocked_by_apps']}" if r["blocked_by_apps"] else "")
        for r in chain["activity"]
        if r["app"] not in ("monitor", "")
    ]


def summarize(results: dict) -> str:
    out: list[str] = []
    for key, res in results.items():
        if key.startswith(("stream/", "open/")):
            keep = {k: v for k, v in res.items() if k not in ("chain", "after_write")}
            out.append(f"- {key}: `{keep}`")
            out.append("  chain at capture:")
            out.extend(_chain_lines(res["chain"]))
            if "after_write" in res:
                out.append("  after the consumer's own write:")
                out.extend(_chain_lines(res["after_write"]))
        elif key.startswith("flipflop"):
            out.append(f"- {key}: `{res}`")
    return "\n".join(out) + "\n"
