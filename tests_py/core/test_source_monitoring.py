"""Tests for core.source_monitoring (C1 source / reality monitoring).

Covers the Johnson-1993 heuristic attribution (perceived/told/inferred), the
confidence margin, the evidence-tag mapping, and the confabulation gate.
"""

from __future__ import annotations

from mcp_server.core.source_monitoring import (
    INFERRED,
    PERCEIVED,
    TOLD,
    UNKNOWN,
    SourceJudgement,
    classify_source,
    extract_grounding,
    source_judgement_as_dict,
    violates_source_claim,
)


# ── Grounding extraction ────────────────────────────────────────────────────
def test_extract_grounding_finds_refs():
    text = (
        "See mcp_server/core/thermodynamics.py and https://example.com/x "
        "with doi:10.1038/nature14236 at commit a1b2c3d4e5"
    )
    refs = extract_grounding(text)
    assert any(".py" in r for r in refs)
    assert any(r.startswith("http") for r in refs)
    assert any("10.1038" in r for r in refs)


def test_extract_grounding_empty_on_plain_prose():
    assert extract_grounding("I think this is probably a good idea") == []


# ── Attribution ─────────────────────────────────────────────────────────────
def test_perceived_when_file_grounded():
    j = classify_source("The value column is defined in pg_schema.py line 43")
    assert j.attribution == PERCEIVED
    assert j.evidence_tag == "observed"
    assert j.perceptual_score >= 1


def test_told_when_user_attributed():
    j = classify_source("You said the reranker alpha should stay at 0.70")
    assert j.attribution == TOLD
    assert j.evidence_tag == "stated"


def test_inferred_when_cognitive_markers():
    j = classify_source(
        "I think this probably means the decay is too fast, "
        "so it seems the half-life should be longer"
    )
    assert j.attribution == INFERRED
    assert j.evidence_tag == "inferred"
    assert j.inferred_score >= 2


def test_unknown_when_no_signal():
    j = classify_source("The cat sat on the mat")
    assert j.attribution == UNKNOWN
    assert j.confidence == 0.0


def test_confidence_is_margin():
    # Strong perceptual grounding, no competing markers -> high confidence.
    strong = classify_source("pg_schema.py https://x.io commit a1b2c3d4")
    assert strong.confidence > 0.9
    # Mixed signal -> lower confidence.
    mixed = classify_source("I think pg_schema.py is where it lives")
    assert mixed.confidence < strong.confidence


def test_external_pathway_boosts_perceptual():
    j_no = classify_source("some content")
    j_yes = classify_source("some content", source_field="post_tool_capture")
    assert j_yes.perceptual_score > j_no.perceptual_score
    assert j_yes.attribution == PERCEIVED


def test_tool_output_marker_is_perceptual():
    j = classify_source("The grep returned three matches in the handlers dir")
    assert j.perceptual_score >= 1
    assert j.attribution == PERCEIVED


# ── Confabulation gate ──────────────────────────────────────────────────────
def test_gate_fires_on_ungrounded_observed_claim():
    # Claims observed, but content is pure inference with no grounding.
    assert (
        violates_source_claim("I think the benchmark probably passed", "observed")
        is True
    )


def test_gate_passes_grounded_observed_claim():
    assert (
        violates_source_claim("benchmark_results.json shows MRR 0.76", "observed")
        is False
    )


def test_gate_ignores_inferred_claim():
    # An inferred claim makes no external-grounding promise — never a violation.
    assert violates_source_claim("I think this probably works", "inferred") is False


def test_gate_ignores_stated_claim():
    assert violates_source_claim("I think this probably works", "stated") is False


def test_gate_perceived_synonym():
    assert violates_source_claim("presumably it seems to work", "perceived") is True


def test_judgement_as_dict():
    d = source_judgement_as_dict(classify_source("pg_schema.py line 43"))
    assert d["attribution"] == PERCEIVED
    assert "grounding_refs" in d
    assert isinstance(d["grounding_refs"], list)


def test_source_judgement_as_dict_full_shape_and_rounding():
    # confidence carries a 5th-decimal digit so round(x, 4) vs round(x, 5)
    # and vs round(x, None) (int truncation) are all observably different
    # (issue #282 mutation-testing gap: classify_source's own confidence
    # values in the fixture above didn't force this precision). 11
    # grounding refs so the [:10] truncation slice is exercised too.
    refs = [f"ref{i}.py" for i in range(11)]
    judgement = SourceJudgement(
        attribution=PERCEIVED,
        confidence=0.612345,
        evidence_tag="observed",
        perceptual_score=3,
        told_score=1,
        inferred_score=0,
        grounding_refs=refs,
    )
    d = source_judgement_as_dict(judgement)
    assert d == {
        "attribution": PERCEIVED,
        "confidence": round(0.612345, 4),
        "evidence_tag": "observed",
        "perceptual_score": 3,
        "told_score": 1,
        "inferred_score": 0,
        "grounding_refs": refs[:10],
    }
