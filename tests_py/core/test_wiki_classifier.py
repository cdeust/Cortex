"""Regression tests for wiki_classifier audit-gate and path/URL rejection."""

from __future__ import annotations

from mcp_server.core.wiki_classifier import classify_memory


# ── Audit-tag gate ────────────────────────────────────────────────────


def test_backfill_tag_rejects_even_with_rich_content() -> None:
    content = (
        "Decision: adopt pgvector with HNSW (m=16, ef_construction=64) "
        "because benchmarks show 3x improvement over IVFFlat at this scale. "
        "Consequences: Postgres becomes a hard dependency."
    )
    assert classify_memory(content, tags=["imported", "_backfill"]) is None


def test_session_summary_tag_rejects() -> None:
    content = (
        "Session abc-123 in domain 'cortex' | category: bug-fix | "
        "topics: recall, regression, pgvector"
    )
    assert classify_memory(content, tags=["session-summary"]) is None


def test_stage_tag_rejects_audit_artefact() -> None:
    content = (
        "ai-architect-mcp stage 1 code review (src/main.rs, 1042 LOC): "
        "APPROVED-WITH-CHANGES. Five engineer-flagged concerns: "
        "MergeMode::PreserveRefined CORRECT, validate_safe_id CORRECT..."
    )
    assert classify_memory(content, tags=["stage-1", "code-review"]) is None


# ── Path/URL title gate ───────────────────────────────────────────────


def test_posix_path_title_rejects() -> None:
    content = (
        "/Users/alice/Downloads/resume.pdf\nhttps://linkedin.com/in/alice/\n\n"
        "Context note about the file."
    )
    assert classify_memory(content, tags=["paper"]) is None


def test_home_path_title_rejects() -> None:
    content = "~/code/cortex/mcp_server/core/pg_recall.py has a bug."
    assert classify_memory(content, tags=["bug-fix"]) is None


def test_url_title_rejects() -> None:
    content = (
        "https://arxiv.org/abs/2310.12345\n\n"
        "This paper proposes WRRF fusion. Results show R@10 = 97.8%."
    )
    assert classify_memory(content, tags=["paper", "research"]) is None


def test_lone_filename_title_rejects() -> None:
    content = "resume-v3.pdf contains my latest CV as of April 2026."
    assert classify_memory(content, tags=[]) is None


# ── Audit-shaped titles ───────────────────────────────────────────────


def test_stage_n_in_title_rejects() -> None:
    content = "stage 3 research verdict: GitNexus is MIT licensed and usable."
    assert classify_memory(content, tags=["research"]) is None


def test_code_review_title_rejects() -> None:
    content = "Code review notes for PR #42: three concerns raised around SRP."
    assert classify_memory(content, tags=["review"]) is None


# ── Positive control: real ADR/lesson still admitted ─────────────────


def test_valid_adr_admitted() -> None:
    content = (
        "Decision: use pgvector over IVFFlat for ANN search. Context: "
        "100k memories need sub-100ms cosine retrieval. Decided to adopt "
        "HNSW (m=16, ef_construction=64) because benchmarks show 3x improvement. "
        "Consequences: Postgres becomes mandatory."
    )
    assert classify_memory(content, tags=["decision", "architecture"]) == "adr"


def test_valid_lesson_admitted() -> None:
    content = (
        "The bug was that FlashRank ONNX cache persisted stale weights across "
        "container restarts. Root cause: cache key did not include model hash. "
        "Fix: include model SHA in the cache key. Never ship a cache keyed only "
        "on path again."
    )
    assert classify_memory(content, tags=["lesson", "bug-fix"]) == "lesson"
