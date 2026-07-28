"""Domain-aware condensers per Cortex memory type.

Each condenser reduces a piece of content to fit a token budget, using
domain knowledge of **what matters** for that content type. Generic
truncation loses the most important information first (it keeps the
first N tokens regardless of significance); domain-aware condensers
preserve high-signal content and drop filler.

Adapted from Clément Deust's Swift condensers in ContextDecomposer.swift
(`condenseContracts`, `condenseEngineGraph`, `condenseFileTree`,
`condenseImpactReport`), plus Cortex-specific memory types.
"""

from __future__ import annotations

import re

from mcp_server.core.context_assembly.budget import (
    estimate_tokens,
    truncate_to_budget,
)

# source: structural — the condenser keeps first + last sentence, so texts
# of two or fewer sentences have no middle filler to drop.
_FIRST_PLUS_LAST_SENTENCES = 2
# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_MIN_ARROWS_FOR_TRIPLES = 2
# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_MIN_INDENT_RUNS_FOR_CODE = 3


# ── User message condenser ──────────────────────────────────────────────
# Strategy: keep the first sentence (establishes intent), any questions
# (explicit interrogatives), and the last sentence (final state of
# thought), dropping middle filler.


def condense_user_message(text: str, token_budget: int) -> str:
    """Keep first sentence + questions + last sentence, within budget."""
    if estimate_tokens(text) <= token_budget:
        return text
    sentences = _split_sentences(text)
    if len(sentences) <= _FIRST_PLUS_LAST_SENTENCES:
        return truncate_to_budget(text, token_budget)

    kept: list[str] = [sentences[0]]
    for s in sentences[1:-1]:
        if "?" in s:
            kept.append(s)
    kept.append(sentences[-1])
    result = " ".join(kept).strip()
    if estimate_tokens(result) <= token_budget:
        return result
    return truncate_to_budget(result, token_budget)


# ── Assistant message condenser ─────────────────────────────────────────
# Strategy: keep code blocks verbatim (they're high-density facts that
# don't survive summarization), summarize prose by keeping topic
# sentences.


def condense_assistant_message(text: str, token_budget: int) -> str:
    """Preserve code blocks verbatim, compress prose between them."""
    if estimate_tokens(text) <= token_budget:
        return text

    parts = _split_by_code_blocks(text)
    # Parts alternate: prose, code, prose, code, ...
    # Priority: keep all code, compress prose.
    code_parts = [p for is_code, p in parts if is_code]
    prose_parts = [p for is_code, p in parts if not is_code]

    code_tokens = sum(estimate_tokens(p) for p in code_parts)
    if code_tokens >= token_budget:
        # Even the code exceeds budget — keep first N code blocks
        kept: list[str] = []
        used = 0
        for p in code_parts:
            t = estimate_tokens(p)
            if used + t > token_budget:
                break
            kept.append(p)
            used += t
        # A single block bigger than the whole budget keeps nothing, and
        # returning "" would delete the memory outright. Degrade to the
        # generic truncation the sibling condensers fall back to.
        if not kept:
            return truncate_to_budget(text, token_budget)
        return "\n\n".join(kept)

    prose_budget = token_budget - code_tokens
    if prose_parts and prose_budget > 0:
        per_prose = max(20, prose_budget // len(prose_parts))
        compressed_prose = [_first_sentence(p)[: per_prose * 3] for p in prose_parts]
        # Reassemble in original order
        out: list[str] = []
        pi = ci = 0
        for is_code, _ in parts:
            if is_code:
                if ci < len(code_parts):
                    out.append(code_parts[ci])
                    ci += 1
            else:
                if pi < len(compressed_prose):
                    out.append(compressed_prose[pi])
                    pi += 1
        joined = "\n\n".join(s for s in out if s.strip())
        return joined if joined else truncate_to_budget(text, token_budget)
    # No prose budget — just concatenate code.
    # NOTE (issue #196 coverage audit): prose_parts can only be empty
    # when _split_by_code_blocks returned a single segment — any closed
    # or re-opened fence emits the fence line into a following prose
    # segment, so two code segments always have a prose segment between
    # them. A single code segment IS the whole input text, so
    # code_tokens == estimate_tokens(text) exactly. The fast-path guard
    # at the top (`estimate_tokens(text) <= token_budget` returns early)
    # ensures we only reach here when estimate_tokens(text) >
    # token_budget — which, combined with the equality above, forces
    # code_tokens > token_budget, so the `code_tokens >= token_budget`
    # branch earlier in this function always returns first. This line is
    # provably unreachable through this function's own arithmetic; kept
    # (not deleted) as the correct fallback should a future edit to
    # _split_by_code_blocks break that single-segment invariant.
    return "\n\n".join(code_parts)  # pragma: no cover


# ── Entity-triple condenser ─────────────────────────────────────────────
# Strategy: keep (subject, predicate, object) triples verbatim, drop
# anything else. Triples are already maximally compressed.


def condense_entity_triples(text: str, token_budget: int) -> str:
    """Keep only lines matching triple patterns, in budget order."""
    if estimate_tokens(text) <= token_budget:
        return text
    triple_re = re.compile(
        r"^\s*([^→\->:]+?)\s*(?:→|->|:)\s*([^→\->:]+?)\s*(?:→|->|:)\s*(.+?)\s*$"
    )
    kept_lines: list[str] = []
    used = 0
    for line in text.split("\n"):
        if triple_re.match(line):
            t = estimate_tokens(line)
            if used + t > token_budget:
                break
            kept_lines.append(line)
            used += t
    if kept_lines:
        return "\n".join(kept_lines)
    return truncate_to_budget(text, token_budget)


# ── Timeline-event condenser ────────────────────────────────────────────
# Strategy: extract (when, what, who) slots. A fixed schema compresses an
# event more reliably than a free-text summary because the salient fields
# are pinned. (Engineering heuristic — no biological source.)


def condense_timeline_event(text: str, token_budget: int) -> str:
    """Extract when/what/who into a fixed-slot format within budget."""
    if estimate_tokens(text) <= token_budget:
        return text

    date_match = re.search(
        r"\[Date:\s*([^\]]+)\]|(\d{4}-\d{2}-\d{2})|"
        r"(\w+\s+\d{1,2},?\s+\d{4})",
        text,
    )
    date = (
        date_match.group(1) or date_match.group(2) or date_match.group(3)
        if date_match
        else ""
    )

    first = _first_sentence(text)
    compressed = f"[{date}] {first}" if date else first
    if estimate_tokens(compressed) <= token_budget:
        return compressed
    return truncate_to_budget(compressed, token_budget)


# ── Code block condenser ────────────────────────────────────────────────
# Strategy: signatures only (function/class/imports), same spirit as the
# Swift condenseContracts.


def condense_code_block(text: str, token_budget: int) -> str:
    """Keep imports, class, function, protocol, and method signatures only."""
    if estimate_tokens(text) <= token_budget:
        return text

    kept: list[str] = []
    used = 0
    signature_prefixes = (
        "import ",
        "from ",
        "class ",
        "def ",
        "async def ",
        "struct ",
        "enum ",
        "protocol ",
        "func ",
        "interface ",
        "@",  # decorators
        "//",  # comments
        "#",  # comments
    )
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if any(stripped.startswith(p) for p in signature_prefixes):
            t = estimate_tokens(line)
            if used + t > token_budget:
                break
            kept.append(line)
            used += t
    if kept:
        return "\n".join(kept)
    return truncate_to_budget(text, token_budget)


# ── Stage-assembler integration point ────────────────────────────────────
# StageAwareContextAssembler (stage_assembler.py) allocates a per-phase
# token sub-budget to each of own/adjacent/summaries independently
# (submodular selection caps chunk count per phase), so the sum can
# still exceed the caller's total token_budget: estimate_tokens is a
# heuristic (chars // 3), and per-phase caps do not renegotiate against
# each other. pg_recall.assemble_context() promises a "budgeted,
# slot-filled prompt with truncation awareness" (module docstring) —
# this function is the truncation-awareness step: it is the caller that
# was missing, wiring condense_memory_content + assemble_prompt's
# priority-condensation into the one place that already computes the
# three raw text blocks.


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
    content omitted (byte-identical formatting to the assembler's own
    concatenation). When the combined estimated token count of the three
    inputs is within ``token_budget``, the return value is exactly that
    header+concatenation (no condensation applied — zero behavior change
    for the already-common case). When it exceeds ``token_budget``, each
    section is priority-condensed (own > adjacent > summaries, matching
    ``StageAwareContextAssembler``'s own emphasis order) via
    ``condense_memory_content`` through ``decomposer.assemble_prompt``'s
    progressive-condensation + post-assembly safety loop, so the
    condensed *content* is within ``token_budget`` up to that loop's
    fixed safety margin. Caveat inherited from ``assemble_prompt``: its
    truncation-warning banner is prepended *after* that loop and is not
    itself counted against the budget, so the returned string (banner
    included) can exceed ``token_budget`` by the banner's own length.
    """
    own = own_stage_context.strip()
    adjacent = adjacent_stage_context.strip()
    summaries = stage_summaries.strip()

    # (header, content, priority, key) — priority mirrors StageAware
    # ContextAssembler's own emphasis order (own > adjacent > summaries);
    # lower number = more important = condensed last (decomposer.py
    # semantics). Keys are human-readable so build_truncation_banner's
    # warning lines (which label by raw placeholder key) name the actual
    # section, not an opaque index.
    sections = [
        (f"## Current Stage Context ({current_stage})", own, 1, "{{OWN_STAGE}}"),
        ("## Related Prior Context", adjacent, 2, "{{ADJACENT_STAGE}}"),
        ("## Stage Summaries", summaries, 3, "{{STAGE_SUMMARIES}}"),
    ]
    present = [(h, c, pr, k) for h, c, pr, k in sections if c]

    total = sum(estimate_tokens(c) for _h, c, _pr, _k in present)
    if total <= token_budget:
        return "\n\n".join(f"{h}\n\n{c}" for h, c, _pr, _k in present)

    # Late import: decomposer depends on budget only, condensers depends
    # on budget only — importing decomposer here (not at module scope)
    # keeps condensers.py's own import graph unchanged for every caller
    # that never hits the over-budget path.
    from mcp_server.core.context_assembly.budget import Placeholder
    from mcp_server.core.context_assembly.decomposer import assemble_prompt

    template = "\n\n".join(f"{h}\n\n{k}" for h, _c, _pr, k in present)
    placeholders = [
        Placeholder(k, c, priority=pr, condenser=condense_memory_content)
        for _h, c, pr, k in present
    ]
    prompt, _metrics = assemble_prompt(
        template, placeholders, context_window=token_budget, headroom=1.0
    )
    return prompt


# ── Generic memory condenser ────────────────────────────────────────────
# Strategy: dispatch by content shape. When unsure, truncate.


def condense_memory_content(
    content: str,
    token_budget: int,
    *,
    tags: list[str] | None = None,
) -> str:
    """Auto-dispatch to the right condenser based on content shape.

    Args:
        content: the memory's textual content.
        token_budget: target token count for the output.
        tags: optional tag hints (e.g. ["code", "decision"]) to bias
            dispatch. When provided, takes precedence over heuristic.
    """
    if estimate_tokens(content) <= token_budget:
        return content

    tags = tags or []

    # Tag-driven dispatch first
    if "code" in tags or "file" in tags:
        return condense_code_block(content, token_budget)
    if "timeline" in tags or "event" in tags:
        return condense_timeline_event(content, token_budget)

    # Heuristic dispatch by content shape
    if _has_code_blocks(content):
        return condense_assistant_message(content, token_budget)
    if content.count("→") + content.count("->") >= _MIN_ARROWS_FOR_TRIPLES:
        return condense_entity_triples(content, token_budget)
    if content.lstrip().startswith("[user]:") or content.lstrip().startswith(
        "[assistant]:"
    ):
        # Cortex memory format
        if "[assistant]:" in content:
            return condense_assistant_message(content, token_budget)
        return condense_user_message(content, token_budget)

    # Default: treat as prose user message
    return condense_user_message(content, token_budget)


# ── Helpers ─────────────────────────────────────────────────────────────


def _split_sentences(text: str) -> list[str]:
    """Naive sentence splitter; good enough for condensers."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p]


def _first_sentence(text: str) -> str:
    sents = _split_sentences(text)
    return sents[0] if sents else text


def _has_code_blocks(text: str) -> bool:
    return "```" in text or text.count("    ") >= _MIN_INDENT_RUNS_FOR_CODE


def _split_by_code_blocks(text: str) -> list[tuple[bool, str]]:
    """Split markdown-style text into (is_code, chunk) segments."""
    segments: list[tuple[bool, str]] = []
    in_code = False
    buf: list[str] = []
    for line in text.split("\n"):
        if line.strip().startswith("```"):
            if buf:
                segments.append((in_code, "\n".join(buf)))
                buf = []
            in_code = not in_code
            buf.append(line)
        else:
            buf.append(line)
    if buf:
        segments.append((in_code, "\n".join(buf)))
    return segments
