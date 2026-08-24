"""Apply the change-remediation policy to diff-impacted memories (#110).

The sibling of ``memory_staleness_pass`` (detection): where that marks stale,
this *repairs*. Given the memories a commit impacted (from ``change_impact``'s
matcher ∩ the diff) — each carrying the subset of its file refs that changed —
it applies ``core.change_remediation``:

  - code-derived memories → collect their changed files and re-ingest them once
    (``reingest_fn``); ``codebase_analyze`` supersedes the stale AST facts.
  - hand-authored memories → ``mark_memory_stale`` and leave the re-authoring to
    a human/LLM (never silently rewritten).

Composition root: pure policy (``classify_remediation``) + injected re-ingest
callback + injected store. No direct I/O here, so it unit-tests with fakes; the
real wiring (``codebase_analyze`` as ``reingest_fn``, the commit diff as the
impact source) is done by the caller and validated against AP + a real codebase.
"""

from __future__ import annotations

import logging
from typing import Callable, Protocol

from mcp_server.core.change_remediation import (
    Remediation,
    build_impacted,
    classify_remediation,
)

logger = logging.getLogger(__name__)

ReingestFn = Callable[[list[str]], None]


class _RemediationStore(Protocol):
    def mark_memory_stale(self, memory_id: int, stale: bool = True) -> None: ...


def remediate_impacted(
    impacted: list[dict],
    store: _RemediationStore,
    reingest_fn: ReingestFn,
) -> dict[str, int]:
    """Repair diff-impacted memories per the remediation policy.

    Each ``impacted`` item is a memory dict plus ``changed_refs`` — the subset
    of its file references that appear in the commit diff. Returns counts.
    """
    reingest_paths: set[str] = set()
    counts = {"reingest_memories": 0, "flagged_stale": 0, "reingest_paths": 0}
    for mem in impacted:
        if classify_remediation(mem) is Remediation.REINGEST:
            reingest_paths.update(mem.get("changed_refs") or [])
            counts["reingest_memories"] += 1
        else:
            store.mark_memory_stale(mem["id"], True)
            counts["flagged_stale"] += 1
    if reingest_paths:
        reingest_fn(sorted(reingest_paths))
    counts["reingest_paths"] = len(reingest_paths)
    logger.info("change remediation: %s", counts)
    return counts


def remediate_from_impact(
    matches: list,
    memory_by_id: dict[int, dict],
    store: _RemediationStore,
    reingest_fn: ReingestFn,
) -> dict[str, int]:
    """Drive remediation straight from ``change_impact``'s match output.

    ``matches`` is the ``ImpactMatch`` list from ``handlers/change_impact.py``
    (each carrying ``memory_id`` + the changed ``matched_files``); ``memory_by_id``
    resolves those ids to memory dicts. This is the one composition the caller
    needs — supply the real ``reingest_fn`` (an incremental ``codebase_analyze``
    over the changed paths), validated against AP + a real codebase.
    """
    return remediate_impacted(build_impacted(matches, memory_by_id), store, reingest_fn)
