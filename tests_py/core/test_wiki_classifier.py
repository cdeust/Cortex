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
    result = classify_memory(content, tags=["decision", "architecture"])
    assert result is not None
    assert result.kind == "adr"
    assert result.lifecycle == "proposed"  # default for new ADRs
    assert result.provenance == "human"


def test_valid_lesson_admitted_as_explanation() -> None:
    """ADR-2244 §4.1: the legacy 'lesson' kind maps to modern 'explanation'.

    Root-cause analysis is explanatory content — the 'lesson' bucket
    collapses into 'explanation' with audience=[developer].
    """
    content = (
        "The bug was that FlashRank ONNX cache persisted stale weights across "
        "container restarts. Root cause: cache key did not include model hash. "
        "Fix: include model SHA in the cache key. Never ship a cache keyed only "
        "on path again."
    )
    result = classify_memory(content, tags=["lesson", "bug-fix"])
    assert result is not None
    assert result.kind == "explanation"
    assert result.lifecycle == "seedling"


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


# ── ADR-2244: modern-kind routing (tutorial / how-to / runbook / rfc / journal) ──


def test_classifier_detects_runbook_from_pattern() -> None:
    """Content describing on-call response routes to kind=runbook."""
    content = (
        "When the alert fires for high p99 latency on the recall path, "
        "first check pgvector replica health via the runbook dashboard. "
        "If healthy, rotate the connection pool. Recovery procedure: "
        "1) check connections, 2) restart proxy, 3) page on-call DBA."
    )
    result = classify_memory(content, tags=["runbook", "ops"])
    assert result is not None
    assert result.kind == "runbook"
    assert "ops" in result.audience


def test_classifier_detects_tutorial_from_pattern() -> None:
    content = (
        "Tutorial: in this tutorial we'll learn how to wire pgvector "
        "into a fresh Cortex install. By the end of this tutorial you'll "
        "have a working recall pipeline. Step 1: install Postgres 16. "
        "Step 2: enable the pgvector extension."
    )
    result = classify_memory(content, tags=["tutorial", "getting-started"])
    assert result is not None
    assert result.kind == "tutorial"


def test_classifier_detects_howto_from_pattern() -> None:
    content = (
        "How to migrate a wiki page between kinds when the classifier "
        "verdict changes after an ADR. Here's how to do it without "
        "breaking inbound links: use the redirect-stub pattern from MediaWiki."
    )
    result = classify_memory(content, tags=["how-to", "migration"])
    assert result is not None
    assert result.kind == "how-to"


def test_classifier_detects_rfc_from_pattern() -> None:
    content = (
        "RFC: we propose to replace the single-kind taxonomy with a "
        "4-tuple (kind, lifecycle, audience, provenance). This RFC "
        "supersedes the previous wiki classification design and proposes "
        "an explicit migration plan with stable IDs and redirects."
    )
    result = classify_memory(content, tags=["rfc", "design"])
    assert result is not None
    assert result.kind == "rfc"


def test_classifier_detects_journal_from_dated_heading() -> None:
    """Journal kind fires when content is a dated reflective entry.

    The dated heading is the signal; the body must avoid stronger
    signals (decision markers, RFC tags) that would route elsewhere.
    """
    content = (
        "## 2026-05-12\n\n"
        "Spent the morning on wiki classification design. Read three of "
        "the surveyed taxonomies and sketched the registry approach. "
        "Productive day overall."
    )
    result = classify_memory(content, tags=["journal", "diary"])
    assert result is not None
    assert result.kind == "journal"


# ── ADR-2244: provenance and audience inference ────────────────────────


def test_codebase_tag_marks_auto_generated_provenance() -> None:
    content = (
        "## Process — packages/codebase-rust/src/parser/mod.rs::parse_file\n"
        "Decision: this function parses a single source file via tree-sitter "
        "and falls back to a regex tokeniser. The trade-off is documented "
        "in ADR-0033."
    )
    result = classify_memory(
        content,
        tags=["code-reference", "codebase"],
    )
    assert result is not None
    assert result.provenance == "auto-generated"
    assert result.generator is not None  # required when provenance is auto-gen


def test_security_tag_routes_to_security_audience() -> None:
    content = (
        "Decision: store session tokens in a separate, HSM-backed column "
        "with auth-grade rotation. Context: legal compliance requires "
        "token-level access auditing distinct from app-level logging."
    )
    result = classify_memory(content, tags=["security", "decision"])
    assert result is not None
    assert "security" in result.audience


# ── Calibration regressions from the Phase 2 pilot (2026-05-13) ───────


def test_adr_detected_from_nygard_heading_skeleton() -> None:
    """Pilot 2026-05-13 found 3 of 8 ADRs misclassified because their body
    used the canonical ``## Decision`` heading without a ``Decision:`` colon.
    The ADR pattern now matches the heading skeleton.
    """
    content = (
        "## Status\n\nAccepted\n\n"
        "## Context\n\n"
        "MCP plugins run inside Claude Code's process. Any external "
        "dependency introduces supply chain risk.\n\n"
        "## Decision\n\n"
        "Use zero external npm dependencies. Rely on Node.js built-ins.\n\n"
        "## Consequences\n\n"
        "Gain: no supply chain attack surface. Lose: more hand-written code."
    )
    result = classify_memory(content, tags=["adr"])
    assert result is not None
    assert result.kind == "adr"


def test_architecture_tag_alone_does_not_route_to_adr() -> None:
    """Pilot 2026-05-13 found 8 of 8 RFC pages misrouted to ADR because
    they carried the ``architecture`` tag, which used to be in adr.tag_aliases.
    ``architecture`` was removed from adr aliases — those pages now stay RFC
    (or fall through to explanation if no other signal hits).
    """
    content = (
        "## Top-level layout\n\n- README.md\n- pyproject.toml\n\n"
        "Project structure: repo-a. Primary languages: unknown."
    )
    result = classify_memory(content, tags=["architecture", "project-structure"])
    # Must NOT be adr (the regression we just fixed).
    if result is not None:
        assert result.kind != "adr"


def test_crypto_module_name_does_not_flag_security_audience() -> None:
    """Pilot 2026-05-13 found ADR-001 (zero dependencies) tagged ``security``
    audience because its body listed ``crypto`` among Node built-in modules.
    The security pattern now requires ``cryptograph(y|ic)`` — the full word —
    so a bare module name no longer fires the audience.
    """
    content = (
        "Decision: use zero external dependencies. Rely on Node.js built-in "
        "modules: fs, path, os, http, crypto, and node:test. No external "
        "supply chain. Hand-write any utility a library would provide."
    )
    result = classify_memory(content, tags=["decision", "adr"])
    assert result is not None
    assert result.kind == "adr"
    # The bare word ``crypto`` (module name) should NOT trigger security.
    assert "security" not in result.audience
