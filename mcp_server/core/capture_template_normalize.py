"""Pure normalization of auto-capture/derived-fact template boilerplate,
applied ONLY to the write-gate's NOVELTY DECISION (embedding-novelty
re-scoring and structural-novelty features) — never to the content that
gets stored, and never to the ``embedding`` column written by
``remember()``.

Decision: M-D1 (docs design "memoire qui comprend", section 7.3).

Scope narrowed by incident i7d3 (2026-07-11): the original M-D1 design
also normalized the STORED embedding (``remember.py``'s
``emb_engine.encode()`` call) and shipped a one-shot corpus backfill.
That stored-embedding path was measured to correlate with a LongMemEval
regression (MRR -0.05 to -0.13 across three runs, R@10 near floor —
a ranking-degradation profile) in a shared, contended benchmark
environment; root-cause investigation could not conclusively separate
"caused by this code" from "caused by a benchmark-container concurrency
hole" (the pure baseline on unmodified code regressed WORSE in the same
window, which argues against this code being the cause — but the
ambiguity itself was disqualifying under the zero-tolerance bench gate).
Per the tolerance-zero rule (rework or abandon, never negotiate), the
stored-embedding path was reverted (``remember.py`` and
``remember_helpers._do_merge`` both encode raw ``content`` again, exactly
as before M-D1) and the corpus backfill tooling was deleted. This module
is now wired ONLY into ``remember_helpers.compute_template_normalized_
similarities`` (embedding-novelty signal) and ``evaluate_gate``'s
structural-novelty call — both are write-gate DECISION inputs, computed
fresh at gate-evaluation time and discarded; neither ever reaches
storage or the recall vector space. This makes the mechanism
bench-neutral BY CONSTRUCTION, not just "not exercised by this
benchmark": grep confirms zero remaining callers of this module touch
the ``embedding`` column.

Fact base (measured, i6d2 campaign, docs/campaigns/i6d2_near_dup_calibration_report.md):
the auto-capture template built by
``mcp_server.hooks.post_tool_capture._build_memory_content`` — a fixed
``# Tool: X`` header, a labeled reference line (``**Read:** ...``,
``**File:** ...``, ``**Command:** ...``, ``**Glob:** ...``,
``**Grep:** ...``), an ``## Output`` / ``**Output:**`` section label, code
fence delimiters, and an optional ``**Artifact:** ...`` pointer line —
drives cosine similarity to 0.95-0.99 between memories that reference
DIFFERENT entities (worst offender: pairs of ``**Read:**
`.../checkpoints/<uuid>.md``` differing only by UUID). At every
candidate threshold (0.75-0.95) measured precision was 0.02-0.10 — the
TEMPLATE, not the fact, drives the embedding.

The derived-fact template written by
``mcp_server.core.curation.identify_derivable_facts`` (memify_derive,
INC6.1b) — ``"{src} and {tgt} are strongly linked ({type},
weight={w})"`` — is the same failure in miniature: the connective text
is shared by every derived fact, so distinct entity pairs collide in
embedding space (measured: 0 derived facts ever survived the write
gate, 20/20 rejected).

Design constraint (append-only, Q3 arbitration): the STORED content is
never mutated, and — post i7d3 — neither is the STORED embedding. Only
transient strings handed to ``EmbeddingEngine.encode()`` for a gate
DECISION, and to ``_structural_features``, ever pass through this
function. This module is therefore pure (core layer, stdlib-only, zero
I/O) and idempotent — running it twice produces the same output as
running it once, because the stripped skeleton markers no longer match
on the second pass.

Safety gate: the function only transforms content that matches one of
the two known templates byte-for-byte at the structural-marker level.
Deliberate memories and free-form notes are returned UNCHANGED. Because
no stored vector is ever touched (post i7d3), there is no write/read
vector-space coherence question left to reason about for the recall
path — the read-side query embedding (``recall_helpers.py``) and the
stored embedding column are BOTH always raw content, exactly as before
this module existed. The only remaining consumer of this function's
output is the write gate's own novelty arithmetic, computed fresh and
discarded every call.
"""

from __future__ import annotations

import re

# ── Auto-capture template markers
# (hooks/post_tool_capture.py::_build_memory_content) ──

_AUTO_CAPTURE_HEADER_RE = re.compile(r"^# Tool: \S")

_TOOL_HEADER_LINE_RE = re.compile(r"^# Tool: \S+[ \t]*$\n?", re.MULTILINE)
# Labeled reference line prefixes — strip the LABEL, keep the payload
# (file path / command / pattern) that follows it. Stripping the payload
# too would destroy the only signal that distinguishes two captures of
# the same tool kind (out of scope for M-D1 — see decision doc §1.3,
# "payload collision" is a separate, deferred, read-path concern).
_LABELED_REF_PREFIX_RE = re.compile(
    r"^\*\*(?:File|Command|Read|Glob|Grep):\*\*[ \t]*", re.MULTILINE
)
_OUTPUT_SECTION_HEADER_RE = re.compile(r"^## Output[ \t]*$\n?", re.MULTILINE)
_OUTPUT_LABEL_LINE_RE = re.compile(r"^\*\*Output:\*\*[ \t]*$\n?", re.MULTILINE)
# The artifact pointer line is pure boilerplate (content-addressed path +
# char count) with no fact-level payload — dropped entirely.
_ARTIFACT_POINTER_LINE_RE = re.compile(r"^\*\*Artifact:\*\*.*$\n?", re.MULTILINE)
_FENCE_DELIMITER_LINE_RE = re.compile(r"^```[\w-]*[ \t]*$\n?", re.MULTILINE)
_BLANK_RUN_RE = re.compile(r"\n{3,}")

# ── Derived-fact template marker (core/curation.py::identify_derivable_facts) ──

_DERIVED_FACT_RE = re.compile(
    r"^(?P<src>.+?) and (?P<tgt>.+?) are strongly linked "
    r"\((?P<rel_type>[^,]+), weight=(?P<weight>[\d.]+)\)$"
)


def is_auto_capture_template(content: str) -> bool:
    """True when ``content`` was built by ``_build_memory_content``.

    Precondition: none. Postcondition: True iff the FIRST non-blank line
    matches the fixed ``# Tool: <name>`` header emitted by the PostToolUse
    hook — the one structural invariant every auto-capture shares
    regardless of tool kind or payload.
    """
    if not content:
        return False
    return bool(_AUTO_CAPTURE_HEADER_RE.match(content.lstrip()))


def is_derived_fact_template(content: str) -> bool:
    """True when ``content`` is a memify-derive relationship sentence."""
    if not content:
        return False
    return bool(_DERIVED_FACT_RE.match(content.strip()))


def _normalize_auto_capture(content: str) -> str:
    text = _TOOL_HEADER_LINE_RE.sub("", content)
    text = _ARTIFACT_POINTER_LINE_RE.sub("", text)
    text = _OUTPUT_SECTION_HEADER_RE.sub("", text)
    text = _OUTPUT_LABEL_LINE_RE.sub("", text)
    text = _LABELED_REF_PREFIX_RE.sub("", text)
    text = _FENCE_DELIMITER_LINE_RE.sub("", text)
    text = _BLANK_RUN_RE.sub("\n\n", text)
    return text.strip()


def _normalize_derived_fact(content: str) -> str:
    m = _DERIVED_FACT_RE.match(content.strip())
    if m is None:
        # Caller already checked is_derived_fact_template; an explicit
        # raise (not `assert`, S101) so this internal-contract check is
        # never silently stripped by `python -O`.
        raise AssertionError(  # noqa: TRY003 — one-off internal-invariant message, not reused (§3.3)
            "_normalize_derived_fact called on a non-matching template"
        )
    return (
        f"{m.group('src')} {m.group('tgt')} {m.group('rel_type')} {m.group('weight')}"
    )


def capture_template_normalize(content: str) -> str:
    """Strip auto-capture / derived-fact template skeleton before embedding.

    Contract:
      pre:  ``content`` is the RAW string that would otherwise be passed to
            ``EmbeddingEngine.encode()`` or to ``_structural_features``.
      post: if ``content`` matches the auto-capture header or the
            derived-fact connective sentence, returns the payload with the
            template skeleton removed (never the empty string — falls back
            to the original ``content`` if stripping the skeleton would
            leave nothing, so a representation is always produced).
            Otherwise returns ``content`` unchanged (deliberate memories
            and free-form notes are never touched).
      invariant: idempotent — ``f(f(x)) == f(x)`` for all ``x``, because
            the stripped markers no longer match the normalized output on
            a second pass.
    """
    if not content:
        return content
    if is_derived_fact_template(content):
        return _normalize_derived_fact(content)
    if not is_auto_capture_template(content):
        return content
    normalized = _normalize_auto_capture(content)
    return normalized if normalized else content
