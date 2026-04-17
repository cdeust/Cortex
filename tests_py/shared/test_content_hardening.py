"""Phase 7 hardening: content ingestion tests.

Asserts that harden_content() applied at the write boundary:
  * composes Unicode to NFC (defeats dupe creation from decomposed form)
  * strips control / BOM / bidi-override characters
  * caps byte length to prevent ReDoS amplification

Source: docs/program/phase-5-pool-admission-design.md §7 (hardening);
CVE-2021-42574 (Trojan Source).
"""

from __future__ import annotations

import pytest

from mcp_server.shared.content_hardening import CONTENT_MAX_BYTES, harden_content


class TestNFCNormalization:
    def test_composed_and_decomposed_hash_equal(self):
        composed = "café"  # contains U+00E9
        decomposed = "cafe\u0301"  # U+0065 + U+0301
        assert harden_content(composed) == harden_content(decomposed)

    def test_already_nfc_unchanged(self):
        s = "Hello, world!"
        assert harden_content(s) == s

    def test_emoji_preserved(self):
        s = "🎉 party"
        assert harden_content(s) == s


class TestControlStripping:
    def test_null_removed(self):
        assert harden_content("hello\x00world") == "helloworld"

    def test_bom_removed(self):
        assert harden_content("\ufeffhello") == "hello"

    def test_tabs_and_newlines_preserved(self):
        s = "line1\nline2\tcolumn"
        assert harden_content(s) == s

    def test_carriage_return_preserved(self):
        assert harden_content("a\rb") == "a\rb"

    def test_c1_control_removed(self):
        # U+0085 (Next Line) is C1
        assert harden_content("a\u0085b") == "ab"

    def test_bidi_override_stripped(self):
        """CVE-2021-42574 trojan-source attack vector — we strip the
        override characters so they cannot flip source display."""
        trojan = "access = not allowed\u202e;drop"
        out = harden_content(trojan)
        assert "\u202e" not in out
        assert "access = not allowed" in out


class TestByteCap:
    def test_under_cap_unchanged(self):
        s = "a" * 1000
        assert harden_content(s) == s

    def test_over_cap_truncated(self):
        # 2 MB of plain ASCII
        s = "x" * (2 * 1024 * 1024)
        out = harden_content(s)
        assert len(out.encode("utf-8")) <= CONTENT_MAX_BYTES

    def test_custom_cap(self):
        s = "x" * 1000
        out = harden_content(s, max_bytes=100)
        assert len(out.encode("utf-8")) <= 100

    def test_truncation_produces_valid_utf8(self):
        # Multi-byte chars at the boundary: cap 101 bytes with a
        # stream of 3-byte UTF-8 codepoints would leave orphaned bytes
        # without the errors='ignore' decode path.
        s = "€" * 100  # 300 bytes total (3 per €)
        out = harden_content(s, max_bytes=101)
        # Must decode cleanly — no UnicodeDecodeError
        out.encode("utf-8")
        # And contain only whole €s
        assert all(ch == "€" for ch in out)


class TestEmpty:
    def test_empty_string_returns_empty(self):
        assert harden_content("") == ""

    def test_control_only_returns_empty(self):
        assert harden_content("\x00\x01\x02\ufeff") == ""
