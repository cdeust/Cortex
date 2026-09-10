# ADR-0717: scripts/check_version_surfaces.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/check_version_surfaces.py`; original SHA-256 `bb7165de32c4cd33564015ed6c5a1bb394f7257f255b48bd702a31d3b62d5992`.

## Original docstring, lines 1–41

````text
"""Version-coherence gate: every version site in the repo must agree.

Three gates already touch a version number, and each trusts a DIFFERENT
canonical source:

- ``check_doc_claims.py``'s (now removed) ``check_versions`` compared
  ``manifest.json``/``server.json``/``package.json``/the version badge
  against ``pyproject.toml``.
- ``check_marketplace_pins.py`` compares ``server.json``/``manifest.json``
  against the marketplace's *own* primary pin (not pyproject.toml), and only
  for the two files it happens to enumerate.
- ``tests_py/scripts/test_cross_host_manifests.py`` compares four more
  manifests against ``package.json`` (not pyproject.toml either).

Two sites were covered by NOTHING: ``server.json``'s
``packages[0].version`` (the MCP-registry package entry, served to every
registry client) and ``.claude-plugin/marketplace.json``'s
``metadata.version``. A partial version bump can reach ``main`` and only be
caught by the weekly ``marketplace-pins`` cron, which is not part of the
``ci-green`` aggregate (issue #392).

This module is the single authoritative source: every version site is
compared against ONE canonical value, ``[project].version`` in
``pyproject.toml`` (via ``doc_claim_sources.canonical_version``, the same
reader ``check_doc_claims.py`` uses). ``SURFACES`` is DATA — a tuple of
no-argument-bound check callables built by ``functools.partial`` over three
small, pure functions (``_json_check``, ``_badge_check``,
``_uv_lock_check``/``_marketplace_primary_plugin_check``) — so adding a 15th
surface of an existing kind (another JSON file/key, another badge
occurrence) is a one-line data edit, never a new branch in
``check_version_surfaces`` itself (OCP).

Badge parsing reuses ``doc_claim_structural.check_badge`` verbatim (fails
closed on a missing file or an unmatched pattern) rather than reimplementing
it; the pyproject version regex is reused from ``doc_claim_sources`` rather
than re-derived here.

Usage::

    python scripts/check_version_surfaces.py
"""
````

## Original comment, lines 54–56

````text
# Sibling modules, path-imported for the same reason check_doc_claims.py does
# it: resolves identically whether this runs as a script or is loaded via
# importlib.util.spec_from_file_location from a test.
````

## Original comment, lines 70–70

````text
# docstring for why (non-ASCII prose, locale-dependent defaults).
````

## Original comment, lines 110–115

````text
# The badge is a generated SVG (scripts/generate_repo_badges.py) that states
# its version four times: the accessible aria-label, the <title> (reused
# from doc_claim_structural.VERSION_BADGE below), and a drop-shadow + solid
# <text> pair. Each occurrence can desync independently of the others (a
# hand-edit, or a future template change to only one of them), so each is
# its own surface rather than one "the badge" surface.
````

## Original docstring, lines 122–128

````text
"""The self-hosted (primary) marketplace plugin entry's own version.

    Selection rule mirrors check_marketplace_pins.main's own primary-entry
    predicate (`source.strip("/") in ("", ".")`) verbatim, rather than
    re-deriving a second notion of "the primary plugin" that could disagree
    with it.
    """
````

## Original docstring, lines 158–164

````text
"""The root `hypermnesia-mcp` package block's own version.

    uv.lock is TOML, but read line-by-line rather than parsed: this repo's
    floor is Python 3.10, where `tomllib` does not exist — the same
    rationale scripts/generate_pip_constraints.py's lock_registries uses for
    the identical [[package]]/name/version scan.
    """
````

