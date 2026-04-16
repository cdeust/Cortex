"""Tests for entity name canonicalization policy.

Source: Curie I4 audit (2026-04-16); policy defined in
mcp_server/shared/entity_canonical.py.
"""

from __future__ import annotations

import pytest

from mcp_server.shared.entity_canonical import canonicalize_entity_name


class TestCanonicalization:
    """Policy test matrix per docstring in entity_canonical.py."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            # Long all-caps → Title (the 111-group-dedup mechanism)
            ("OUTPUT", "Output"),
            ("STRING", "String"),
            ("DOMAIN", "Domain"),
            ("STATUS", "Status"),
            ("ZETETIC", "Zetetic"),
            # Iconic short acronyms preserved (length < 5)
            ("HTTP", "HTTP"),
            ("JSON", "JSON"),
            ("HTML", "HTML"),
            ("YAML", "YAML"),
            ("CURL", "CURL"),
            ("BASH", "BASH"),
            ("AI", "AI"),
            ("ML", "ML"),
            ("GPT", "GPT"),
            ("XML", "XML"),
            ("CSS", "CSS"),
            # Edge of cutoff — length 5 all-caps converts
            ("HTTPS", "Https"),
            ("XHTML", "Xhtml"),
            # Already canonical → preserve
            ("Output", "Output"),
            ("output", "output"),
            ("FilePath", "FilePath"),
            ("file_path", "file_path"),
            ("camelCase", "camelCase"),
            # Digits + underscores in all-caps — Title-case applies
            ("HTTP_2", "Http_2"),
            ("PHASE_3", "Phase_3"),
            # No-alpha strings pass through
            ("42", "42"),
            ("__init__", "__init__"),
            ("", ""),
            ("   ", ""),  # whitespace-only collapses to empty
            # Mixed case with digits
            ("A1B2", "A1B2"),  # not all-caps (B2 has digit, but alpha all upper)
        ],
    )
    def test_canonicalize(self, raw: str, expected: str) -> None:
        assert canonicalize_entity_name(raw) == expected

    def test_idempotent(self) -> None:
        """Canonicalizing twice must equal canonicalizing once."""
        for name in ["OUTPUT", "http", "FilePath", "JSON", "OUTPUT_DIR"]:
            once = canonicalize_entity_name(name)
            twice = canonicalize_entity_name(once)
            assert once == twice, (
                f"canonicalize({name}) = {once!r} but "
                f"canonicalize({once!r}) = {twice!r}"
            )

    def test_length_5_is_cutoff(self) -> None:
        """Exactly-5-char all-caps converts; exactly-4 preserves."""
        # 4 chars: preserved (iconic acronyms)
        assert canonicalize_entity_name("HTTP") == "HTTP"
        assert canonicalize_entity_name("JSON") == "JSON"
        assert canonicalize_entity_name("YAML") == "YAML"
        assert canonicalize_entity_name("HTML") == "HTML"
        # 5 chars: converted
        assert canonicalize_entity_name("HTTPS") == "Https"
        assert canonicalize_entity_name("XHTML") == "Xhtml"
        assert canonicalize_entity_name("STORE") == "Store"
