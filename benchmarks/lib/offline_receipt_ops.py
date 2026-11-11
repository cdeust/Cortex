"""The child process of the offline receipt: memory operations, network off.

Issue #734, slice 6. ``offline_receipt.py`` starts this module in a fresh
interpreter whose store paths point at a throwaway SQLite tree, because
``mcp_server`` binds those paths at import time
(tests_py/conftest.py, ``_redirect_real_data_roots``). Here the network guard
is installed before the first ``mcp_server`` import, then ``remember`` and
``recall`` run through their production handlers. Each operation is labelled
with the embedding mode and the reranker state it ran in, and the refused
network attempts it made. The result is one JSON document, written to the
path given as the only argument (stdout stays free for the server's logs).

The models are the caller's own: the model caches are not redirected, so a
provisioned machine is measured as it is.

source: issue #734, acceptance item 4;
docs/audits/model-identity-inventory-2026-11-06.md,
remaining slice 4
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from typing import Any

from benchmarks.lib.network_guard import NetworkGuard

# source: issue #734 (three facts a recall must find; one is enough to show
# that the stored memories are retrieved through the served embedding).
MEMORIES = (
    "The offline receipt stores this memory with networking disabled.",
    "SQLite keeps the receipt's memories in a throwaway directory.",
    "Recall must find a stored memory without reaching any host.",
)
QUERY = "offline receipt memory stored with networking disabled"


# source: mcp_server/core/reranker.py ``rerank_results`` (the component its
# swallowed inference failure is noted under).
_RERANK_CALL = "reranker.rerank_call"


def _rerank_failures() -> int:
    """Inference failures the loaded reranker swallowed so far (ADR-0640)."""
    # noqa: PLC0415 — imported after the guard is installed (module docstring).
    from mcp_server.observability import silent_failure  # noqa: PLC0415

    return int(silent_failure.status().get(_RERANK_CALL, {}).get("count", 0))


def _labels() -> dict[str, Any]:
    """The embedding mode and reranker state now, without loading a model.

    ``reranker_state`` is the load state only: a loaded model whose inference
    raised served the first-stage order, which ``rerank_failures`` counts."""
    # noqa: PLC0415 — imported after the guard is installed (module docstring).
    from mcp_server.core.reranker import reranker_status  # noqa: PLC0415
    from mcp_server.infrastructure.embedding_factory import (  # noqa: PLC0415
        get_embedding_engine,
    )

    engine = get_embedding_engine()
    return {
        "embedding_mode": engine.mode,
        "embedding_model_state": engine.model_state.name,
        "reranker_state": reranker_status().state,
    }


async def _timed(guard: NetworkGuard, name: str, call: Any) -> dict[str, Any]:
    """Run one operation; record its outcome, labels and refused attempts.

    postcondition: ``ok`` is False and ``error`` names the class when the
    operation raised; the message is not kept (it can carry content)."""
    before, failures = len(guard.attempts), _rerank_failures()
    start = time.perf_counter()
    entry: dict[str, Any] = {"operation": name, "ok": True, "error": None}
    try:
        entry["result"] = await call()
    except Exception as exc:  # noqa: BLE001 — the receipt records the failure
        entry.update(ok=False, error=type(exc).__name__, result=None)
    entry["elapsed_ms"] = round((time.perf_counter() - start) * 1000, 1)
    entry["network_attempts"] = len(guard.attempts) - before
    entry["rerank_failures"] = _rerank_failures() - failures
    entry.update(_labels())
    return entry


def _remember_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {"stored": bool(result.get("stored") or result.get("status") == "stored")}


def _recall_summary(result: dict[str, Any]) -> dict[str, Any]:
    contents = [m.get("content", "") for m in result.get("memories", [])]
    return {
        "count": result.get("count", 0),
        "found_stored": any(text in MEMORIES for text in contents),
    }


async def run_operations(guard: NetworkGuard) -> list[dict[str, Any]]:
    """``remember`` each of ``MEMORIES``, then ``recall`` ``QUERY``.

    precondition: ``guard`` is installed and the composition root is wired."""
    # noqa: PLC0415 — imported after the guard is installed (module docstring).
    from mcp_server.handlers.recall import handler as recall  # noqa: PLC0415
    from mcp_server.handlers.remember import handler as remember  # noqa: PLC0415

    entries = []
    for text in MEMORIES:
        args = {"content": text, "tags": ["offline-receipt"], "force": True}
        entry = await _timed(guard, "remember", lambda a=args: remember(a))
        entry["result"] = entry["result"] and _remember_summary(entry["result"])
        entries.append(entry)
    args = {"query": QUERY, "max_results": 5, "min_heat": 0.0}
    entry = await _timed(guard, "recall", lambda: recall(args))
    entry["result"] = entry["result"] and _recall_summary(entry["result"])
    entries.append(entry)
    return entries


def served_manifest() -> dict[str, Any]:
    """``effective_manifest`` with what this process's engines served.

    The reranker is reported through ``reranker_status``: the receipt states
    the state recall left it in and never loads it for the manifest."""
    # noqa: PLC0415 — imported after the guard is installed (module docstring).
    from benchmarks.lib.embedding_identity import (  # noqa: PLC0415
        embedding_identity_fields,
    )
    from mcp_server.core.reranker import model_identity, reranker_status  # noqa: PLC0415
    from mcp_server.doctor_manifest import effective_manifest  # noqa: PLC0415
    from mcp_server.infrastructure.embedding_factory import (  # noqa: PLC0415
        get_embedding_engine,
    )

    identity = model_identity()
    reranker = {
        "reranker_state": reranker_status().state,
        "reranker_model_sha256": identity.sha256,
        "reranker_model_identity": identity.state,
    }
    embedding = embedding_identity_fields(get_embedding_engine())
    return effective_manifest(
        embedding_served=embedding, reranker_served=reranker, backend="sqlite"
    )


def main(argv: list[str]) -> int:
    """Write the operations, the refused attempts and the manifest as JSON.

    precondition: ``argv`` is ``[output_path]``."""
    (output,) = argv
    guard = NetworkGuard()
    guard.install()
    # noqa: PLC0415 — the wiring imports mcp_server, after the guard.
    from mcp_server.hooks.wiring import wire_composition_root  # noqa: PLC0415

    wire_composition_root()
    operations = asyncio.run(run_operations(guard))
    # The manifest is built once the operations are done and the guard is
    # removed: it is not a memory operation, and its artifact identity runs
    # a local ``git`` (doctor_artifact), which a refused spawn would turn into
    # ``revision state unknown``. It reads files only (doctor_manifest).
    guard.uninstall()
    manifest = served_manifest()
    document = {
        "operations": operations,
        "network_attempts": guard.attempts,
        "runtime_manifest": manifest,
    }
    with open(output, "w", encoding="utf-8") as handle:
        json.dump(document, handle, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
