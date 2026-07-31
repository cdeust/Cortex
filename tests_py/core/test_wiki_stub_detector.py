"""Tests for wiki_stub_detector — placeholder-density scoring."""

from __future__ import annotations

from mcp_server.core.wiki_stub_detector import (
    is_stub,
    placeholder_count,
    stub_score,
)
import pathlib


SUBSTANTIVE_BODY = """\
# Tool: Bash

This page documents the canonical bash invocation used in the deploy
pipeline. The command is executed by the CI runner after the build
artifact is signed.

## Trigger

The deploy CI job calls this at the end of stage 4.

## Recovery procedure

Roll back via `git revert` and re-run the pipeline.
"""


STUB_BODY = """\
# Tool: Bash

Tool: Bash
**Command:** `./gradlew :app:compileIodevDebugKotlin`

## Trigger

Tool: Bash
**Command:** `./gradlew :app:compileIodevDebugKotlin`

## Root Cause

_(to be filled)_

## Rule

_(to be filled)_

## Situation

_To be written._

## What happened

_To be written._

## What we learned

_To be written._

## Next time

_To be written._
"""


MIXED_BODY = """\
# Foo

A page with one real paragraph and one placeholder section.

## Real content

This explains the topic in two sentences.

## Open questions

_(to be filled)_
"""


class TestStubScore:
    def test_substantive_body_scores_zero(self):
        assert stub_score(SUBSTANTIVE_BODY) == 0.0

    def test_stub_body_scores_high(self):
        # 6 placeholder lines + 2 lines of "Tool: Bash" / Command framing.
        # Placeholder fraction should be well over 0.5.
        assert stub_score(STUB_BODY) >= 0.5

    def test_mixed_body_scores_between(self):
        score = stub_score(MIXED_BODY)
        assert 0.0 < score < 1.0

    def test_empty_body_scores_zero(self):
        assert stub_score("") == 0.0
        assert stub_score("   \n  \n") == 0.0


class TestIsStub:
    def test_substantive_is_not_stub(self):
        assert is_stub(SUBSTANTIVE_BODY) is False

    def test_stub_is_stub(self):
        assert is_stub(STUB_BODY) is True

    def test_mixed_below_threshold_is_not_stub(self):
        # The mixed body has 1 placeholder line vs 2 content lines → 0.33,
        # below the default 0.5 threshold.
        assert is_stub(MIXED_BODY) is False

    def test_threshold_param(self):
        # Tightening the threshold catches the mixed page.
        assert is_stub(MIXED_BODY, threshold=0.2) is True

    def test_all_placeholder_is_always_stub(self):
        body = "## A\n\n_(to be filled)_\n\n## B\n\n_To be written._\n"
        # Score is 1.0 — every content line is placeholder.
        assert is_stub(body, threshold=0.99) is True


class TestPurgeCap:
    """The autonomous wiki maintenance runs with a per-cycle deletion cap
    so a buggy classifier change can't wipe the wiki in one shot. The
    cap is a safety rail, not a policy decision — under normal
    operation cleanup proceeds gradually until the backlog clears.
    """

    def _make_stub_pages(self, root, n):
        body = "_(to be filled)_\n_To be written._\n"
        for i in range(n):
            path = pathlib.Path(root) / "lessons" / "p" / f"stub-{i:03d}.md"
            path.parent.mkdir(exist_ok=True, parents=True)
            with path.open("w") as f:
                f.write(f"---\ntitle: stub {i}\nkind: lesson\n---\n\n{body}")

    def test_cap_limits_per_cycle_purges(self, tmp_path, monkeypatch):
        import asyncio
        from mcp_server.handlers import wiki_purge as wp

        monkeypatch.setattr(wp, "WIKI_ROOT", str(tmp_path))
        self._make_stub_pages(str(tmp_path), 10)

        result = asyncio.run(
            wp.handler(
                {
                    "apply": True,
                    "purge_stubs": True,
                    "purge_classifier_rejects": False,
                    "max_purges": 3,
                }
            )
        )
        # 3 pages deleted, 7 deferred to the next cycle.
        assert result["purged"] == 3
        assert result["deferred"] == 7
        assert result["cap_reached"] is True
        assert result["max_purges"] == 3

    def test_cap_zero_means_unlimited(self, tmp_path, monkeypatch):
        import asyncio
        from mcp_server.handlers import wiki_purge as wp

        monkeypatch.setattr(wp, "WIKI_ROOT", str(tmp_path))
        self._make_stub_pages(str(tmp_path), 7)

        result = asyncio.run(
            wp.handler(
                {
                    "apply": True,
                    "purge_stubs": True,
                    "purge_classifier_rejects": False,
                    "max_purges": 0,
                }
            )
        )
        assert result["purged"] == 7
        assert result["deferred"] == 0
        assert result["cap_reached"] is False
        assert result["max_purges"] is None


class TestPlaceholderCount:
    def test_counts_all_marker_variants(self):
        body = (
            "_(to be filled)_\n_To be written._\n_(none identified)_\nTBD\nreal prose\n"
        )
        assert placeholder_count(body) == 4

    def test_empty_body(self):
        assert placeholder_count("") == 0
