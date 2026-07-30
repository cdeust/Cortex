"""Stage-assembler integration point (issue #228 split, extracted from
``condensers.py``).

StageAwareContextAssembler (stage_assembler.py) allocates a per-phase token
sub-budget to each of own/adjacent/summaries independently (submodular
selection caps chunk count per phase), so the sum can still exceed the
caller's total token_budget: estimate_tokens is a heuristic (chars // 3),
and per-phase caps do not renegotiate against each other. pg_recall.
assemble_context() promises a "budgeted, slot-filled prompt with truncation
awareness" (module docstring) — this function is the truncation-awareness
step: it is the caller that was missing, wiring condense_memory_content +
assemble_prompt's priority-condensation into the one place that already
computes the three raw text blocks. (Original wiring: issue #196.)

Extracted from ``condensers.py`` (§4.1/§4.2 — the file was 391 lines, over
this repo's 300-line cap, and this function alone was 66 lines, over the
40-line cap) with zero behaviour change: the docstring below states the
same contract, split so the "how" of the over-budget path lives beside the
helper that implements it rather than in one 66-line body. See
``condensers.py`` for the shared module docstring and re-export facade.
"""

from __future__ import annotations

from mcp_server.core.context_assembly.budget import Placeholder, estimate_tokens
from mcp_server.core.context_assembly.condense_dispatch import condense_memory_content
from mcp_server.core.context_assembly.decomposer import assemble_prompt

# (header, content, priority, key) row shape shared by the two helpers
# below: priority mirrors StageAwareContextAssembler's own emphasis order
# (own > adjacent > summaries; lower number = more important = condensed
# last, decomposer.py semantics). Keys are human-readable so
# build_truncation_banner's warning lines (which label by raw placeholder
# key) name the actual section, not an opaque index.
_Section = tuple[str, str, int, str]


def condense_assembled_context(
    own_stage_context: str,
    adjacent_stage_context: str,
    stage_summaries: str,
    current_stage: str,
    token_budget: int,
) -> str:
    """Fit stage_assembler's three raw text blocks into ``token_budget``.

    Precondition: ``token_budget > 0``; the three text args are the raw
    (uncondensed) own/adjacent/summary blocks ``StageAwareContextAssembler
    .assemble()`` produced (``StageContextResult.own_stage_context`` etc.,
    not the already-headered ``assembled_context``).

    Postcondition: returns a single string with the same ``"## <Section>"``
    headers ``StageAwareContextAssembler`` uses, sections with empty
    content omitted. Within budget: byte-identical to the assembler's own
    concatenation (zero behavior change for the already-common case). Over
    budget: each section is priority-condensed (own > adjacent >
    summaries) via ``_condense_sections_over_budget`` — see that helper's
    docstring for the condensation caveats it inherits from
    ``decomposer.assemble_prompt``.
    """
    sections = _build_present_sections(
        own_stage_context, adjacent_stage_context, stage_summaries, current_stage
    )
    total = sum(estimate_tokens(c) for _h, c, _pr, _k in sections)
    if total <= token_budget:
        return "\n\n".join(f"{h}\n\n{c}" for h, c, _pr, _k in sections)
    return _condense_sections_over_budget(sections, token_budget)


def _build_present_sections(
    own_stage_context: str,
    adjacent_stage_context: str,
    stage_summaries: str,
    current_stage: str,
) -> list[_Section]:
    """Strip inputs and keep only the non-empty (header, content, priority,
    key) rows, in own/adjacent/summaries emphasis order."""
    own = own_stage_context.strip()
    adjacent = adjacent_stage_context.strip()
    summaries = stage_summaries.strip()

    # EQUIVALENT MUTANT (#196, re-confirmed #228): summaries' priority
    # 3 → 4. decomposer.assemble_prompt consumes `priority` only through
    # `sorted(..., key=lambda p: p.priority, reverse=True)` (decomposer.py
    # lines 119 and 156) — never as a magnitude. With ranks {1, 2, 3} and
    # {1, 2, 4} the descending order is byte-identical and no tie is
    # created or broken, so no input can distinguish the two.
    sections: list[_Section] = [
        (f"## Current Stage Context ({current_stage})", own, 1, "{{OWN_STAGE}}"),
        ("## Related Prior Context", adjacent, 2, "{{ADJACENT_STAGE}}"),
        ("## Stage Summaries", summaries, 3, "{{STAGE_SUMMARIES}}"),
    ]
    return [(h, c, pr, k) for h, c, pr, k in sections if c]


def _condense_sections_over_budget(sections: list[_Section], token_budget: int) -> str:
    """Route over-budget sections through assemble_prompt's priority
    condensation.

    Caveat inherited from ``assemble_prompt``: its truncation-warning
    banner is prepended *after* the condensation loop and is not itself
    counted against ``token_budget``, so the returned string (banner
    included) can exceed ``token_budget`` by the banner's own length.
    """
    template = "\n\n".join(f"{h}\n\n{k}" for h, _c, _pr, k in sections)
    placeholders = [
        Placeholder(k, c, priority=pr, condenser=condense_memory_content)
        for _h, c, pr, k in sections
    ]
    prompt, _metrics = assemble_prompt(
        template, placeholders, context_window=token_budget, headroom=1.0
    )
    return prompt
