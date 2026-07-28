"""Tests for core/prose_redaction.py — the native AI-writing-tell inventory (issue
#166)."""

from __future__ import annotations

from mcp_server.core.prose_redaction import (
    CATEGORY_AI_ARTIFACT,
    CATEGORY_BANNED_WORD,
    CATEGORY_BINARY_CONTRAST,
    CATEGORY_DRAMATIC_FRAGMENT,
    CATEGORY_EM_DASH,
    CATEGORY_FAKE_VERB,
    CATEGORY_FAUX_INSIGHT,
    CATEGORY_FILLER,
    CATEGORY_ING_TACKON,
    CATEGORY_NEGATIVE_LISTING,
    CATEGORY_PROMOTIONAL,
    CATEGORY_PUFFERY,
    CATEGORY_RHETORICAL,
    CATEGORY_SIGNPOST,
    CATEGORY_THROAT_CLEARING,
    CATEGORY_WEASEL,
    REDACTION_CONVENTIONS,
    scan_prose,
    summarize_findings,
)


def _categories(text: str) -> list[str]:
    return [f.category for f in scan_prose(text)]


class TestScanProse:
    def test_clean_technical_prose_yields_no_findings(self):
        text = (
            "The recall path fuses vector, FTS, and trigram signals.\n"
            "p50 latency is 125ms, measured in benchmarks/longmemeval "
            "(2026-04 run).\n"
        )
        assert scan_prose(text) == []

    def test_em_dash_flagged_with_line_number(self):
        findings = scan_prose("First line is fine.\nThe store is fast — very fast.")
        assert len(findings) == 1
        f = findings[0]
        assert f.category == CATEGORY_EM_DASH
        assert f.line == 2

    def test_banned_vocabulary_flagged(self):
        findings = scan_prose("We leverage a transformative pipeline.")
        cats = [f.category for f in findings]
        assert cats.count(CATEGORY_BANNED_WORD) >= 1

    def test_weasel_attribution_flagged(self):
        findings = scan_prose("Studies show this approach wins.")
        assert [f.category for f in findings] == [CATEGORY_WEASEL]

    def test_ing_tackon_flagged(self):
        text = "The launch adds file search, highlighting the team's commitment."
        findings = scan_prose(text)
        assert [f.category for f in findings] == [CATEGORY_ING_TACKON]

    def test_plain_participle_clause_not_flagged(self):
        # An -ing verb outside the tack-on set must not fire (false-positive guard).
        assert scan_prose("The worker keeps polling, retrying on timeouts.") == []

    def test_fenced_code_blocks_skipped(self):
        text = (
            "Real prose line.\n```\nx = 'studies show — leverage'\n```\nMore prose.\n"
        )
        assert scan_prose(text) == []

    def test_frontmatter_is_scanned(self):
        # Titles/descriptions are reader-facing; the fence regex must not
        # treat YAML '---' as a code fence.
        text = "---\ntitle: A transformative journey\n---\nBody.\n"
        findings = scan_prose(text)
        assert [f.category for f in findings] == [CATEGORY_BANNED_WORD]

    def test_excerpt_bounded(self):
        long_line = "delve " + "x" * 300
        (finding,) = scan_prose(long_line)
        assert len(finding.excerpt) <= 80


class TestExpandedInventory:
    """The full mechanical set beyond the initial four classes (issue #166)."""

    def test_binary_contrast_two_sentence_form(self):
        assert _categories("It's not the model. It's the eval.") == [
            CATEGORY_BINARY_CONTRAST
        ]

    def test_binary_contrast_not_just_but_form(self):
        assert CATEGORY_BINARY_CONTRAST in _categories(
            "This is not just retrieval, but a full memory system."
        )

    def test_negative_listing(self):
        assert _categories("Not a cache. Not a database. A memory.") == [
            CATEGORY_NEGATIVE_LISTING
        ]

    def test_throat_clearing(self):
        assert _categories("Here's the thing about consolidation.") == [
            CATEGORY_THROAT_CLEARING
        ]

    def test_faux_insight(self):
        assert _categories("What nobody tells you about vector search.") == [
            CATEGORY_FAUX_INSIGHT
        ]

    def test_puffery(self):
        assert _categories("This marks a pivotal moment for the wiki.") == [
            CATEGORY_PUFFERY
        ]

    def test_promotional(self):
        assert CATEGORY_PROMOTIONAL in _categories(
            "A vibrant ecosystem nestled in the heart of the repo."
        )

    def test_fake_strong_verb(self):
        assert _categories("The handler serves as a centralized hub.") == [
            CATEGORY_FAKE_VERB
        ]

    def test_ai_conversation_artifact(self):
        assert _categories("I hope this helps with your setup.") == [
            CATEGORY_AI_ARTIFACT
        ]

    def test_signposting(self):
        assert _categories("In this section we will explore recall.") == [
            CATEGORY_SIGNPOST
        ]

    def test_rhetorical_setup(self):
        assert _categories("Plot twist: the cache was cold.") == [CATEGORY_RHETORICAL]

    def test_dramatic_fragment(self):
        assert _categories("That's it. That's the whole design.") == [
            CATEGORY_DRAMATIC_FRAGMENT
        ]

    def test_filler_phrase(self):
        assert _categories("At its core, the gate is a filter.") == [CATEGORY_FILLER]

    def test_false_positive_guards_on_technical_prose(self):
        # Ordinary technical sentences that brush against pattern shapes
        # must stay silent — an inventory extension that fires here is a
        # regression, not a catch.
        clean = (
            "The store is not thread-safe; callers hold the lock.\n"
            "Serves requests from the read replica after failover.\n"
            "The problem is the cache TTL, not the index.\n"
            "We explore the graph via BFS from the seed entity.\n"
            "In summary tables, counts are measured, not estimated.\n"
        )
        assert scan_prose(clean) == []


class TestSummarizeFindings:
    def test_summary_shape_and_cap(self):
        text = "\n".join("We delve deeper — again." for _ in range(15))
        summary = summarize_findings(scan_prose(text), cap=10)
        assert summary["count"] == 30  # em dash + banned word per line
        assert summary["by_category"][CATEGORY_EM_DASH] == 15
        assert summary["by_category"][CATEGORY_BANNED_WORD] == 15
        assert len(summary["first"]) == 10
        first = summary["first"][0]
        assert set(first) == {"line", "category", "match", "excerpt"}

    def test_empty_findings_summary(self):
        summary = summarize_findings([])
        assert summary == {"count": 0, "by_category": {}, "first": []}


class TestPromptIntegration:
    def test_conventions_block_is_nonempty_and_em_dash_free(self):
        assert "No em dashes" in REDACTION_CONVENTIONS
        assert "—" not in REDACTION_CONVENTIONS

    def test_authoring_prompts_carry_the_conventions(self):
        from mcp_server.core import auto_curator

        for name in (
            "WIKI_AUTHORING_PROMPT",
            "WIKI_COVERAGE_PROMPT",
            "WIKI_REAUTHOR_PROMPT",
        ):
            template = getattr(auto_curator, name)
            assert "{redaction_conventions}" in template, name
