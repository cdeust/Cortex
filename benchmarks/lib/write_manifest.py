"""Write the MANIFEST.json describing exactly what produced a benchmark run.

Extracted verbatim from the heredoc previously embedded in
``benchmarks/reproduce.sh::write_manifest`` (behaviour unchanged) so the shell
driver stays within the size limits of coding-standards.md §4 and so this
provenance logic can be read, diffed and tested as Python.

Usage (from reproduce.sh):
    python benchmarks/lib/write_manifest.py \\
        RESULTS_DIR GIT_SHA DATASET_SHA256 PG_IMAGE CONTAINER PG_PORT RUNNER_PID
"""

import json
import platform
import sys
from pathlib import Path


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
    return {
        "git_sha": git_sha,
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
        "results_files": sorted(p.name for p in Path(results_dir).glob("*.json")),
    }


def main(argv: list[str]) -> None:
    results_dir = argv[1]
    manifest = build_manifest(*argv[1:8])
    out = Path(results_dir) / "MANIFEST.json"
    out.write_text(json.dumps(manifest, indent=2))
    print(f"==> Wrote {out}")


if __name__ == "__main__":
    main(sys.argv)
