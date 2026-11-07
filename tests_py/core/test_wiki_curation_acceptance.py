"""ADR-0299: prose is required; headings, fences and lists are not curation."""

from mcp_server.core.wiki_curation_gaps import gap_report, render_gap_banner

PURPOSE = (
    "The adapter owns the conversion from stored memory rows into a response "
    "that the wiki can render. It keeps source identifiers so the reader can "
    "follow every claim back to evidence. It must not mutate a memory or invent "
    "a missing reference; storage and authorization remain with their own components."
)


def test_substantive_alias_heading_counts_without_crediting_neighbor_sections():
    report = gap_report(
        "## What this file does\n"
        + PURPOSE
        + "\n### Scope\nOnly stored evidence.\n## Public API\nTODO"
    )
    assert "purpose" not in report["missing"]
    assert "public-api" in report["missing"]
    assert report["covered_sections"] == 1 and not report["complete"]
    assert len(report["missing"]) == report["total_sections"] - 1
    banner = render_gap_banner(report)
    assert "Public API" in banner and "autonomous re-author loop" in banner


def test_code_and_bullet_padding_cannot_make_skeleton_complete():
    body = (
        "## Purpose\n\n```python\n"
        + PURPOSE
        + "\n```\n- "
        + PURPOSE
        + "\n* Another bullet\n+ Third bullet\n## Other\n"
        + PURPOSE
    )
    report = gap_report(body)
    assert "purpose" in report["missing"]
    assert report["covered_sections"] == 0 and report["completion_pct"] == 0


def test_later_valid_alias_can_replace_an_empty_canonical_heading():
    report = gap_report("## Purpose\nTODO\n## What this file does\n" + PURPOSE)
    assert "purpose" not in report["missing"]


def test_banner_handles_complete_and_legacy_reports_without_crashing():
    assert render_gap_banner({"complete": True}) == ""
    assert render_gap_banner({"missing": []}) == ""
    banner = render_gap_banner({"missing": ["provenance"], "completion_pct": 0.5})
    assert "50% curated" in banner and "**provenance**" in banner
