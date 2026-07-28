"""Distillation reporting — authoring prompts + memify_derive usage stats.

Split out of ``core/distillation.py`` (INC7.8/M-D8) purely to respect the
300-line file cap (§4.1): dossier ASSEMBLY (clustering, pairing, the
idempotence marker) lives in ``distillation.py``; TEXT GENERATION for the
LLM prompt and the read-only usage snapshot for ``memify_derive`` live
here. Both are pure business logic — no I/O.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.distillation import DistillDossier


def build_distill_prompt(
    dossier: DistillDossier, memory_previews: list[dict[str, Any]]
) -> str:
    """Structured authoring prompt for the in-session LLM (M-D8 point 2).

    Precondition: ``memory_previews`` is ``[{"id", "content", "tags"}]``
    for exactly ``dossier.memory_ids`` (content truncated by the caller,
    same 200-char convention as ``navigate_memory._enrich_neighbors``).
    Postcondition: the returned text explicitly names the required
    ``remember`` call shape (``write_class='deliberate'``, tags
    ``lesson`` + ``derived-src:<id>`` per source + the dossier's own
    ``marker`` for idempotence) so the LLM cannot silently drop
    provenance — mirrors ``curate_wiki``'s prompt convention of
    embedding the exact required tool call.
    """
    lines = [
        f"Distillation dossier ({dossier.kind}) — "
        f"topic: {dossier.topic or '(untitled)'}",
        "",
        "Sources (read these, then write the WHY, not the WHAT):",
    ]
    for mem in memory_previews:
        preview = (mem.get("content") or "")[:200].replace("\n", " ")
        lines.append(f"  - id={mem['id']} tags={mem.get('tags') or []}: {preview}")
    src_tags = " ".join(f"'derived-src:{mid}'" for mid in dossier.memory_ids)
    lines += [
        "",
        "Write ONE distilled lesson via `remember` if — and only if — these",
        "sources actually justify a durable, situated lesson (a root cause, a",
        "rule, a decision and its rationale). If they don't, skip this dossier.",
        "",
        "Required call shape:",
        "  remember(",
        "    content=<the lesson — WHY it happened / WHY the decision, not a",
        "             restatement of the source events>,",
        f"    tags=['lesson', '{dossier.marker}', {src_tags}],",
        "    write_class='deliberate',",
        "    source='distillation',",
        "  )",
        "",
        "The tag list MUST include this dossier's marker "
        f"('{dossier.marker}') so a future run does not re-offer the same "
        "dossier (idempotence), and one 'derived-src:<id>' per source "
        "memory above (provenance) — both conventions are read back by "
        "`curate_distill` and by the M-D6 lesson-promotion / M-D7 "
        "wiki-citation passes.",
    ]
    return "\n".join(lines)


def summarize_derived_usage(derived_memories: list[dict[str, Any]]) -> dict[str, Any]:
    """Day-0 usage baseline for ``memify_derive``'s machine-synthesized
    facts (M-D8 point 3: "conditionner son maintien à la mesure d'usage à
    30 jours").

    Precondition: ``derived_memories`` is every active memory carrying the
    ``derived`` tag (``store.get_memories_by_tag("derived", ...)``, the
    same tag ``memify_derive.py`` writes) — NOT the LLM-authored
    ``distilled`` lessons from this module, which carry ``lesson`` +
    ``write_class='deliberate'`` instead.
    Postcondition: returns aggregate ``useful_count``/``access_count``
    stats plus the raw count — a snapshot, not a verdict. The
    keep/retire decision requires re-running this at J+30 and comparing;
    this function only computes one snapshot, it does not persist
    anything or decide.
    """
    n = len(derived_memories)
    if n == 0:
        return {
            "count": 0,
            "total_access_count": 0,
            "total_useful_count": 0,
            "mean_useful_ratio": None,
        }
    total_access = sum(int(m.get("access_count") or 0) for m in derived_memories)
    total_useful = sum(int(m.get("useful_count") or 0) for m in derived_memories)
    return {
        "count": n,
        "total_access_count": total_access,
        "total_useful_count": total_useful,
        "mean_useful_ratio": (total_useful / total_access) if total_access else 0.0,
    }
