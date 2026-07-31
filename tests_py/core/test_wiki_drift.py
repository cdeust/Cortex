"""Tests for wiki_drift — existing-page re-author detection."""

from __future__ import annotations

import os
import time

from mcp_server.core.wiki_drift import (
    REASON_MISSING_LINK,
    REASON_MISSING_SOURCE,
    REASON_OFF_TEMPLATE,
    REASON_STALE,
    audit_page_drift,
    audit_wiki_drift,
)
import pathlib


def _write(path: str, content: str) -> None:
    pathlib.Path(path).parent.mkdir(exist_ok=True, parents=True)
    with pathlib.Path(path).open("w", encoding="utf-8") as f:
        f.write(content)


ADR_BODY_WITH_SOURCE = """\
---
title: Foo
kind: adr
updated: 2026-01-01
---

# ADR: Foo

## Status

accepted

## Entry

Used `mcp_server/core/foo.py` to do bar.

## Mandatory elements

- Clean Architecture

## How

Edited `mcp_server/core/foo.py`.

## Result

Done.

## Serves

System.
"""


SHORT_ADR_BODY = """\
---
title: Foo
kind: adr
updated: 2026-04-01
---

# ADR: Foo

Just some prose.
"""


class TestAuditPageDrift:
    def test_no_drift_when_source_exists_and_recent(self, tmp_path):
        wiki = tmp_path / "wiki"
        src = tmp_path / "src"
        _write(str(wiki / "adr" / "p" / "0001-foo.md"), ADR_BODY_WITH_SOURCE)
        _write(str(src / "mcp_server" / "core" / "foo.py"), "x")
        # All sections present, source exists, mtime is "now".
        d = audit_page_drift(str(wiki), "adr/p/0001-foo.md", str(src), max_age_days=365)
        assert d is None

    def test_missing_source_file_flagged(self, tmp_path):
        wiki = tmp_path / "wiki"
        src = tmp_path / "src"
        src.mkdir()
        _write(str(wiki / "adr" / "p" / "0001-foo.md"), ADR_BODY_WITH_SOURCE)
        # Source root exists but foo.py is missing.
        d = audit_page_drift(str(wiki), "adr/p/0001-foo.md", str(src), max_age_days=365)
        assert d is not None
        assert REASON_MISSING_SOURCE in d.reasons
        assert "mcp_server/core/foo.py" in d.missing_source_files

    def test_stale_when_mtime_old_and_cites_source(self, tmp_path):
        wiki = tmp_path / "wiki"
        src = tmp_path / "src"
        page = wiki / "adr" / "p" / "0001-foo.md"
        _write(str(page), ADR_BODY_WITH_SOURCE)
        _write(str(src / "mcp_server" / "core" / "foo.py"), "x")
        # Backdate page by 120 days.
        old = time.time() - 120 * 86400
        os.utime(str(page), (old, old))
        d = audit_page_drift(str(wiki), "adr/p/0001-foo.md", str(src), max_age_days=60)
        assert d is not None
        assert REASON_STALE in d.reasons

    def test_off_template_when_required_sections_missing(self, tmp_path):
        wiki = tmp_path / "wiki"
        src = tmp_path / "src"
        src.mkdir()
        _write(
            str(wiki / "adr" / "p" / "0001-foo.md"),
            SHORT_ADR_BODY,
        )
        d = audit_page_drift(str(wiki), "adr/p/0001-foo.md", str(src), max_age_days=365)
        assert d is not None
        assert REASON_OFF_TEMPLATE in d.reasons

    def test_technology_names_not_flagged_as_missing(self, tmp_path):
        """Product names like Node.js / Three.js match the path regex but
        are technologies, not source files — they must not fire the
        missing-source axis (false positive observed 2026-06-11)."""
        wiki = tmp_path / "wiki"
        src = tmp_path / "src"
        src.mkdir()
        body = ADR_BODY_WITH_SOURCE.replace(
            "Used `mcp_server/core/foo.py` to do bar.",
            "A zero-dep Node.js MCP server rendering via Three.js.",
        ).replace("Edited `mcp_server/core/foo.py`.", "Edited nothing.")
        _write(str(wiki / "adr" / "p" / "0001-foo.md"), body)
        d = audit_page_drift(str(wiki), "adr/p/0001-foo.md", str(src), max_age_days=365)
        if d is not None:
            assert REASON_MISSING_SOURCE not in d.reasons
            assert "Node.js" not in d.missing_source_files
            assert "Three.js" not in d.missing_source_files

    def test_no_source_root_skips_missing_check(self, tmp_path):
        """Pages from domains without a checked-out tree don't trigger
        the missing-source-file axis."""
        wiki = tmp_path / "wiki"
        _write(
            str(wiki / "adr" / "_general" / "0001-foo.md"),
            ADR_BODY_WITH_SOURCE,
        )
        d = audit_page_drift(
            str(wiki),
            "adr/_general/0001-foo.md",
            None,
            max_age_days=365,
        )
        # No source root → no missing-source flag. Other reasons may still fire.
        if d is not None:
            assert REASON_MISSING_SOURCE not in d.reasons

    def test_reference_page_without_link_flagged_missing_link(self, tmp_path):
        """A source-documenting page with no frontmatter documents: and
        no groundable body citation is missing-link drift (ADR-0051
        STEP 3 — REASON_MISSING_LINK)."""
        wiki = tmp_path / "wiki"
        body = """\
---
title: Foo
kind: reference
updated: 2026-01-01
---

# `mcp_server/core/foo.py`

## Scope

Undocumented linkage.

## API

None cited here.
"""
        _write(str(wiki / "reference" / "cortex" / "foo.md"), body)
        d = audit_page_drift(
            str(wiki), "reference/cortex/foo.md", None, max_age_days=365
        )
        assert d is not None
        assert REASON_MISSING_LINK in d.reasons

    def test_reference_page_with_frontmatter_documents_not_flagged(self, tmp_path):
        """A page whose frontmatter already declares documents: is
        linked — REASON_MISSING_LINK must not fire even without a
        source root to verify against."""
        wiki = tmp_path / "wiki"
        body = """\
---
title: Foo
kind: reference
updated: 2026-01-01
documents: mcp_server/core/foo.py
---

# `mcp_server/core/foo.py`

## Scope

Documented linkage.

## API

N/A.
"""
        _write(str(wiki / "reference" / "cortex" / "foo.md"), body)
        d = audit_page_drift(
            str(wiki), "reference/cortex/foo.md", None, max_age_days=365
        )
        if d is not None:
            assert REASON_MISSING_LINK not in d.reasons

    def test_non_reference_kind_never_flagged_missing_link(self, tmp_path):
        """An ADR page doesn't claim to document a single source file,
        so REASON_MISSING_LINK never applies to it."""
        wiki = tmp_path / "wiki"
        src = tmp_path / "src"
        _write(str(wiki / "adr" / "p" / "0001-foo.md"), ADR_BODY_WITH_SOURCE)
        _write(str(src / "mcp_server" / "core" / "foo.py"), "x")
        d = audit_page_drift(str(wiki), "adr/p/0001-foo.md", str(src), max_age_days=365)
        if d is not None:
            assert REASON_MISSING_LINK not in d.reasons


class TestAuditWikiDrift:
    def test_walks_every_page(self, tmp_path):
        wiki = tmp_path / "wiki"
        src_a = tmp_path / "a"
        src_b = tmp_path / "b"
        src_a.mkdir()
        src_b.mkdir()
        # Page A: missing source → drifted.
        _write(str(wiki / "adr" / "a" / "0001-foo.md"), ADR_BODY_WITH_SOURCE)
        # Page B: source exists → clean.
        _write(str(wiki / "adr" / "b" / "0001-foo.md"), ADR_BODY_WITH_SOURCE)
        _write(str(src_b / "mcp_server" / "core" / "foo.py"), "x")

        def resolver(domain):
            return {"a": str(src_a), "b": str(src_b)}.get(domain)

        drifts = audit_wiki_drift(str(wiki), resolver, max_age_days=365)
        # Only page A drifts.
        paths = {d.wiki_path for d in drifts}
        assert "adr/a/0001-foo.md" in paths
        assert "adr/b/0001-foo.md" not in paths

    def test_limit_caps_returned(self, tmp_path):
        wiki = tmp_path / "wiki"
        src = tmp_path / "src"
        src.mkdir()
        for i in range(10):
            _write(
                str(wiki / "adr" / "p" / f"{i:04d}-foo.md"),
                ADR_BODY_WITH_SOURCE,
            )

        def resolver(_):
            return str(src)

        drifts = audit_wiki_drift(str(wiki), resolver, max_age_days=365, limit=3)
        assert len(drifts) == 3
