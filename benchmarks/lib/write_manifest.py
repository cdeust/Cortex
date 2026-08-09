"""Write the MANIFEST.json describing exactly what produced a benchmark run.

Extracted verbatim from the heredoc previously embedded in
``benchmarks/reproduce.sh::write_manifest`` (behaviour unchanged) so the shell
driver stays within the size limits of coding-standards.md §4 and so this
provenance logic can be read, diffed and tested as Python.

Usage (from reproduce.sh):
    python benchmarks/lib/write_manifest.py \\
        RESULTS_DIR GIT_SHA DATASET_SHA256 PG_IMAGE CONTAINER PG_PORT RUNNER_PID

    # Cell-start snapshot (call BEFORE start_db, so it also predates the
    # benchmark's own container/DB overhead):
    python benchmarks/lib/write_manifest.py --snapshot RESULTS_DIR
"""

import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_START_SNAPSHOT_NAME = "START_SNAPSHOT.json"


def machine_load_snapshot() -> dict:
    """Load average + concurrent pytest/container counts, as this run saw them.

    2026-08-10 incident: a 5-cell trust-factor sweep ran while three other
    agents' full pytest suites were active on the same machine (load average
    ~11-14 on a 10-core box); one cell crashed on a native fatal error, and
    the crash was the ONLY visible signal — cells that merely finished under
    the same contention could have returned degraded numbers (saturated
    connection pool, cold cache, GC pressure) with nothing in the artifact to
    show it. The whole grid was discarded and re-run rather than salvaged,
    per this project's own rule: a measurement from a harness with a known
    defect is invalid and is redone, not patched after the fact — and
    contention is exactly such a defect. This snapshot is recorded so that
    rule can be applied by inspection later, instead of by asking whoever
    happened to be watching at the time.

    Taken TWICE per cell (2026-08-10 follow-up, same incident): once at cell
    START (`write_start_snapshot`, called before `start_db` so it predates
    the container/DB overhead too) and once at cell END (inside
    `build_manifest`, the pre-existing call). A crash is the visible failure
    mode; a cell that merely FINISHES under contention (saturated pool, cold
    cache, GC pressure) is the invisible one, and a single end-of-run
    snapshot cannot distinguish "this cell ran under load throughout" from
    "load spiked right at the end". Two points at least bound the window.

    Best-effort: any probe that fails records `None`/`"unresolved"` rather
    than aborting manifest generation, matching this module's other fields.
    """
    try:
        load1, load5, load15 = os.getloadavg()
    except OSError:  # not available on this platform (e.g. Windows)
        load1 = load5 = load15 = None

    def _run(cmd: list[str]) -> str | None:
        try:
            return subprocess.run(
                cmd, capture_output=True, text=True, timeout=10, check=False
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return None

    # Filtered in Python, not via a shell `grep -c "[p]ytest"` idiom: a
    # subprocess.run argv has no shell to bracket-escape a self-match, so the
    # filter runs here instead, over the same process list that idiom reads.
    ps_out = _run(["ps", "aux"])
    pytest_procs = (
        None
        if ps_out is None
        else sum(
            1 for line in ps_out.splitlines() if "pytest" in line and "grep" not in line
        )
    )

    docker_out = _run(["docker", "ps", "-q"])
    docker_containers = (
        None
        if docker_out is None
        else len([line for line in docker_out.splitlines() if line.strip()])
    )

    return {
        "load_average_1m": load1,
        "load_average_5m": load5,
        "load_average_15m": load15,
        "cpu_count": os.cpu_count(),
        "concurrent_pytest_processes": pytest_procs,
        "concurrent_docker_containers": docker_containers,
    }


def write_start_snapshot(results_dir: str) -> Path:
    """Capture + persist the cell-start machine-load snapshot.

    Called from reproduce.sh before `start_db`, so `RESULTS_DIR` already
    exists (created by `main()`'s `mkdir -p`) but nothing benchmark-specific
    has run yet. `build_manifest` reads this file back at cell end and folds
    it into the final MANIFEST.json as `machine_load_at_start`, alongside the
    end-of-run `machine_load_at_end` — see `machine_load_snapshot`'s
    docstring for why both points are recorded.
    """
    out = Path(results_dir) / _START_SNAPSHOT_NAME
    payload = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "machine_load": machine_load_snapshot(),
    }
    out.write_text(json.dumps(payload, indent=2))
    return out


def _read_start_snapshot(results_dir: str) -> dict | None:
    """Read back the cell-start snapshot written by `write_start_snapshot`.

    Returns None (never raises) when absent — e.g. a `reproduce.sh` call
    that predates this fix, or a caller that skipped the `--snapshot` step.
    A missing start snapshot must not block the end-of-run manifest from
    being written; `machine_load_at_start` is simply absent in that case,
    which is itself an observable fact rather than a silent guess.
    """
    path = Path(results_dir) / _START_SNAPSHOT_NAME
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def ver(pkg: str) -> str:
    try:
        # noqa: PLC0415 — ImportError-probe boundary: the except arm IS the
        # degraded mode ("absent" in the manifest) for an optional bench extra.
        import importlib.metadata as m  # noqa: PLC0415

        return m.version(pkg)
    except Exception:  # noqa: BLE001 — signal is the recorded "absent" value
        return "absent"


def embedding_revision() -> str:
    """Exact model revision this run's EmbeddingEngine loaded.

    i7d3 reproducibility-gap fix (2026-07-11): uv.lock pins the Python package
    version but NOT the HF model weights an unpinned model name resolves
    against (refs/main can move independently of any pyproject/uv.lock change,
    with zero signal in this manifest before this fix). See
    mcp_server/infrastructure/embedding_engine.py's "Model revision pin"
    docstring for the incident this closes.
    """
    try:
        # noqa: PLC0415 — ImportError-probe boundary: the except arm IS the
        # degraded mode ("unresolved" in the manifest).
        from mcp_server.infrastructure.embedding_engine import (  # noqa: PLC0415
            get_embedding_engine,
        )

        return get_embedding_engine().revision
    except Exception:  # noqa: BLE001 — signal is the recorded "unresolved" value
        return "unresolved"


def reranker_fields() -> dict:
    """Load state + weights sha256 of the reranker, as this run observed it.

    Reranker cache-durability fix (2026-07-11, incident: silent reranker skip).
    Same shape of gap as embedding_revision above: a bare-except swallow in
    mcp_server.core.reranker let 6 LongMemEval runs execute with CE reranking
    silently disabled (MRR 0.9163 -> 0.8636), with nothing in the manifest to
    show it.
    """
    try:
        # noqa: PLC0415 — ImportError-probe boundary: the except arm IS the
        # degraded mode (reranker_state "unresolved" in the manifest).
        from mcp_server.core.reranker import (  # noqa: PLC0415
            ensure_reranker_loaded,
            model_sha256,
        )

        status = ensure_reranker_loaded()
        return {
            "reranker_active": status.state == "loaded",
            "reranker_state": status.state,
            "reranker_model_sha256": model_sha256(),
        }
    except Exception:  # noqa: BLE001 — signal is the recorded reranker_state
        return {
            "reranker_active": False,
            "reranker_state": "unresolved",
            "reranker_model_sha256": None,
        }


def build_manifest(
    results_dir: str,
    git_sha: str,
    ds_sha: str,
    pg_image: str,
    container: str,
    pg_port: str,
    pid: str,
) -> dict:
    start_snapshot = _read_start_snapshot(results_dir)
    return {
        "git_sha": git_sha,
        # Alongside git_sha, not buried: see machine_load_snapshot's
        # docstring for why (2026-08-10 sweep-contention incident). Two
        # points, not one — `_at_start` is None when reproduce.sh's
        # `--snapshot` step was never called for this results_dir.
        "machine_load_at_start": (
            start_snapshot["machine_load"] if start_snapshot else None
        ),
        "machine_load_at_end": machine_load_snapshot(),
        "longmemeval_dataset_sha256": ds_sha,
        "pg_image": pg_image,
        # Per-run container isolation fix (2026-07-11, incident: two concurrent
        # runs from different worktrees shared one fixed container/port and
        # silently cross-contaminated scores — 0.9163 isolated vs. 0.78-0.86
        # under concurrency). Recorded so a future diagnostic can always match a
        # result set to the exact container/port/PID that produced it instead
        # of guessing.
        "bench_container_name": container,
        "bench_container_port": int(pg_port),
        "bench_runner_pid": int(pid),
        "python": platform.python_version(),
        "packages": {
            p: ver(p)
            for p in (
                "datasets",
                "sentence-transformers",
                "torch",
                "psycopg",
                "psycopg-pool",
            )
        },
        "embedding_model_revision": embedding_revision(),
        **reranker_fields(),
        "results_files": sorted(
            p.name
            for p in Path(results_dir).glob("*.json")
            if p.name != _START_SNAPSHOT_NAME
        ),
    }


def main(argv: list[str]) -> None:
    if len(argv) > 1 and argv[1] == "--snapshot":
        out = write_start_snapshot(argv[2])
        print(f"==> Wrote {out}")
        return
    results_dir = argv[1]
    manifest = build_manifest(*argv[1:8])
    out = Path(results_dir) / "MANIFEST.json"
    out.write_text(json.dumps(manifest, indent=2))
    print(f"==> Wrote {out}")


if __name__ == "__main__":
    main(sys.argv)
