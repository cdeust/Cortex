"""Tests for wiki_identity — stable page IDs (Phase 3 of ADR-2244)."""

from __future__ import annotations

import re

import pytest

from mcp_server.core.wiki_identity import (
    PageIdentity,
    ensure_page_id,
    extract_memory_id,
    extract_page_id,
    generate_page_id,
    is_valid_page_id,
    page_identity_from_frontmatter,
)


# ── Format validation ──────────────────────────────────────────────────


def test_valid_uuid4_accepted() -> None:
    assert is_valid_page_id("adfb8a1f-1b58-4f0c-9a7e-4c5e6c8d9f12")


def test_uppercase_uuid_accepted() -> None:
    assert is_valid_page_id("ADFB8A1F-1B58-4F0C-9A7E-4C5E6C8D9F12")


def test_uuid1_rejected() -> None:
    """UUID1 has version 1 in the third group — we require UUID4 (version 4)."""
    assert not is_valid_page_id("adfb8a1f-1b58-1f0c-9a7e-4c5e6c8d9f12")


def test_short_string_rejected() -> None:
    assert not is_valid_page_id("not-a-uuid")
    assert not is_valid_page_id("")


def test_missing_hyphens_rejected() -> None:
    assert not is_valid_page_id("adfb8a1f1b584f0c9a7e4c5e6c8d9f12")


def test_extra_characters_rejected() -> None:
    assert not is_valid_page_id("adfb8a1f-1b58-4f0c-9a7e-4c5e6c8d9f12-tail")


# ── Generation ────────────────────────────────────────────────────────


def test_generate_returns_valid_id() -> None:
    page_id = generate_page_id()
    assert is_valid_page_id(page_id)


def test_generated_ids_are_unique() -> None:
    """100 successive draws should not collide (Birthday paradox makes
    collision in this space astronomically unlikely)."""
    seen = {generate_page_id() for _ in range(100)}
    assert len(seen) == 100


def test_generated_id_is_lowercase_hex() -> None:
    page_id = generate_page_id()
    assert page_id == page_id.lower()
    # Strip hyphens and check it's all hex.
    assert re.fullmatch(r"[0-9a-f]+", page_id.replace("-", ""))


# ── Extraction ─────────────────────────────────────────────────────────


def test_extract_returns_existing_id() -> None:
    fm = {"id": "adfb8a1f-1b58-4f0c-9a7e-4c5e6c8d9f12", "title": "foo"}
    assert extract_page_id(fm) == "adfb8a1f-1b58-4f0c-9a7e-4c5e6c8d9f12"


def test_extract_normalises_case() -> None:
    fm = {"id": "ADFB8A1F-1B58-4F0C-9A7E-4C5E6C8D9F12"}
    assert extract_page_id(fm) == "adfb8a1f-1b58-4f0c-9a7e-4c5e6c8d9f12"


def test_extract_returns_none_for_missing() -> None:
    assert extract_page_id({"title": "no id"}) is None


def test_extract_returns_none_for_malformed() -> None:
    assert extract_page_id({"id": "garbage"}) is None
    assert extract_page_id({"id": 42}) is None


def test_extract_memory_id_int() -> None:
    assert extract_memory_id({"memory_id": 1234}) == 1234


def test_extract_memory_id_string_coerce() -> None:
    assert extract_memory_id({"memory_id": "1234"}) == 1234


def test_extract_memory_id_invalid_returns_none() -> None:
    assert extract_memory_id({"memory_id": "not-a-number"}) is None
    assert extract_memory_id({"memory_id": None}) is None
    assert extract_memory_id({}) is None


# ── ensure_page_id (mint-if-missing) ──────────────────────────────────


def test_ensure_returns_existing_id_without_minting() -> None:
    fm = {"id": "adfb8a1f-1b58-4f0c-9a7e-4c5e6c8d9f12"}
    page_id, minted = ensure_page_id(fm)
    assert page_id == "adfb8a1f-1b58-4f0c-9a7e-4c5e6c8d9f12"
    assert minted is False


def test_ensure_mints_when_missing() -> None:
    page_id, minted = ensure_page_id({"title": "no id"})
    assert is_valid_page_id(page_id)
    assert minted is True


def test_ensure_mints_when_existing_is_malformed() -> None:
    """A malformed existing id is treated as if it weren't there."""
    page_id, minted = ensure_page_id({"id": "garbage"})
    assert is_valid_page_id(page_id)
    assert minted is True
    assert page_id != "garbage"


# ── PageIdentity dataclass ────────────────────────────────────────────


def test_page_identity_construction() -> None:
    pid = PageIdentity(page_id=generate_page_id(), memory_id=42)
    assert pid.memory_id == 42


def test_page_identity_rejects_invalid_id() -> None:
    with pytest.raises(ValueError, match="invalid page_id"):
        PageIdentity(page_id="not-a-uuid")


def test_page_identity_from_frontmatter_full() -> None:
    fm = {
        "id": "adfb8a1f-1b58-4f0c-9a7e-4c5e6c8d9f12",
        "memory_id": 99,
        "title": "irrelevant",
    }
    pid = page_identity_from_frontmatter(fm)
    assert pid is not None
    assert pid.page_id == "adfb8a1f-1b58-4f0c-9a7e-4c5e6c8d9f12"
    assert pid.memory_id == 99


def test_page_identity_from_frontmatter_no_id_returns_none() -> None:
    assert page_identity_from_frontmatter({"title": "no id"}) is None
