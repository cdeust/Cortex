"""Acceptance A2 and A4 (ADR-1112), and the hook timings of increment 5.

A scripted session on a private cluster, every step a real process started
the way the hosts start them, with the production launcher (the broker is
started by the first hook through ``scripts/launcher.py``): SessionStart,
three UserPromptSubmit recalls, one ``remember`` tool call, one
``consolidate`` cycle. A sampler reads ``pg_stat_activity`` every 50 ms.

- A2: every Cortex backend is named ``cortex-store-<pool>-<pid>`` with one
  PID, the broker's, and no other client backend appears (the sampler's own
  connection excluded).
- A4: every ``idle in transaction`` sample is on one of the broker's store
  connections (a client never holds a transaction), and none belongs to a
  transaction older than ``deadlock_timeout``'s default (the incident's
  transaction spanned a whole consolidation pass). The first wording, "no
  sample at all", also counted the broker's own transactions caught between
  two statements of one request (0 to 7 ms old; experiment log entry 22);
  the raw count stays in the record.
- The session's detached jobs (SessionStart's consolidation cycle and code
  reanalysis, when the host offers them) are waited for with the sampler on,
  so a full consolidation cycle is inside the measurement.
- A3: with ``log_statement = ddl``, no DDL on a shared relation is logged
  during the session (the schema is current; the broker's start-up
  migration applies nothing; temporary tables are session-local).
- Timings: the first hook pays the broker's start (cold), the next ones do
  not (warm); every hook process exits by itself.

Records its numbers through ``CORTEX_REPRO_JSON``
(``python scripts/repro_connection_broker.py census``).

source: ADR-1112 acceptance A2, A4; increment 5
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from tests_py import _pg_private_cluster as cluster
from tests_py.infrastructure._census_instruments import Sampler, wait_for_session_jobs

psycopg = pytest.importorskip("psycopg")

pytestmark = [
    pytest.mark.skipif(not cluster.available(), reason="initdb/pg_ctl not on PATH"),
    pytest.mark.skipif(sys.platform == "win32", reason="Unix transport"),
    pytest.mark.skipif(
        not (
            os.environ.get("CORTEX_BROKER_MEASUREMENTS")
            or os.environ.get("CORTEX_REPRO_JSON")
        ),
        reason="set CORTEX_BROKER_MEASUREMENTS=1 (measurement, about 60 s)",
    ),
]

_REPO = Path(__file__).resolve().parents[2]
# source: PostgreSQL 17 docs 19.12 Lock Management, deadlock_timeout
# default 1 s; the incident's chain needed three such rounds
# (scripts/repro_lock_chain.py), a younger transaction cannot produce it
_MAX_IDLE_XACT_MS = 1000
# source: A2/A4 protocol, the sampler period
_SAMPLE_SECONDS = 0.05
# source: A2/A4 protocol, five pages of iter_memories_for_decay's default 1000
_SEEDED = 5000
_TOOL = (
    "import asyncio, sys\n"
    "from mcp_server.hooks.wiring import wire_composition_root\n"
    "wire_composition_root()\n"
    "from mcp_server.hooks._store_lifecycle import close_shared_store_on_exit\n"
    "from mcp_server.handlers.{module} import handler\n"
    "with close_shared_store_on_exit():\n"
    "    print(asyncio.run(handler({args})))\n"
)


def _run(
    argv: list[str], env: dict, payload: dict | None = None
) -> tuple[float, int, str]:
    started = time.monotonic()
    done = subprocess.run(
        argv,
        input=json.dumps(payload) if payload is not None else None,
        capture_output=True,
        text=True,
        env=env,
        cwd=_REPO,
        check=False,
    )
    tail = (done.stdout.strip() or done.stderr.strip())[-300:]
    return round(time.monotonic() - started, 2), done.returncode, tail


def _hook(module: str, env: dict, payload: dict) -> tuple[float, int, str]:
    return _run([sys.executable, "-m", f"mcp_server.hooks.{module}"], env, payload)


def _tool(module: str, args: dict, env: dict) -> tuple[float, int, str]:
    code = _TOOL.format(module=module, args=repr(args))
    return _run([sys.executable, "-c", code], env)


def _session(url: str, root: Path) -> dict:
    env = {**os.environ, "DATABASE_URL": url, "CORTEX_CLAUDE_DIR": str(root)}
    env.pop("CORTEX_STORE_IN_PROCESS", None)
    env["CORTEX_BROKER_IDLE_SECONDS"] = "3"
    transcript = root / "session.jsonl"
    transcript.write_text("")
    project = root / "project"  # a small project, not the cluster's files
    project.mkdir()
    (project / "README.md").write_text("census project\n")
    event = {
        "session_id": "census",
        "transcript_path": str(transcript),
        "cwd": str(project),
    }
    cold = _hook("session_start", env, event)
    warm = [
        _hook("auto_recall", env, {**event, "prompt": f"census prompt {i} broker"})
        for i in range(3)
    ]
    remember = _tool(
        "remember", {"content": "census fact about the broker", "force": True}, env
    )
    consolidate = _tool("consolidate", {}, env)
    return {
        "cold_hook": cold,
        "warm_hooks": warm,
        "remember": remember,
        "consolidate": consolidate,
    }


def _shared_ddl(log: Path, start: int) -> list[str]:
    """DDL statements on shared relations logged during the session (A3);
    session-local temporary tables are not shared and are left out."""
    with log.open("rb") as stream:
        stream.seek(start)
        text = stream.read().decode("utf-8", "replace")
    statements = [
        line.split("statement: ", 1)[1].strip()
        for line in text.splitlines()
        if "statement: " in line
    ]
    return [s for s in statements if not s.upper().startswith("CREATE TEMP")]


def _record(result: dict) -> None:
    target = os.environ.get("CORTEX_REPRO_JSON")
    if target:
        Path(target).write_text(json.dumps(result))


def _seed(maint: str) -> str:
    from mcp_server.infrastructure.pg_migrations import apply_schema  # noqa: PLC0415

    with psycopg.connect(maint, autocommit=True) as conn:
        conn.execute("CREATE DATABASE census")
    url = maint.rpartition("/")[0] + "/census"
    apply_schema(url)
    with psycopg.connect(url, autocommit=True) as conn:
        # several keyset pages for consolidation's streamed passes (A4)
        conn.execute(
            "INSERT INTO memories (content, embedding) SELECT"
            " 'census memory ' || g, array_fill(0.1::real, ARRAY[384])::vector"
            " FROM generate_series(1, %s) g",
            (_SEEDED,),
        )
    return url


def _observe(url: str, root: Path) -> tuple[dict, Sampler, float, list[str]]:
    """The session and its detached jobs, with the sampler on throughout."""
    sampler = Sampler(url, _SAMPLE_SECONDS)
    sampler.start()
    steps = _session(url, root)
    waited, jobs = wait_for_session_jobs()  # the sampler keeps sampling
    sampler.stop.set()
    sampler.join(timeout=10)
    return steps, sampler, waited, jobs


def _summary(sampler: Sampler, brokers: dict, waited: float, jobs: list) -> dict:
    return {
        "owners": sorted(sampler.owners),
        "owner_is_broker": all("store_broker" in c for c in brokers.values()),
        "other_client_backends": sorted(sampler.others),
        "peak_cortex_backends": sampler.peak,
        "idle_in_transaction_samples": sampler.idle_in_tx,
        "idle_in_transaction_outside_broker": sampler.idle_outside_broker,
        "max_idle_transaction_age_ms": sampler.max_idle_xact_ms,
        "max_idle_ms": sampler.max_idle_ms,
        "session_jobs_waited_seconds": waited,
        "session_jobs_seen": jobs,
        "migration_samples": sampler.migrations,
        "unexpected_samples": sampler.details[:20],
        "samples": sampler.samples,
        "seeded_memories": _SEEDED,
    }


def _measure(root: Path) -> tuple[dict, list[str]]:
    with cluster.private_cluster(
        root / "pg", max_connections=40, extra="-c log_statement=ddl"
    ) as maint:
        url = _seed(maint)
        log = root / "pg" / "pg.log"
        log_start = log.stat().st_size  # DDL before the session: the setup's
        steps, sampler, waited, jobs = _observe(url, root)
        brokers = sampler.commands
        session_ddl = _shared_ddl(log, log_start)
        # the instrument works: the setup's migration is in the same log
        setup_ddl = len(_shared_ddl(log, 0)) - len(session_ddl)
    # seconds and exit code per step: the output tails stay out of the log,
    # they can quote the user's own paths
    timings = {
        name: [step[:2] for step in value] if isinstance(value, list) else value[:2]
        for name, value in steps.items()
    }
    return {
        **timings,
        **_summary(sampler, brokers, waited, jobs),
        "shared_ddl_during_session": len(session_ddl),
        "ddl_logged_by_the_setup": setup_ddl,
    }, session_ddl


def test_one_broker_holds_every_connection_and_no_transaction_idles():
    with tempfile.TemporaryDirectory(prefix="a2-", dir=Path("/tmp").resolve()) as raw:
        result, session_ddl = _measure(Path(raw))
    _record(result)
    hooks = [result["cold_hook"], *result["warm_hooks"]]
    assert all(step[1] == 0 for step in hooks), result
    assert result["remember"][1] == 0 and result["consolidate"][1] == 0, result
    assert len(result["owners"]) == 1 and result["owner_is_broker"], result  # A2
    assert result["other_client_backends"] == [], result  # A2
    assert result["idle_in_transaction_outside_broker"] == 0, result  # A4
    assert result["max_idle_transaction_age_ms"] < _MAX_IDLE_XACT_MS, result  # A4
    assert result["ddl_logged_by_the_setup"] > 0, result  # the log records DDL
    assert result["shared_ddl_during_session"] == 0, (result, session_ddl)  # A3
    assert result["peak_cortex_backends"] <= 12, result  # P + 1 (P = 11)
