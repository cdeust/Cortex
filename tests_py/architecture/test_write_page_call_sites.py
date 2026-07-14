"""Issue #110: guard against a new, unreviewed direct caller of
``wiki_store.write_page`` appearing silently.

Frontmatter normalization (issue #107) is now enforced unconditionally
inside ``write_page`` itself (see that function's docstring), so a new
direct caller can no longer persist non-canonical frontmatter — that
corruption class is closed structurally. What this test protects
against is different: ``write_governed_page``
(``mcp_server/handlers/wiki_write.py``) is the ONLY place that registers
pointer-memory + citation governance for a wiki write. Every existing
direct ``write_page`` caller was individually audited (see the whitelist
below and each call site's own surrounding comment/docstring) as a
deliberate governance bypass — e.g. a redirect stub, a generated
reference/PRD/finding page, an ADR, or a link-frontmatter rewrite, none
of which should acquire a citable pointer memory. A new direct caller
that appears without being added here has NOT been through that review;
this test fails loudly so the reviewer either (a) adds it to the
whitelist with a one-line justification, or (b) routes it through
``write_governed_page`` instead.
"""

from __future__ import annotations

import re
from pathlib import Path

MCP_SERVER_ROOT = Path(__file__).resolve().parents[2] / "mcp_server"

# The one module allowed to *define* write_page — excluded from the scan
# entirely (its own `def write_page(` would otherwise match the call regex).
_DEFINITION_MODULE = MCP_SERVER_ROOT / "infrastructure" / "wiki_store.py"

# A call is `write_page(` not preceded by an identifier character (so
# `_rewrite_page(` — a different, unrelated function — never matches).
_CALL_RE = re.compile(r"(?<![A-Za-z0-9_])write_page\(")

# Audited whitelist: relative path (from mcp_server/) -> expected number of
# direct write_page(...) call expressions in that file. Each entry below
# was reviewed as a deliberate governance bypass (see module docstring);
# adding a NEW call increases the count and must update this table —
# forcing the reviewer to consciously decide whether the new write
# belongs here or should route through write_governed_page instead.
_EXPECTED_CALL_COUNTS = {
    "handlers/ingest_prd.py": 1,  # generated PRD spec page, no citations
    "handlers/ingest_findings_writers.py": 1,  # generated finding page
    "handlers/wiki_adr.py": 1,  # ADR creation (own pointer-memory path)
    "handlers/wiki_rename.py": 2,  # destination copy + redirect stub
    "handlers/ingest_codebase_pages.py": 1,  # generated process reference page
    "handlers/wiki_link.py": 1,  # in-place frontmatter link rewrite
    "handlers/wiki_write.py": 1,  # write_governed_page's own delegation call
    "handlers/wiki_compile.py": 1,  # publishing an already-curated draft
}


def _iter_python_files():
    for path in MCP_SERVER_ROOT.rglob("*.py"):
        if path == _DEFINITION_MODULE:
            continue
        yield path


def test_write_page_direct_callers_match_audited_whitelist() -> None:
    observed: dict[str, int] = {}
    for path in _iter_python_files():
        text = path.read_text(encoding="utf-8")
        count = len(_CALL_RE.findall(text))
        if count:
            rel = str(path.relative_to(MCP_SERVER_ROOT)).replace("\\", "/")
            observed[rel] = count

    unexpected_files = sorted(set(observed) - set(_EXPECTED_CALL_COUNTS))
    missing_files = sorted(set(_EXPECTED_CALL_COUNTS) - set(observed))
    mismatched_counts = {
        rel: (observed[rel], _EXPECTED_CALL_COUNTS[rel])
        for rel in set(observed) & set(_EXPECTED_CALL_COUNTS)
        if observed[rel] != _EXPECTED_CALL_COUNTS[rel]
    }

    assert not unexpected_files, (
        "New direct caller(s) of write_page() found, not in the audited "
        f"whitelist: {unexpected_files}. Either add them to "
        "_EXPECTED_CALL_COUNTS with a one-line justification (why this "
        "write doesn't need write_governed_page's pointer-memory/citation "
        "bookkeeping), or route the write through write_governed_page "
        "instead."
    )
    assert not missing_files, (
        f"Whitelisted file(s) no longer call write_page(): {missing_files}. "
        "Remove the stale entry from _EXPECTED_CALL_COUNTS."
    )
    assert not mismatched_counts, (
        "Call count changed for whitelisted file(s) (observed, expected): "
        f"{mismatched_counts}. A new write_page() call was added to an "
        "already-whitelisted file — review it the same way as a brand new "
        "caller and update the expected count once satisfied."
    )
