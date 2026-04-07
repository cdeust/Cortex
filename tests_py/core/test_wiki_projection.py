"""Tests for core.wiki_projection — pure rendering, deterministic output."""

from __future__ import annotations

from pathlib import PurePosixPath

from mcp_server.core.wiki_projection import (
    CausalChain,
    DomainSummary,
    SchemaInfo,
    WikiSnapshot,
    build_pages,
)


def _snapshot() -> WikiSnapshot:
    return WikiSnapshot(
        domains=(
            DomainSummary(
                id="cortex",
                label="Cortex",
                session_count=42,
                confidence=0.91,
                last_active="2026-04-07",
                top_categories=("refactoring", "testing"),
                dominant_mode="deep",
            ),
            DomainSummary(
                id="other",
                label="Other",
                session_count=3,
                confidence=0.4,
            ),
        ),
        global_style="reflective/intuitive",
    )


def test_build_pages_returns_global_and_domain_indexes() -> None:
    pages = build_pages(_snapshot())
    paths = [str(p.path) for p in pages]
    assert paths == ["INDEX.md", "cortex/INDEX.md", "other/INDEX.md"]


def test_global_index_contains_domain_table() -> None:
    pages = build_pages(_snapshot())
    md = pages[0].markdown
    assert "# Cortex Memory Wiki" in md
    assert "reflective/intuitive" in md
    assert "[Cortex](cortex/INDEX.md)" in md
    # cortex must come before other (sorted by session_count desc)
    assert md.index("cortex/INDEX.md") < md.index("other/INDEX.md")


def test_domain_index_contains_categories_and_placeholders() -> None:
    pages = build_pages(_snapshot())
    cortex_page = next(p for p in pages if p.path == PurePosixPath("cortex/INDEX.md"))
    md = cortex_page.markdown
    assert "# Cortex" in md
    assert "refactoring" in md
    assert "Dominant mode" in md
    assert "No schemas formed yet" in md  # schema placeholder when none
    assert "No causal chains" in md  # chain placeholder when none


def test_empty_snapshot_renders_global_index_only() -> None:
    pages = build_pages(WikiSnapshot())
    assert len(pages) == 1
    assert "No domains yet" in pages[0].markdown


def _snapshot_with_schemas() -> WikiSnapshot:
    base = _snapshot()
    schemas = (
        SchemaInfo(
            schema_id="schema_a",
            domain_id="cortex",
            label="Memory consolidation",
            entity_signature={"memory": 0.9, "schema": 0.7, "decay": 0.5},
            tag_signature={"neuro": 0.8},
            formation_count=12,
            assimilation_count=4,
        ),
        SchemaInfo(
            schema_id="schema_b",
            domain_id="cortex",
            label="Retrieval pipeline",
            entity_signature={"recall": 0.8, "rerank": 0.6, "memory": 0.4},
            formation_count=7,
        ),
        SchemaInfo(
            schema_id="orphan",
            domain_id="missing",
            label="Should not render",
            entity_signature={"x": 1.0},
        ),
    )
    return WikiSnapshot(
        domains=base.domains,
        global_style=base.global_style,
        schemas=schemas,
    )


def test_schema_pages_rendered_only_for_known_domains() -> None:
    pages = build_pages(_snapshot_with_schemas())
    paths = [str(p.path) for p in pages]
    assert "cortex/schemas/schema_a.md" in paths
    assert "cortex/schemas/schema_b.md" in paths
    assert not any("missing/" in p for p in paths)


def test_domain_index_lists_schemas_and_overlap_graph() -> None:
    pages = build_pages(_snapshot_with_schemas())
    cortex_idx = next(p for p in pages if str(p.path) == "cortex/INDEX.md").markdown
    assert "Memory consolidation" in cortex_idx
    assert "Retrieval pipeline" in cortex_idx
    assert "schemas/schema_a.md" in cortex_idx
    assert "```mermaid" in cortex_idx  # overlap graph embedded
    # schema_a (12 formations) ranks above schema_b (7)
    assert cortex_idx.index("schema_a.md") < cortex_idx.index("schema_b.md")


def test_schema_page_contains_entity_table_and_wheel() -> None:
    pages = build_pages(_snapshot_with_schemas())
    sa = next(p for p in pages if str(p.path) == "cortex/schemas/schema_a.md").markdown
    assert "# Memory consolidation" in sa
    assert "memory" in sa
    assert "0.90" in sa
    assert "neuro" in sa  # tag rendered
    assert "```mermaid" in sa
    assert "../INDEX.md" in sa  # back-link


def _snapshot_with_chains() -> WikiSnapshot:
    base = _snapshot()
    chains = (
        CausalChain(
            chain_id="mem_42",
            domain_id="cortex",
            seed_memory_id=42,
            seed_label="Decay tuning",
            seed_heat=0.81,
            edges=(
                ("memory", "decays_into", "gist"),
                ("gist", "consolidates_to", "schema"),
            ),
        ),
        CausalChain(
            chain_id="mem_7",
            domain_id="cortex",
            seed_memory_id=7,
            seed_label="Reranker tweak",
            seed_heat=0.55,
            edges=(("query", "ranked_by", "reranker"),),
        ),
        CausalChain(
            chain_id="orphan",
            domain_id="missing",
            seed_memory_id=1,
            seed_label="ignored",
            edges=(("a", "r", "b"),),
        ),
    )
    return WikiSnapshot(
        domains=base.domains,
        global_style=base.global_style,
        chains=chains,
    )


def test_chain_pages_rendered_only_for_known_domains() -> None:
    pages = build_pages(_snapshot_with_chains())
    paths = [str(p.path) for p in pages]
    assert "cortex/chains/mem_42.md" in paths
    assert "cortex/chains/mem_7.md" in paths
    assert not any("missing" in p for p in paths)


def test_domain_index_lists_chains_sorted_by_heat() -> None:
    pages = build_pages(_snapshot_with_chains())
    md = next(p for p in pages if str(p.path) == "cortex/INDEX.md").markdown
    assert "Decay tuning" in md
    assert "Reranker tweak" in md
    # mem_42 (heat 0.81) ranks above mem_7 (heat 0.55)
    assert md.index("chains/mem_42.md") < md.index("chains/mem_7.md")


def test_chain_page_contains_graph_and_edge_table() -> None:
    pages = build_pages(_snapshot_with_chains())
    page = next(p for p in pages if str(p.path) == "cortex/chains/mem_42.md").markdown
    assert "# Chain: Decay tuning" in page
    assert "```mermaid" in page
    assert "graph TD" in page
    assert "decays_into" in page
    assert "../INDEX.md" in page  # back-link


def test_render_is_deterministic() -> None:
    a = build_pages(_snapshot())
    b = build_pages(_snapshot())
    assert [(str(p.path), p.markdown) for p in a] == [
        (str(p.path), p.markdown) for p in b
    ]
