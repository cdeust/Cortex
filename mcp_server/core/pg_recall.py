"""PG recall: intent-adaptive retrieval via recall_memories() + FlashRank reranking.

Two top-level functions are exposed:

  - `recall()` — the legacy WRRF composition retrieval path. Returns a
    flat ranked list of candidates. Used by the production handler and
    the current BEAM benchmark harness.

  - `assemble_context()` — the new structured 3-phase context assembler
    (Clément Deust's invention ported from Swift, complemented with
    paper-backed mechanisms). Returns a budgeted, slot-filled prompt
    with truncation awareness. See `mcp_server/core/context_assembly/`.

Pure business logic — takes a store + embeddings, returns results.

`recall()` is a thin public-API wrapper: the request-scoped context and
WRRF fetch/triage live in `pg_recall_context.py`; the post-WRRF
recollection/rerank/typed-pool/final stages plus the pipeline driver
(`run_recall_pipeline`) live in `pg_recall_stages.py`; the store-duck-typed
mood/goal/Titans signal readers live in `pg_recall_signals.py`. All are
re-exported here (alongside the pre-existing `pg_recall_weights.py` /
`pg_recall_assembly.py` seams cut at #368) so no caller or test has to
move — this file stays under the local 300-line/40-line caps (CLAUDE.md
§ Code Style; a tightening of coding-standards.md §4.1/§4.2).
"""

from __future__ import annotations

from typing import Any

# Re-exported for backward compatibility: tests and callers reach these
# names as ``pg_recall.<name>`` (see pg_recall_signals.py / pg_recall_
# context.py / pg_recall_stages.py docstrings for why they moved).
from mcp_server.core.pg_recall_signals import (  # noqa: F401 — re-export
    _get_active_goal,
    _get_titans,
    _get_user_mood,
)
from mcp_server.core.pg_recall_context import RecallContext
from mcp_server.core.pg_recall_stages import (
    _chronological_rerank,  # noqa: F401 — re-export
    run_recall_pipeline,
)

# Live in pg_recall_weights.py since the #368 split. Re-exported: callers and
# tests reach compute_pg_weights through this module.
from mcp_server.core.pg_recall_weights import (  # noqa: E402 — facade re-export at the seam the split left
    compute_pg_weights,
)


def recall(
    query: str,
    store: Any,
    embeddings: Any,
    *,
    top_k: int = 10,
    domain: str | None = None,
    directory: str | None = None,
    agent_topic: str | None = None,
    min_heat: float = 0.01,
    rerank: bool = True,
    rerank_alpha: float = 0.70,
    wrrf_k: int = 60,
    momentum_state: dict | None = None,
    include_globals: bool = True,
    familiarity_shortcut: bool = False,
    cross_domain: bool = False,
    sa_mode: str = "tail",
) -> list[dict[str, Any]]:
    """Thin recall() wrapper; see pg_recall_context.py for tuning-knob citations."""
    ctx = RecallContext(
        query=query,
        store=store,
        embeddings=embeddings,
        domain=domain,
        directory=directory,
        agent_topic=agent_topic,
        min_heat=min_heat,
        wrrf_k=wrrf_k,
        include_globals=include_globals,
        cross_domain=cross_domain,
        sa_mode=sa_mode,
        rerank=rerank,
        rerank_alpha=rerank_alpha,
        familiarity_shortcut=familiarity_shortcut,
        top_k=top_k,
        momentum_state=momentum_state,
    )
    return run_recall_pipeline(ctx)


# ── Structured 3-phase context assembly ─────────────────────────────────
# Lives in pg_recall_assembly.py since the #368 split (§4.1: this file was
# 833 lines). Re-exported here because callers and tests reach it as
# ``pg_recall.assemble_context``; this name is a facade over that module and
# holds no implementation.
from mcp_server.core.pg_recall_assembly import assemble_context  # noqa: E402 — facade re-export, placed at the seam the split left rather than hoisted away from its explanatory comment

__all__ = ["assemble_context", "compute_pg_weights", "recall"]
