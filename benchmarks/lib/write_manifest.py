"""Write the MANIFEST.json describing exactly what produced a benchmark run.

Usage (from reproduce.sh):
    python benchmarks/lib/write_manifest.py \\
        RESULTS_DIR GIT_SHA DATASET_SHA256 PG_IMAGE CONTAINER PG_PORT RUNNER_PID

    # Cell-start snapshot (call BEFORE start_db, so it also predates the
    # benchmark's own container/DB overhead):
    python benchmarks/lib/write_manifest.py --snapshot RESULTS_DIR

source: ADR-0091"""

import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

# Same idiom as ablation_runner.py/latency_runner.py/e2_subsample_runner.py
# in this package: REPO_ROOT on sys.path so `benchmarks.lib.*` resolves both
# when this file runs as a standalone script (reproduce.sh invokes it
# directly, not via `-m`) and when it is imported normally as a package
# member (tests_py/).
_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from benchmarks.lib.disk_space_snapshot import disk_space_snapshot  # noqa: E402
from benchmarks.lib.machine_load_snapshot import machine_load_snapshot  # noqa: E402

_START_SNAPSHOT_NAME = "START_SNAPSHOT.json"


def write_start_snapshot(results_dir: str) -> Path:
    """Capture + persist the cell-start machine-load and disk-space snapshot.

    Called from reproduce.sh before `start_db`, so `RESULTS_DIR` already
    exists (created by `main()`'s `mkdir -p`) but nothing benchmark-specific
    has run yet. `build_manifest` reads this file back at cell end and folds
    it into the final MANIFEST.json as `machine_load_at_start` /
    `disk_space_at_start`, alongside the end-of-run `_at_end` counterparts.
    """
    out = Path(results_dir) / _START_SNAPSHOT_NAME
    payload = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "machine_load": machine_load_snapshot(),
        "disk_space": disk_space_snapshot(),
    }
    out.write_text(json.dumps(payload, indent=2))
    return out


def _read_start_snapshot(results_dir: str) -> dict | None:
    """Read back the cell-start snapshot written by `write_start_snapshot`.

    Returns None (never raises) when the start snapshot is absent. A missing start
    snapshot does not block the end-of-run manifest.

    source: ADR-0091"""
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

    source: ADR-0091"""
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

    source: ADR-0091"""
    try:
        # noqa: PLC0415 — ImportError-probe boundary: the except arm IS the
        # degraded mode (reranker_state "unresolved" in the manifest).
        import benchmarks.lib._composition_root_wiring  # noqa: PLC0415,F401 — source: issue #560
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


def _environment_fields() -> dict:
    """Package/model/reranker identity fields — split out of `build_manifest`
    to keep that function under the 40-line method cap
    (docs/agent-guidance.md § Code Style)."""
    return {
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
    }


def _start_snapshot_fields(results_dir: str) -> dict:
    """`_at_start` machine-load/disk-space fields, or None/None if
    `write_start_snapshot` was never called for this `results_dir` — split
    out of `build_manifest` for the same reason as `_environment_fields`."""
    snap = _read_start_snapshot(results_dir)
    if snap is None:
        return {"machine_load_at_start": None, "disk_space_at_start": None}
    return {
        "machine_load_at_start": snap.get("machine_load"),
        "disk_space_at_start": snap.get("disk_space"),
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
    return {
        "git_sha": git_sha,
        # source: ADR-0091
        **_start_snapshot_fields(results_dir),
        "machine_load_at_end": machine_load_snapshot(),
        "disk_space_at_end": disk_space_snapshot(),
        "longmemeval_dataset_sha256": ds_sha,
        "pg_image": pg_image,
        # source: ADR-0091
        "bench_container_name": container,
        "bench_container_port": int(pg_port),
        "bench_runner_pid": int(pid),
        **_environment_fields(),
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
