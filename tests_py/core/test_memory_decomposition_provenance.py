"""ADR-0197: structural chunks keep temporal context and retrieval evidence."""

from mcp_server.core.memory_decomposer import build_entity_summary, decompose_memory


def test_conversation_chunks_keep_date_speakers_and_semantic_signals():
    text = (
        '[Date: 2026-10-01]\n[Alice]: I prefer "Redis Cache" for this project.\n'
        '[Bob]: I visited "Paris Lab" yesterday.\n'
        "[Alice]: Retaining the evidence identifier is mandatory.\n"
        "[Bob]: I decided to keep the current schema.\n"
        "[Alice]: We can review it together."
    )
    chunks = decompose_memory(text, turns_per_chunk=2, min_chunk_chars=1)
    assert len(chunks) == 3
    assert all(c["content"].startswith("[Date: 2026-10-01]\n") for c in chunks)
    assert chunks[0]["content"].endswith('[Bob]: I visited "Paris Lab" yesterday.')
    assert chunks[1]["content"].startswith("[Date: 2026-10-01]\n[Alice]: Retaining")
    assert chunks[2]["content"].endswith("We can review it together.")
    summary = build_entity_summary(chunks[0]["entities"])
    assert "Redis Cache" in summary and "Paris Lab" in summary
    assert "preference" in summary and "activity" in summary
    summary = build_entity_summary(chunks[1]["entities"])
    assert "instruction" in summary and "decision" in summary


def test_markdown_sections_keep_date_and_only_eligible_section_bodies():
    first = (
        "## Storage\nAlice documents the persistent database "
        "and its backup process for the service."
    )
    second = (
        "## Recovery\nBob describes how to restore a verified snapshot "
        "without losing the evidence identifiers."
    )
    chunks = decompose_memory(
        "[Date: 2026-10-01]\n" + first + "\n" + second, min_chunk_chars=40
    )
    assert [c["content"] for c in chunks] == [
        "[Date: 2026-10-01]\n" + first,
        "[Date: 2026-10-01]\n" + second,
    ]


def test_short_structured_content_falls_back_without_losing_original_evidence():
    for text in ("[Date: 2026-10-01]\n[Alice]: Yes.", "## Short\nRetain this note."):
        chunks = decompose_memory(text)
        assert len(chunks) == 1 and chunks[0]["content"] == text
    assert decompose_memory("  \n ") == []
    assert build_entity_summary({}) == ""
