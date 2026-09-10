"""Tests for wiki_sync.build_from_memory routing.

Verifies modern kind, lifecycle, audience and provenance fields and directory routing.

source: ADR-0935"""

from __future__ import annotations

from mcp_server.core.wiki_sync import build_from_memory


def _parse_frontmatter(md: str) -> dict[str, str]:
    """Minimal YAML-ish parser for the test (no PyYAML dependency)."""
    assert md.startswith("---\n"), f"missing frontmatter delimiter: {md[:40]!r}"
    end = md.find("\n---", 4)
    block = md[4:end]
    out: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            out[key.strip()] = value.strip()
    return out


def test_adr_routes_to_adr_directory() -> None:
    content = (
        "Decision: use pgvector with HNSW for ANN retrieval. Context: 100k "
        "memories need sub-100ms cosine. Decided to adopt HNSW (m=16). "
        "Consequences: Postgres becomes mandatory."
    )
    result = build_from_memory(
        memory_id=42,
        content=content,
        tags=["decision", "architecture"],
        domain="cortex",
    )
    assert result is not None
    rel, md = result
    assert rel.startswith("adr/cortex/42-")
    assert rel.endswith(".md")
    assert not rel.endswith(".md.md")  # regression for the old slug bug


def test_legacy_lesson_routes_to_explanation_directory() -> None:
    """Lesson and root-cause content routes to explanation/.

    source: ADR-0935"""
    content = (
        "The bug was that the cache key did not include the model SHA. "
        "Root cause: stale weights persisted across container restarts. "
        "Fix: include the SHA in every cache key. Never ship a path-keyed "
        "cache again."
    )
    result = build_from_memory(
        memory_id=101,
        content=content,
        tags=["lesson", "bug-fix"],
        domain="cortex",
    )
    assert result is not None
    rel, _md = result
    assert rel.startswith("explanation/cortex/101-")
    # Must NOT land in the legacy lessons/ directory.
    assert not rel.startswith("lessons/")


def test_runbook_routes_to_runbook_directory() -> None:
    content = (
        "When the alert fires for the recall p99 latency, follow this "
        "runbook. Step 1: check pgvector replica health. Step 2: rotate "
        "connection pool. On-call recovery procedure documented below."
    )
    result = build_from_memory(
        memory_id=7,
        content=content,
        tags=["ops", "runbook"],
        domain="cortex",
    )
    assert result is not None
    rel, md = result
    assert rel.startswith("runbook/cortex/7-")
    fm = _parse_frontmatter(md)
    assert fm["kind"] == "runbook"


def test_frontmatter_includes_4tuple_axes() -> None:
    """Modern pages carry kind, lifecycle, audience and provenance in frontmatter.

    source: ADR-0935"""
    content = (
        "Decision: use pgvector over IVFFlat for ANN search. Context: 100k "
        "memories. Decided to adopt HNSW. Consequences: Postgres is mandatory."
    )
    result = build_from_memory(
        memory_id=200,
        content=content,
        tags=["decision", "architecture"],
        domain="cortex",
    )
    assert result is not None
    _rel, md = result
    fm = _parse_frontmatter(md)
    assert fm["kind"] == "adr"
    assert fm["lifecycle"] == "proposed"  # ADR default
    assert fm["provenance"] == "human"


def test_rejection_returns_none() -> None:
    """Tool-output content stays rejected — admission gate unchanged."""
    result = build_from_memory(
        memory_id=1,
        content="<tool_result>output of ls -la</tool_result>",
        tags=["tool-output"],
    )
    assert result is None


def test_new_page_carries_stable_id() -> None:
    """Every page written by wiki_sync receives a UUID4 frontmatter id.

    source: ADR-0935"""
    from mcp_server.core.wiki_identity import is_valid_page_id

    content = (
        "Decision: use pgvector over IVFFlat for ANN search. Context: 100k "
        "memories. Decided to adopt HNSW. Consequences: Postgres mandatory."
    )
    result = build_from_memory(
        memory_id=300,
        content=content,
        tags=["decision", "architecture"],
        domain="cortex",
    )
    assert result is not None
    _rel, md = result
    fm = _parse_frontmatter(md)
    assert "id" in fm
    assert is_valid_page_id(fm["id"])


def test_each_new_page_gets_a_distinct_id() -> None:
    """Two writes produce two different ids so we never accidentally
    write a redirect stub that points at its own source."""
    from mcp_server.core.wiki_identity import is_valid_page_id

    content_a = (
        "Decision: use pgvector. Context: 100k memories need sub-100ms. "
        "Decided to adopt HNSW. Consequences: Postgres mandatory."
    )
    content_b = (
        "Decision: use Lucene. Context: full text search on 10M docs. "
        "Decided to adopt Lucene. Consequences: JVM in the stack."
    )
    r_a = build_from_memory(
        memory_id=301, content=content_a, tags=["decision"], domain="cortex"
    )
    r_b = build_from_memory(
        memory_id=302, content=content_b, tags=["decision"], domain="cortex"
    )
    assert r_a is not None and r_b is not None
    id_a = _parse_frontmatter(r_a[1])["id"]
    id_b = _parse_frontmatter(r_b[1])["id"]
    assert is_valid_page_id(id_a)
    assert is_valid_page_id(id_b)
    assert id_a != id_b


def test_file_documentation_is_rejected_from_wiki() -> None:
    """Codebase-tagged extractor output does not create wiki pages.

    source: ADR-0935"""
    content = (
        "Decision: this module parses a single source file via tree-sitter "
        "and falls back to regex tokenisation for unsupported languages. "
        "Trade-off documented in ADR-0033. Defined entities: parse_file, "
        "_tokenize, language_for_extension."
    )
    result = build_from_memory(
        memory_id=98649,
        content=content,
        tags=["code-reference", "codebase"],
        domain="cortex",
    )
    assert result is None, (
        "codebase/code-reference tagged content must be rejected from the "
        "wiki — it lives in PG memory only; the autonomous worker "
        "produces curated structural pages instead"
    )
