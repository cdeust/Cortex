"""Regression tests for wiki_classifier audit-gate and path/URL rejection."""

from __future__ import annotations

from mcp_server.core.wiki_classifier import classify_memory, derive_title


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


# ── derive_title regression tests (bugs found 2026-05-12) ─────────────


def test_derive_title_rejects_yaml_timestamp_line() -> None:
    """Regression — 10 ADRs were slugged ``decision-created-2026-04-15t...``
    because the first non-{}/[] line in the body was a YAML ``created:``
    timestamp. derive_title must reject metadata key:value lines.
    """
    content = (
        "created: 2026-04-15T09:29:10Z\n"
        "We adopted pgvector with HNSW because benchmarks showed 3x speedup.\n"
    )
    title = derive_title(content, "adr")
    assert "2026-04-15" not in title
    assert "created" not in title.lower()
    assert "pgvector" in title.lower() or "HNSW" in title


def test_derive_title_rejects_embedded_posix_path() -> None:
    """Regression — pages like ``2026-04-17-also-on-users-cdeust-documents-
    developments-...`` were created because the first body line contained
    an absolute /Users/ path mid-sentence and the path-as-title regex only
    matched start-of-line. derive_title must reject path-embedded lines.
    """
    content = (
        "also on /Users/cdeust/Documents/Developments/ai-architect-prd-builder "
        "the same issue shows up\n"
        "The real spec: caching keys must include model SHA.\n"
    )
    title = derive_title(content, "spec")
    assert "users-cdeust" not in title.lower()
    assert "/users/" not in title.lower()


def test_derive_title_rejects_windows_path() -> None:
    content = (
        "see C:\\Users\\dev\\project\\config.toml for details\n"
        "Caching policy: include the model SHA in every key.\n"
    )
    title = derive_title(content, "spec")
    # The C:\ line must not appear; the clean second line is used instead.
    assert "config.toml" not in title.lower()
    assert "\\users\\dev" not in title.lower()
    assert "caching" in title.lower()


def test_derive_title_returns_empty_when_no_clean_candidate() -> None:
    """When every candidate line is rejected, return empty so the caller
    (wiki_sync) routes to the deterministic ``memory-<hash>`` fallback
    instead of inheriting the v3.10.1 ``content[:80]`` raw-fragment leak.
    """
    content = "created: 2026-04-15T09:29:10Z\nupdated: 2026-04-15T09:29:11Z\nid: 1828\n"
    title = derive_title(content, "adr")
    assert title == ""


def test_derive_title_bare_iso_timestamp_rejected() -> None:
    content = (
        "2026-04-15T09:29:10Z is when this happened\n"
        "Decision: adopt pgvector for ANN.\n"
    )
    title = derive_title(content, "adr")
    assert "2026-04-15" not in title


def test_derive_title_still_works_for_clean_input() -> None:
    """Positive control — happy path must continue to work."""
    content = "Use pgvector for retrieval — IVFFlat is too slow at our scale."
    title = derive_title(content, "adr")
    assert "pgvector" in title.lower()
    assert title.startswith("Decision:")
