# ADR-0777: scripts/refresh_mcp_toplist_badge.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/refresh_mcp_toplist_badge.py`; original SHA-256 `55e193909eb2ce3201c877d9bd014f7c18db251d0c8663c33a0f53776cdad822`.

## Original docstring, lines 2–21

````text
"""Regenerate assets/badge-mcp-toplist.svg from upstream MCP Toplist data.

The badge is a committed static file, not a hotlinked remote image, so it
cannot restate itself without a commit in our history. The cost of that
choice is that it cannot self-update: the date it carries is part of the
claim, and goes stale by INACTION. Inaction never opens a PR, so this
script exists to be run on a cron and propose the refresh.

The data acquisition (fetch, the two parser strategies, and shared
validation) lives in the sibling module mcp_toplist_ranking.py — see its
docstring for the two extraction paths and their fallback order. This
file re-exports every one of its public names (`import X as X`, mirroring
condensers.py's issue #228 facade), so every existing import path and
test-patch target keeps resolving unchanged; the split is an internal
reorganization; this file's own job is rendering the SVG and the CLI.

Usage:
    python3 scripts/refresh_mcp_toplist_badge.py           # rewrite if changed
    python3 scripts/refresh_mcp_toplist_badge.py --check   # exit 1 if stale
"""
````

## Original comment, lines 30–34

````text
# badge_render.py and mcp_toplist_ranking.py are stdlib-only sibling
# modules. Path-based import for the same reason the launcher family
# path-imports its siblings: resolves identically whether this file is run
# as a script (script dir already on sys.path) or loaded directly via
# importlib.util.spec_from_file_location from a test.
````

## Original comment, lines 55–57

````text
# The left panel carries the fixed string "MCP Toplist", so unlike the right
# panel its geometry never varies with the data. Both measured 2026-07-28 by
# rendering: 64px of text inside a 92px panel (icon + padding).
````

