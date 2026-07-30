"""Source / reality monitoring (C1) — attribute a memory's epistemic origin.

Remembering *where* a memory came from — did I perceive it, was I told it, or
did I infer it? — is a distinct, decision-based attribution process, separate
from remembering the content itself. Its failure is the mechanism of
confabulation: an internally-generated (inferred) memory misattributed to an
external source is a hallucinated fact presented as observed truth. Cortex has
no such check today: the `source` column records the ingestion *pathway*
(session / import / post_tool_capture), not the epistemic *origin*, so an
inferred claim and a file-grounded observation are indistinguishable downstream.

Neuroscience basis (DOIs verified against Crossref):
  - Johnson & Raye (1981), "Reality monitoring," Psychological Review 88:67-85
    (doi:10.1037/0033-295X.88.1.67). Perceived vs. self-generated memories are
    told apart by their characteristic features: externally-derived memories
    carry more perceptual/contextual detail; internally-generated ones carry
    traces of the cognitive operations that produced them.
  - Johnson, Hashtroudi & Lindsay (1993), "Source monitoring," Psychological
    Bulletin 114:3-28 (doi:10.1037/0033-2909.114.1.3). Source attribution is a
    decision process over those features — heuristic (fast, feature-weighted)
    or systematic — and its threshold trades false-observed against
    false-inferred errors.

Design (pure business logic — no I/O). A memory's text + metadata are scored on
two competing feature families and mapped to a source attribution:

  PERCEIVED  — grounded in verifiable external references (file paths, URLs,
               commit SHAs, citations/DOIs, tool-output markers). Johnson's
               "perceptual detail" proxy: these are the traces an external
               source leaves.
  TOLD       — explicitly attributed to the user / a stated instruction
               ("you said", "the user wants", "per your", "as requested").
  INFERRED   — dominated by cognitive-operation markers ("I think",
               "probably", "presumably", "this suggests", "seems to") with no
               external grounding. Johnson's "cognitive operations" trace.

The output is an attribution + a confidence, plus a GATE
(``violates_source_claim``) that fires when a memory asserts an observed source
but shows no perceptual grounding — the confabulation guard the feasibility
analysis called the highest-leverage cheap win.

Honesty note (zetetic standard, matching value_learning.py / procedural_memory.py):
this is a transparent, feature-weighted heuristic classifier — the "heuristic
judgement" branch of Johnson 1993, not the systematic/deliberative one, and not
a trained model. It scores lexical + reference features the store already has;
it does not verify that a cited file or URL actually exists (that is
validate_memory's job) — it checks only whether the memory *claims* external
grounding consistent with its asserted source. The three-way scheme
(perceived/told/inferred) maps Johnson's perceived-vs-self-generated axis onto
the evidence tags Cortex already reasons about (observed/stated/inferred).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── Source attributions ─────────────────────────────────────────────────────
PERCEIVED = "perceived"  # externally grounded (file/url/commit/citation/tool)
TOLD = "told"  # user-stated / instruction
INFERRED = "inferred"  # self-generated reasoning, no external grounding
UNKNOWN = "unknown"  # no discriminating signal either way

# Map an attribution to the store's evidence-tag vocabulary (observed/stated/
# inferred), so C1 output is commensurate with the tags the rest of the system
# reasons about. PERCEIVED -> observed (saw it), TOLD -> stated (was told it),
# INFERRED -> inferred (concluded it).
EVIDENCE_TAG = {
    PERCEIVED: "observed",
    TOLD: "stated",
    INFERRED: "inferred",
    UNKNOWN: "inferred",  # conservative: unproven origin is treated as inferred
}

# ── Feature patterns ────────────────────────────────────────────────────────
# Perceptual grounding — verifiable external references (the traces an external
# source leaves; mirrors claim_extractor._extract_evidence kinds).
_URL_RE = re.compile(r"https?://\S+")
_DOI_RE = re.compile(r"\b10\.\d{4,9}/\S+\b", re.IGNORECASE)
_FILE_RE = re.compile(
    r"\b[\w./-]+\.(?:py|js|ts|md|json|yaml|yml|toml|tex|sql|txt|rs|go|java|c|cpp|h)\b"
)
_SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b")
_TOOL_RE = re.compile(
    r"\b(?:tool[_\s]?output|stdout|stderr|returned|the output (?:was|shows)|"
    r"grep|read_file|ran|executed|command output)\b",
    re.IGNORECASE,
)

# "Told" markers — explicit attribution to the user / a stated instruction.
_TOLD_RE = re.compile(
    r"\b(?:you (?:said|told|asked|want|mentioned|requested|specified)|"
    r"the user (?:said|wants|asked|requested|specified|prefers)|"
    r"per your|as requested|as you|according to you|you'd like|you prefer)\b",
    re.IGNORECASE,
)

# Cognitive-operation markers — the trace of internally-generated content
# (Johnson: memories of thoughts carry markers of the operations that made them).
_INFER_RE = re.compile(
    r"\b(?:i think|i believe|i (?:would )?(?:guess|assume|suspect|expect)|"
    r"probably|presumably|likely|seems? (?:to|like)|appears? to|"
    r"this (?:suggests|implies|means)|it (?:follows|seems)|"
    r"my (?:guess|hypothesis|assumption)|(?:i )?infer|perhaps|maybe|"
    r"could be|might be|so it should|therefore)\b",
    re.IGNORECASE,
)


@dataclass
class SourceJudgement:
    """A source-monitoring attribution for one memory.

    ``attribution``      — PERCEIVED | TOLD | INFERRED | UNKNOWN.
    ``confidence``       — [0,1] margin of the winning family over the runner-up.
    ``evidence_tag``     — store-vocabulary tag (observed/stated/inferred).
    ``perceptual_score`` — count of external-grounding features.
    ``told_score``       — count of user-attribution features.
    ``inferred_score``   — count of cognitive-operation markers.
    ``grounding_refs``   — the concrete external references found (for audit).
    """

    attribution: str
    confidence: float
    evidence_tag: str
    perceptual_score: int
    told_score: int
    inferred_score: int
    grounding_refs: list[str] = field(default_factory=list)


def source_judgement_as_dict(judgement: "SourceJudgement") -> dict:
    """A free function, not a method: mutmut categorically excludes the
    body of any `@dataclass`-decorated class (`mutmut/mutation/
    file_mutation.py:236`), so logic placed on `SourceJudgement` methods
    would carry zero mutation coverage no matter how the test loader names
    the module (issue #262 3rd pass; issue #282).
    """
    return {
        "attribution": judgement.attribution,
        "confidence": round(judgement.confidence, 4),
        "evidence_tag": judgement.evidence_tag,
        "perceptual_score": judgement.perceptual_score,
        "told_score": judgement.told_score,
        "inferred_score": judgement.inferred_score,
        "grounding_refs": judgement.grounding_refs[:10],
    }


# ── Feature extraction ──────────────────────────────────────────────────────
# source: structural — git abbreviates object names to 7 hex chars by default
# (git-rev-parse --short), and a full SHA-1 hex digest is 40 chars; tokens
# outside that range cannot be commit hashes.
_GIT_SHORT_SHA_LEN = 7
_GIT_FULL_SHA_LEN = 40


def extract_grounding(content: str) -> list[str]:
    """Return the verifiable external references in ``content`` (Johnson's
    perceptual-detail proxy): URLs, DOIs, file paths, commit SHAs."""
    refs: list[str] = []
    text = content or ""
    for rx in (_URL_RE, _DOI_RE, _FILE_RE):
        refs.extend(m.group(0) for m in rx.finditer(text))
    # SHAs are noisy (any hex run) — only count them as grounding when they look
    # like commit hashes standing alone, not embedded in longer tokens.
    for m in _SHA_RE.finditer(text):
        tok = m.group(0)
        if _GIT_SHORT_SHA_LEN <= len(tok) <= _GIT_FULL_SHA_LEN and (not tok.isdigit()):
            refs.append(tok)
    # de-dup preserving order
    seen: set[str] = set()
    out: list[str] = []
    for r in refs:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


# ── The source-monitoring decision (Johnson 1993 heuristic branch) ──────────
def classify_source(
    content: str, *, source_field: str | None = None
) -> SourceJudgement:
    """Attribute a memory's epistemic origin from its text (+ optional ingestion
    ``source`` field). Feature-weighted heuristic judgement (Johnson 1993).

    A ``source_field`` that is itself a strong external-pathway signal (e.g.
    ``post_tool_capture``, ``ingest_codebase``, ``import``) counts as one unit of
    perceptual grounding — those pathways are, by construction, externally
    sourced.
    """
    text = content or ""
    grounding = extract_grounding(text)
    tool_hit = 1 if _TOOL_RE.search(text) else 0
    told_score = len(_TOLD_RE.findall(text))
    inferred_score = len(_INFER_RE.findall(text))

    perceptual_score = len(grounding) + tool_hit
    if source_field and _is_external_pathway(source_field):
        perceptual_score += 1

    scores = {
        PERCEIVED: perceptual_score,
        TOLD: told_score,
        INFERRED: inferred_score,
    }
    winner = max(scores, key=lambda k: scores[k])
    top = scores[winner]

    if top == 0:
        # No discriminating feature in either direction.
        return SourceJudgement(
            attribution=UNKNOWN,
            confidence=0.0,
            evidence_tag=EVIDENCE_TAG[UNKNOWN],
            perceptual_score=perceptual_score,
            told_score=told_score,
            inferred_score=inferred_score,
            grounding_refs=grounding,
        )

    runner_up = max(v for k, v in scores.items() if k != winner)
    # Confidence = normalized margin of the winner over the runner-up.
    confidence = (top - runner_up) / (top + runner_up) if (top + runner_up) else 0.0

    return SourceJudgement(
        attribution=winner,
        confidence=confidence,
        evidence_tag=EVIDENCE_TAG[winner],
        perceptual_score=perceptual_score,
        told_score=told_score,
        inferred_score=inferred_score,
        grounding_refs=grounding,
    )


# ── The confabulation gate ──────────────────────────────────────────────────
def violates_source_claim(
    content: str,
    claimed_source_tag: str,
    *,
    source_field: str | None = None,
) -> bool:
    """True iff a memory ASSERTS an observed/perceived origin but shows no
    perceptual grounding — the reality-monitoring failure that produces
    confabulation (Johnson & Raye 1981).

    ``claimed_source_tag`` is the evidence tag the memory is being written /
    promoted with (observed/perceived/stated/inferred). The gate fires only for
    an *observed* claim that the content cannot support; it never blocks an
    inferred or stated claim (those make no external-grounding promise).
    """
    claim = (claimed_source_tag or "").strip().lower()
    if claim not in ("observed", "perceived"):
        return False  # only an observed-source claim can be a reality-monitoring error
    judgement = classify_source(content, source_field=source_field)
    # Violation: claims observed, but the evidence points to inferred and there
    # is no perceptual grounding at all.
    return judgement.attribution == INFERRED and judgement.perceptual_score == 0


# ── Read-side enforcement: consolidation-promotion gate ─────────────────────
# Semantic-knowledge crystallization is the honest call site for the
# confabulation gate. The write-path `source` is an ingestion *pathway*, not an
# epistemic claim, so gating at write time would be wrong (that was the reason
# C1's gate was held with no call site). But when a cluster of episodic memories
# is abstracted into a NEW ``store_type='semantic'`` memory (consolidation_engine
# ._try_abstract_pattern → cls._create_semantic_memories), the system IS making
# an epistemic claim: "this recurring observation is now general knowledge/fact."
# That is precisely Johnson & Raye's (1981) reality-monitoring failure when the
# underlying evidence is internally generated (inferred) with no external
# grounding — a confabulation being crystallized as fact.
def promotion_confabulation_risk(cluster_memories: list[dict]) -> bool:
    """True iff promoting ``cluster_memories`` to a semantic fact would
    crystallize a confabulation — the combined cluster content classifies as
    INFERRED with zero perceptual grounding (Johnson & Raye 1981).

    A semantic promotion is an implicit *observed/known-fact* claim (the cluster
    is being asserted as general knowledge), so the check is exactly
    ``violates_source_claim(combined_content, "observed")`` over the cluster's
    combined text. Returns False for an empty cluster (nothing to promote) and
    for any cluster whose combined evidence shows perceptual grounding or a
    told/perceived lean — those are legitimately promotable.

    This is a per-cluster *flag*, not a drop: the caller annotates the risky
    promotion (see consolidation_engine._process_patterns) and MAY still create
    the semantic memory. Non-fatal by construction — reality monitoring surfaces
    the risk, it does not silently discard a candidate abstraction.
    """
    if not cluster_memories:
        return False
    combined = " ".join(str(m.get("content", "") or "") for m in cluster_memories)
    return violates_source_claim(combined, "observed")


# ── Read-side surfacing: per-hit recall confabulation risk ──────────────────
def recall_confabulation_risk(
    content: str,
    source_attribution: str | None,
) -> bool:
    """True iff a recalled memory's own stored attribution claims an
    externally-grounded origin (perceived) that its content cannot support.

    Used to annotate each recall hit with a ``confabulation_risk`` flag so a
    consumer of recall sees provenance risk per result. The stored
    ``source_attribution`` (set at write time from ``classify_source``) is the
    memory's asserted origin; the gate re-checks the content against that claim.
    Fires only when the memory was stored as PERCEIVED but the content now
    classifies as INFERRED with zero perceptual grounding — the same
    reality-monitoring failure as ``violates_source_claim``, evaluated against
    the memory's OWN recorded claim rather than a write-time parameter.

    A memory stored as inferred/told/unknown makes no external-grounding promise
    and is never flagged. Purely informational: it changes no ordering and drops
    no result.
    """
    attribution = (source_attribution or "").strip().lower()
    # Only a perceived-origin claim can be a reality-monitoring error; the
    # store's PERCEIVED maps to the "observed" claim vocabulary of the gate.
    if attribution != PERCEIVED:
        return False
    return violates_source_claim(content or "", "observed")


# ── Helpers ─────────────────────────────────────────────────────────────────
# Ingestion pathways that are externally sourced by construction.
_EXTERNAL_PATHWAYS = frozenset(
    {
        "post_tool_capture",
        "ingest_codebase",
        "ingest_prd",
        "ingest_findings",
        "import",
        "seed_project",
    }
)


def _is_external_pathway(source_field: str) -> bool:
    return (source_field or "").strip().lower() in _EXTERNAL_PATHWAYS
