"""Phase 2.1 — Claim extraction from raw memory content.

Deterministic, pattern-based extractor that turns a memory's content
into a list of typed ClaimEvents (Hopper IR layer 1).

Pure logic — no I/O, no LLM calls. The LLM-augmented refinement step
lives in a separate handler that wraps this with prompt-driven
enrichment when needed.

The extractor splits content into candidate sentences, classifies each
by pattern matching against eight ClaimType buckets, and pulls out
evidence references (file paths, URLs, citations, commit SHAs).

Sentences that match no pattern are dropped — silent rejection is the
default, mirroring the wiki classifier's positive-signal philosophy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from mcp_server.shared.wiki_ir import ClaimEvent, ClaimType, EvidenceRef


# ── Sentence splitter ────────────────────────────────────────────────
#
# Naïve enough to be deterministic, smart enough to handle markdown
# structure (don't split inside fenced code blocks; treat list items
# and headings as their own sentences).

_FENCE_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\[\(\#\*\d])")


def _strip_code_fences(text: str) -> str:
    """Remove fenced code blocks before sentence-splitting."""
    return _FENCE_RE.sub("", text)


def _split_sentences(content: str) -> list[str]:
    """Split content into candidate sentences for classification."""
    cleaned = _strip_code_fences(content)
    # Split on blank lines first → paragraphs, then on sentence terminators
    paragraphs = re.split(r"\n\s*\n", cleaned)
    sentences: list[str] = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        # Headings, list items, and short paras are atomic sentences
        if (
            para.startswith("#")
            or re.match(r"^\s*[-*+]\s", para)
            or re.match(r"^\s*\d+[.)]\s", para)
            or len(para) < 120
        ):
            sentences.append(para.strip("#").strip("- *+").strip())
            continue
        # Long paragraphs — split on sentence terminators
        for s in _SENTENCE_END.split(para):
            s = s.strip()
            if s:
                sentences.append(s)
    return [s for s in sentences if 12 <= len(s) <= 1500]


# ── Claim-type pattern matchers ──────────────────────────────────────
#
# Each (pattern, claim_type, base_confidence) tuple. Higher weight
# patterns fire first; first match wins.

_CLAIM_PATTERNS: list[tuple[re.Pattern, ClaimType, float]] = [
    # decisions
    (
        re.compile(
            r"\b(decided to|decision[: ]|the decision is|chose .+ because"
            r"|chose .+ over|will use|we will|adopted|rejected .+ (because|due to)"
            r"|selected .+ over|switched (to|from))\b",
            re.IGNORECASE,
        ),
        "decision",
        0.85,
    ),
    # methods
    (
        re.compile(
            r"\b(uses?|implemented (via|using|with|by)|driven by|built (on|with)"
            r"|relies on|backed by|powered by|leverages|invokes|computes via"
            r"|approach[: ]|method[: ])\b",
            re.IGNORECASE,
        ),
        "method",
        0.7,
    ),
    # results / measurements
    (
        re.compile(
            r"\b(achieved|achieves|measured|benchmark(?:ed|s)?|score(?:d|s)?"
            r"|got|reached|improved (to|by|from)|regressed (to|by|from)|recall|MRR|"
            r"R@\d+|nDCG|F1|accuracy|latency|throughput|p\d{2})\b"
            r"|\b\d+(?:\.\d+)?\s*%|\b0\.\d+\b",
            re.IGNORECASE,
        ),
        "result",
        0.75,
    ),
    # limitations
    (
        re.compile(
            r"\b(does not (handle|support|work)|doesn[''']t (handle|support|work)"
            r"|fails (when|on|if)|broke (when|on|if)|breaks (when|on|if)"
            r"|limitation\b|known issue|cannot|can[''']t|unable to"
            r"|edge case|caveat\b|TODO|FIXME|XXX)",
            re.IGNORECASE,
        ),
        "limitation",
        0.8,
    ),
    # observations / findings
    (
        re.compile(
            r"\b(noticed that|noticed|found that|discovered|observed|surprising(?:ly)?"
            r"|turns out|it appears|it seems|interesting(?:ly)?|the (issue|problem|bug) (was|is))\b",
            re.IGNORECASE,
        ),
        "observation",
        0.65,
    ),
    # questions
    (
        re.compile(r"\?\s*$"),
        "question",
        0.6,
    ),
    # references — line that is essentially a URL / citation / doi
    (
        re.compile(
            r"^\s*(https?://|doi:|arxiv:|@?\w+\d{4}|\[.+\]\(https?://)",
            re.IGNORECASE,
        ),
        "reference",
        0.9,
    ),
]


def _classify_sentence(sentence: str) -> tuple[ClaimType, float] | None:
    """Return (claim_type, confidence) for a sentence, or None if it
    matches no pattern. None → drop the sentence (default-reject).
    """
    for pat, claim_type, conf in _CLAIM_PATTERNS:
        if pat.search(sentence):
            return claim_type, conf
    return None


# ── Evidence reference extraction ────────────────────────────────────
#
# Pulls structured EvidenceRefs out of any text. Same patterns as the
# wiki classifier's positive signal #3 plus structural extraction.

_URL_RE = re.compile(r"https?://[^\s)\]]+")
_DOI_RE = re.compile(r"\bdoi:\s*([^\s,]+)", re.IGNORECASE)
_ARXIV_RE = re.compile(r"\barxiv:\s*([\w./-]+)", re.IGNORECASE)
_PAPER_RE = re.compile(
    r"\b([A-Z][a-z]+(?:\s+(?:et al\.?|&)\s+[A-Z][a-z]+)?)\s+(\d{4})\b"
)
_FILE_RE = re.compile(
    r"\b([\w./-]+\.(?:py|js|ts|md|json|yaml|yml|sql|go|rs|rb|java|cpp|c|h|hpp|sh|toml))\b"
)
_FUNC_RE = re.compile(r"\b([a-z_]+\.[a-z_]+)\(\)|\b([a-z_]\w*)\(\)")
_CLASS_RE = re.compile(r"\b(class\s+[A-Z]\w+|[A-Z][a-zA-Z]+(?=\.))\b")
_SHA_RE = re.compile(r"\b([0-9a-f]{7,40})\b")
_BENCH_RE = re.compile(
    r"\b(LongMemEval|LoCoMo|BEAM|MemoryAgentBench|EverMemBench)\b", re.IGNORECASE
)


def _extract_evidence(content: str) -> list[EvidenceRef]:
    """Extract every concrete reference found in the content."""
    refs: list[EvidenceRef] = []
    seen: set[tuple[str, str]] = set()

    def _add(kind: str, target: str, context: str | None = None) -> None:
        target = target.strip().rstrip(".,;:")
        key = (kind, target)
        if not target or key in seen:
            return
        seen.add(key)
        refs.append(EvidenceRef(kind=kind, target=target, context=context))

    for m in _URL_RE.finditer(content):
        _add("url", m.group(0))
    for m in _DOI_RE.finditer(content):
        _add("paper", "doi:" + m.group(1))
    for m in _ARXIV_RE.finditer(content):
        _add("paper", "arxiv:" + m.group(1))
    for m in _PAPER_RE.finditer(content):
        author, year = m.group(1), m.group(2)
        _add("paper", f"{author} {year}")
    for m in _FILE_RE.finditer(content):
        _add("file", m.group(1))
    for m in _SHA_RE.finditer(content):
        _add("commit", m.group(1))
    for m in _BENCH_RE.finditer(content):
        _add("benchmark", m.group(1))

    return refs


# ── Supersedes detection ─────────────────────────────────────────────

_SUPERSEDES_RE = re.compile(
    r"\b(supersed(?:es|ed by)|replaces?|replaced by|deprecated by|in favour of)\b",
    re.IGNORECASE,
)


def _detects_supersedes(sentence: str) -> bool:
    return bool(_SUPERSEDES_RE.search(sentence))


# ── Public extractor entry point ─────────────────────────────────────


@dataclass(frozen=True)
class ExtractionStats:
    """Diagnostics returned alongside the extracted claims."""

    sentences_total: int
    sentences_classified: int
    sentences_dropped: int
    evidence_refs_total: int


def extract_claims(
    content: str,
    *,
    memory_id: int | None = None,
    session_id: str = "",
    entity_ids: list[int] | None = None,
) -> tuple[list[ClaimEvent], ExtractionStats]:
    """Extract typed ClaimEvents from raw memory content.

    Process:
      1. Strip fenced code blocks (don't classify code as prose claims).
      2. Split into candidate sentences.
      3. Classify each sentence by pattern; drop unclassified.
      4. Pull document-level evidence refs (URLs, files, papers, commits).
      5. Attach evidence refs to every claim from this content (a single
         shared evidence pool — refining per-claim attribution is a
         later optimization).

    Returns (claims, stats). Never raises on bad input — empty content
    yields ([], stats with zero counts).
    """
    if not content or not content.strip():
        return [], ExtractionStats(0, 0, 0, 0)

    sentences = _split_sentences(content)
    evidence = _extract_evidence(content)
    claims: list[ClaimEvent] = []

    for sent in sentences:
        cls = _classify_sentence(sent)
        if cls is None:
            continue
        claim_type, confidence = cls
        # Bias confidence up if the sentence has its own evidence ref
        sent_refs = _extract_evidence(sent)
        if sent_refs:
            confidence = min(1.0, confidence + 0.1)
        # Use the more specific per-sentence refs when present, else the
        # document-level pool (helps draft synthesis cite specific lines)
        refs = sent_refs if sent_refs else evidence
        claims.append(
            ClaimEvent(
                memory_id=memory_id,
                session_id=session_id,
                text=sent[:1900],  # leave headroom under DDL TEXT cap
                claim_type=claim_type,
                entity_ids=entity_ids or [],
                evidence_refs=refs,
                confidence=confidence,
            )
        )

    stats = ExtractionStats(
        sentences_total=len(sentences),
        sentences_classified=len(claims),
        sentences_dropped=len(sentences) - len(claims),
        evidence_refs_total=len(evidence),
    )
    return claims, stats
