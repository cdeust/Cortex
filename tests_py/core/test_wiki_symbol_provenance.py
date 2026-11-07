"""ADR-0312: authoritative claim refs precede best-effort prose extraction."""

from types import SimpleNamespace
import pytest
from mcp_server.core.wiki_symbol_extract import (
    extract_symbol_refs,
    harvest_page_symbols,
)


def test_calls_are_deduplicated_and_filenames_are_not_symbols():
    text = (
        "`parse_record(x, y)` calls `pkg.Parser.parse()` twice: `parse_record()`. "
        "pkg.Parser.parse imports settings.toml and README.md; "
        "`config.json()` is not a function. Other worker.resolve is relevant."
    )
    assert extract_symbol_refs(text) == [
        "parse_record",
        "pkg.Parser.parse",
        "worker.resolve",
    ]
    assert extract_symbol_refs("") == []


@pytest.mark.parametrize(
    "sections",
    [
        {"Details": "worker.resolve then `pkg.Parser.parse()`"},
        [
            {"heading": "Details", "body": "worker.resolve"},
            SimpleNamespace(body="`pkg.Parser.parse()`"),
        ],
    ],
)
def test_claim_provenance_wins_without_duplicates_across_sections(sections):
    page = {
        "lead": "`pkg.Parser.parse()` resolves service.dispatch",
        "sections": sections,
    }
    refs = harvest_page_symbols(
        page, ["authoritative.symbol", "", "worker.resolve", "authoritative.symbol"]
    )
    assert refs == [
        "authoritative.symbol",
        "worker.resolve",
        "pkg.Parser.parse",
        "service.dispatch",
    ]
    assert page["sections"] is sections


def test_absent_optional_content_does_not_invent_symbols():
    assert harvest_page_symbols({"lead": None, "sections": None}) == []
    assert harvest_page_symbols({"sections": [{"heading": "Empty"}, object()]}) == []
