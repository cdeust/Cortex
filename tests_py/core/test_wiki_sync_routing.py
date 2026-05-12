"""Tests for ADR-2244 routing in wiki_sync.build_from_memory.

Verifies that the modern (kind, lifecycle, audience, provenance) tuple
drives the directory, that the frontmatter shape conforms to the new
schema, and that the file→notes/ misroute bug (Task #8) is fixed.
"""

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
    """ADR-2244 §4.1: 'lesson' is dropped; root-cause goes to explanation/."""
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
    """ADR-2244 §4: every modern page carries kind, lifecycle, audience,
    provenance in its frontmatter."""
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


def test_file_documentation_does_not_route_to_notes() -> None:
    """Task #8 fix: pages tagged as code references must not land in notes/.

    Before ADR-2244, file documentation produced by codebase_analyze
    ended up at notes/<domain>/<id>-file-*.md because the old
    _KIND_TO_DIR had no 'file' mapping. The classifier now marks the
    provenance as auto-generated and routes to reference/ via the
    modern kind.
    """
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
    assert result is not None
    rel, md = result
    assert not rel.startswith("notes/"), (
        f"file-documentation still routing to notes/: {rel!r}"
    )
    fm = _parse_frontmatter(md)
    assert fm["provenance"] == "auto-generated"
