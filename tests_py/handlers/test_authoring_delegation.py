"""Tests for the agents-mode delegation hint in authoring prompts.

Validates that ``_delegation_hint`` maps page kinds to specialists and that
each of the three prompt builders splices the hint when given and omits it
(byte-for-byte unchanged shape) when ``delegate_hint=None`` (solo mode).
"""

from __future__ import annotations

from mcp_server.handlers.consolidation.authoring_prompts import (
    _DEFAULT_SPECIALIST,
    _build_page_prompt,
    _build_section_prompt,
    _delegation_hint,
)
from mcp_server.handlers.consolidation.page_io import _scope_anchor_prompt


def test_delegation_hint_maps_kind_to_specialist() -> None:
    assert "engineer" in _delegation_hint("api")
    assert "devops-engineer" in _delegation_hint("ci-cd")
    assert "architect" in _delegation_hint("architecture")
    # Unknown kind falls back to the default specialist.
    hint = _delegation_hint("totally-unknown-kind")
    assert _DEFAULT_SPECIALIST in hint
    assert "totally-unknown-kind" in hint  # kind echoed into the paragraph


def test_section_prompt_includes_hint_only_when_given() -> None:
    meta = {"domain": "d", "title": "T", "source_file_path": "x.py"}
    kw = dict(
        page_path="reference/d/x.md",
        page_meta=meta,
        gap_name="Purpose",
        gap_description="what it does",
        source_text=None,
    )
    with_hint = _build_section_prompt(**kw, delegate_hint=_delegation_hint("file-doc"))
    without = _build_section_prompt(**kw, delegate_hint=None)

    assert "You may delegate analysis" in with_hint
    assert "You may delegate analysis" not in without
    # Solo default (no kwarg) matches explicit None.
    assert _build_section_prompt(**kw) == without


def test_page_prompt_includes_hint_only_when_given() -> None:
    meta = {"domain": "d", "source_file_path": "x.py", "language": "python"}
    kw = dict(
        page_path="reference/d/x.md", page_meta=meta, gaps=["purpose"], source_text=None
    )
    with_hint = _build_page_prompt(**kw, delegate_hint=_delegation_hint("file-doc"))
    without = _build_page_prompt(**kw, delegate_hint=None)

    assert "You may delegate analysis" in with_hint
    assert "You may delegate analysis" not in without
    assert _build_page_prompt(**kw) == without


def test_anchor_prompt_includes_hint_only_when_given(tmp_path) -> None:
    kw = dict(
        domain="proj",
        scope_name="architecture",
        scope_title="Architecture",
        scope_description="desc",
        source_root=str(tmp_path),
    )
    with_hint = _scope_anchor_prompt(
        **kw, delegate_hint=_delegation_hint("architecture")
    )
    without = _scope_anchor_prompt(**kw, delegate_hint=None)

    assert "You may delegate analysis" in with_hint
    assert "You may delegate analysis" not in without
    assert _scope_anchor_prompt(**kw) == without


def test_hint_preserves_untrusted_guard() -> None:
    """The delegation hint must not displace the security guard header."""
    meta = {"domain": "d", "source_file_path": "x.py", "language": "python"}
    prompt = _build_page_prompt(
        page_path="reference/d/x.md",
        page_meta=meta,
        gaps=["purpose"],
        source_text="print('hi')",
        delegate_hint=_delegation_hint("file-doc"),
    )
    # Guard still leads; hint sits after the intro, before grounding section.
    assert prompt.startswith("SECURITY:")
    assert prompt.index("You may delegate") < prompt.index("Ground your writing")
