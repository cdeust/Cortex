"""Remediation policy for memories impacted by a code change (fleet-watch #110).

Detection (``handlers/consolidation/memory_staleness_pass.py``) marks an impacted
memory stale — it points at the bug. Remediation goes one step further: it
decides HOW to make the memory correct again, safely, so a commit that
invalidates a memory also repairs it.

Two classes, because auto-rewriting prose from a diff risks fabrication:

  - CODE-DERIVED memories (written by codebase ingestion — ``agent_context ==
    'codebase'``) can be refreshed *mechanically*: re-ingesting the changed file
    with ``codebase_analyze`` (incremental, content-hash tracked) supersedes the
    old AST-derived fact with the current one. Action: ``REINGEST``.
  - HAND-AUTHORED memories (decisions, lessons) must NOT be silently rewritten;
    a machine cannot re-derive an author's intent from a diff. Action:
    ``FLAG_STALE`` — mark stale and surface for a human/LLM to re-author.

Pure: a memory dict in, an action out. Callers own the I/O (the re-ingest call,
the stale mark). ``agent_context == 'codebase'`` is the same marker
``handlers/codebase_analyze_helpers.py`` and ``handlers/change_impact.py`` use to
scope code-derived rows, reused here — not a new classification signal.
"""

from __future__ import annotations

from enum import Enum


class Remediation(str, Enum):
    REINGEST = "reingest"
    FLAG_STALE = "flag_stale"


def is_code_derived(memory: dict) -> bool:
    """True when the memory was produced by codebase ingestion.

    Primary marker: ``agent_context == 'codebase'`` (the scope predicate the
    codebase-analyze read/write paths already use). A codebase content-hash tag
    (``codebase_analyze``'s incremental HASH_TAG) is accepted as a fallback for
    rows written before the context was consistently stamped.
    """
    if str(memory.get("agent_context", "")).strip().lower() == "codebase":
        return True
    tags = {str(t).lower() for t in (memory.get("tags") or [])}
    return "codebase" in tags or any(t.startswith("hash:") for t in tags)


def classify_remediation(memory: dict) -> Remediation:
    """REINGEST a code-derived memory; FLAG_STALE a hand-authored one."""
    return Remediation.REINGEST if is_code_derived(memory) else Remediation.FLAG_STALE
