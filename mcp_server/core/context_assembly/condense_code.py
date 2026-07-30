"""Condensers for code-shaped content (issue #228 split 2/4).

Extracted from ``condensers.py`` (§4.1 — the original file was 391 lines,
over this repo's 300-line cap) with zero behaviour change. See
``condensers.py`` for the shared module docstring and re-export facade.

Covers the code-block condenser (signatures only) and the assistant-message
condenser (verbatim code, compressed prose in between), plus the private
fence-splitting helpers both of them and the dispatcher depend on.
"""

from __future__ import annotations

from mcp_server.core.context_assembly.budget import (
    estimate_tokens,
    truncate_to_budget,
)
from mcp_server.core.context_assembly.condense_text import _first_sentence

# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_MIN_INDENT_RUNS_FOR_CODE = 3


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
        return _keep_leading_code_blocks(code_parts, token_budget, text)

    # DEAD CODE REMOVED (issue #228): both operands of the guard that used
    # to sit here — `prose_parts and prose_budget > 0` — are provably true
    # at this point, so the guard and its "concatenate code only" fallback
    # were a branch no input could reach. The scoped mutmut run proved it
    # empirically: every mutant of that fallback survived (§12.1 — the
    # signature of dead code). Proof:
    #   (a) prose_budget > 0: reaching here means the `code_tokens >=
    #       token_budget` branch above did NOT return, so code_tokens <
    #       token_budget, i.e. token_budget - code_tokens > 0.
    #   (b) prose_parts is non-empty: it can only be empty when
    #       _split_by_code_blocks returns a single segment tagged as code
    #       (any closed or re-opened fence emits the fence line into a
    #       following prose segment — pinned by
    #       test_split_by_code_blocks_segments_preserve_original_newlines).
    #       A single segment IS the whole input text, so code_tokens ==
    #       estimate_tokens(text), which the fast-path guard at the top of
    #       this function already established exceeds token_budget — i.e.
    #       (a) would have returned first. Pinned by
    #       test_assistant_unclosed_fence_is_a_single_code_segment.
    prose_budget = token_budget - code_tokens
    compressed_prose = _compress_prose_parts(prose_parts, prose_budget)
    joined = _reassemble_in_order(parts, code_parts, compressed_prose)
    return joined if joined else truncate_to_budget(text, token_budget)


def _keep_leading_code_blocks(
    code_parts: list[str], token_budget: int, text: str
) -> str:
    """Even the code exceeds budget — keep first N code blocks that fit.

    A single block bigger than the whole budget keeps nothing, and
    returning "" would delete the memory outright. Degrade to the generic
    truncation the sibling condensers fall back to.
    """
    kept: list[str] = []
    used = 0
    for p in code_parts:
        t = estimate_tokens(p)
        if used + t > token_budget:
            break
        kept.append(p)
        used += t
    if not kept:
        return truncate_to_budget(text, token_budget)
    return "\n\n".join(kept)


def _compress_prose_parts(prose_parts: list[str], prose_budget: int) -> list[str]:
    """Cut each prose segment to its first sentence, floored per-segment."""
    per_prose = max(20, prose_budget // len(prose_parts))
    return [_first_sentence(p)[: per_prose * 3] for p in prose_parts]


def _reassemble_in_order(
    parts: list[tuple[bool, str]],
    code_parts: list[str],
    compressed_prose: list[str],
) -> str:
    """Interleave verbatim code and compressed prose back into source order."""
    out: list[str] = []
    pi = ci = 0
    for is_code, _ in parts:
        if is_code:
            # EQUIVALENT MUTANT (#228): `ci < len(code_parts)` → `<=`. ci is
            # incremented exactly once per is_code segment and code_parts is
            # built from those same segments, so ci < len(code_parts) holds
            # on every entry; both comparisons are unconditionally true and
            # no input can distinguish them. Same for `pi` below.
            if ci < len(code_parts):
                out.append(code_parts[ci])
                ci += 1
        else:
            if pi < len(compressed_prose):
                out.append(compressed_prose[pi])
                pi += 1
    return "\n\n".join(s for s in out if s.strip())


# ── Helpers ─────────────────────────────────────────────────────────────


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
