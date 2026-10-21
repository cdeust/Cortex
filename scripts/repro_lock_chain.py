"""Reproduce the 2026-10-20 lock chain and capture it from the server.

    python scripts/repro_lock_chain.py [--other-tree <dir>]

One command, no live store: a private PostgreSQL cluster (same binaries,
``log_statement = ddl``) on a free 127.0.0.1 port in a temporary directory.
Each experiment runs the pre-fix code (``git archive main``) and this
branch's code as separate client processes (scripts/lock_chain_probe.py)
and records ``pg_stat_activity`` with ``pg_blocking_pids`` and the
``pg_locks`` rows on ``memories``:

* ``stream``: a consolidation consumer paused between two chunks, a no-op
  ``ALTER TABLE memories ADD COLUMN IF NOT EXISTS``, three readers; then
  the consumer's own write, given three times ``deadlock_timeout``.
* ``open``: one client holds a transaction that read ``memories``; a store
  opens on a database recorded at another revision; three readers.
* ``flipflop``: two code trees with different DDL (default: the Codex uv
  tool install, if present) open stores alternately; the recorded revision
  and the DDL statements the server logged are read after each open.

Writes the full capture to docs/verification/connection-broker/evidence/
and appends a summary entry to the append-only experiment log.

source: ADR-1112
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# source: ADR-1112 repository root, from this file's location
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import lock_chain_experiments as lab  # noqa: E402
from tests_py import _pg_private_cluster as cluster  # noqa: E402

# source: ADR-1112 evidence and log locations
VERIFY = ROOT / "docs" / "verification" / "connection-broker"
# source: ADR-1112 the Codex install measured in experiment-log entry 2
CODEX_TREE = (
    Path.home() / ".local/share/uv/tools/hypermnesia-mcp/lib/python3.13/site-packages"
)
# source: ADR-1112 room for the probes' pools plus readers; not a saturation run
MAX_CONNECTIONS = 60
# source: PostgreSQL log_statement / log_line_prefix (runtime-config-logging)
SERVER_OPTIONS = "-c log_statement=ddl -c log_line_prefix='%m [%p] %a '"


def _trees(work: Path, other: Path | None, base_ref: str) -> dict[str, Path]:
    trees = {"branch": ROOT, "main": work / "main"}
    trees["main"].mkdir()
    archive = subprocess.run(
        ["git", "archive", base_ref, "mcp_server"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    subprocess.run(["tar", "-x", "-C", str(trees["main"])], input=archive, check=True)
    if other is not None and (other / "mcp_server").is_dir():
        trees["other"] = work / "other"
        shutil.copytree(
            other / "mcp_server",
            trees["other"] / "mcp_server",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
    return trees


def _run_all(trees: dict[str, Path], work: Path) -> dict:
    results: dict = {"trees": {k: str(v) for k, v in trees.items()}}
    with cluster.private_cluster(work, MAX_CONNECTIONS, SERVER_OPTIONS) as maint:
        url = lab.prepare_database(maint)
        log = work / "pg.log"
        for name in ("main", "branch"):
            results[f"stream/{name}"] = lab.stream_experiment(trees[name], name, url)
            results[f"open/{name}"] = lab.open_experiment(trees[name], name, url, log)
        if "other" in trees:
            for first in ("main", "branch"):
                order = [first, "other", first, "other"]
                results[f"flipflop/{first}+other"] = lab.flipflop_experiment(
                    trees, order, url, log
                )
        else:
            results["flipflop"] = {"skipped": "no second tree with a different DDL"}
    return results


def _record(results: dict) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    results["head"] = head
    evidence = VERIFY / "evidence" / f"lock-chain-{stamp}.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    summary = lab.summarize(results)
    with (VERIFY / "experiment-log.md").open("a", encoding="utf-8") as log:
        log.write(
            f"\n### {stamp} lock chain\n\n- head: `{head}`\n"
            f"- command: `python scripts/repro_lock_chain.py`\n"
            f"- evidence: `{evidence.relative_to(ROOT)}`\n{summary}"
        )
    print(summary)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--other-tree",
        default=str(CODEX_TREE),
        help="a second installed tree for the flipflop experiment; empty to skip",
    )
    parser.add_argument(
        "--base-ref", default="main", help="the pre-fix tree (git ref) to compare"
    )
    args = parser.parse_args()
    if not cluster.available():
        print("initdb/pg_ctl not on PATH", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="cortex-lock-chain-") as scratch:
        work = Path(scratch)
        other = Path(args.other_tree) if args.other_tree else None
        results = _run_all(_trees(work, other, args.base_ref), work)
    print(_record(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
