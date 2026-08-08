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

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable
from functools import partial
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Sibling modules, path-imported for the same reason check_doc_claims.py does
# it: resolves identically whether this runs as a script or is loaded via
# importlib.util.spec_from_file_location from a test.
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
import doc_claim_sources  # noqa: E402
import doc_claim_structural  # noqa: E402
from doc_claim_sources import ClaimError  # noqa: E402  (re-export)

ReadFn = Callable[[str], str]
SurfaceCheck = Callable[[ReadFn, str], list[str]]


def read(relative_path: str) -> str:
    # encoding="utf-8" pinned explicitly — see check_doc_claims.read's own
    # docstring for why (non-ASCII prose, locale-dependent defaults).
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def canonical_version() -> str:
    return doc_claim_sources.canonical_version(read)


def _json_check(
    path: str, keys: tuple[str | int, ...], label: str, read_fn: ReadFn, expected: str
) -> list[str]:
    """A version nested at `keys` inside a JSON file must match `expected`."""
    try:
        body = read_fn(path)
    except FileNotFoundError:
        return [f"{path}: missing — the version-surfaces gate reads it"]
    try:
        value: object = json.loads(body)
        for key in keys:
            value = value[key]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        return [f"{path}: {label}: could not read a version there ({error})"]
    if value != expected:
        return [f"{path}: {label}: version {value!r}, pyproject says {expected!r}"]
    return []


def _badge_check(
    pattern: re.Pattern[str], label: str, read_fn: ReadFn, expected: str
) -> list[str]:
    """One of the four textual version occurrences in the version-badge SVG.

    Delegates entirely to doc_claim_structural.check_badge — no badge parsing
    lives in this module.
    """
    return doc_claim_structural.check_badge(
        "assets/badge-version.svg", pattern, expected, label, read_fn
    )


# The badge is a generated SVG (scripts/generate_repo_badges.py) that states
# its version four times: the accessible aria-label, the <title> (reused
# from doc_claim_structural.VERSION_BADGE below), and a drop-shadow + solid
# <text> pair. Each occurrence can desync independently of the others (a
# hand-edit, or a future template change to only one of them), so each is
# its own surface rather than one "the badge" surface.
_BADGE_ARIA_LABEL = re.compile(r'aria-label="Version (\d+\.\d+\.\d+)"')
_BADGE_SHADOW_TEXT = re.compile(r'fill-opacity="0.25"[^>]*>(\d+\.\d+\.\d+)</text>')
_BADGE_SOLID_TEXT = re.compile(r'fill="#fff"[^>]*>(\d+\.\d+\.\d+)</text>')


def _marketplace_primary_plugin_check(read_fn: ReadFn, expected: str) -> list[str]:
    """The self-hosted (primary) marketplace plugin entry's own version.

    Selection rule mirrors check_marketplace_pins.main's own primary-entry
    predicate (`source.strip("/") in ("", ".")`) verbatim, rather than
    re-deriving a second notion of "the primary plugin" that could disagree
    with it.
    """
    path = ".claude-plugin/marketplace.json"
    label = "primary plugin entry version"
    try:
        data = json.loads(read_fn(path))
    except (FileNotFoundError, json.JSONDecodeError) as error:
        return [f"{path}: {label}: could not read the marketplace manifest ({error})"]
    entries = [
        plugin
        for plugin in data.get("plugins", [])
        if isinstance(plugin.get("source"), str)
        and plugin["source"].strip("/") in ("", ".")
    ]
    if len(entries) != 1:
        return [
            f"{path}: {label}: expected exactly one self-hosted plugin entry, "
            f"found {len(entries)}"
        ]
    value = entries[0].get("version")
    if value != expected:
        return [f"{path}: {label}: version {value!r}, pyproject says {expected!r}"]
    return []


# The root package uv.lock resolved from this repo's own pyproject.toml
# (`source = { editable = "." }`).
_UV_LOCK_PACKAGE = "hypermnesia-mcp"


def _uv_lock_check(read_fn: ReadFn, expected: str) -> list[str]:
    """The root `hypermnesia-mcp` package block's own version.

    uv.lock is TOML, but read line-by-line rather than parsed: this repo's
    floor is Python 3.10, where `tomllib` does not exist — the same
    rationale scripts/generate_pip_constraints.py's lock_registries uses for
    the identical [[package]]/name/version scan.
    """
    path = "uv.lock"
    label = f"{_UV_LOCK_PACKAGE} package block"
    name: str | None = None
    version: str | None = None
    for line in read_fn(path).splitlines():
        if line.startswith("[[package]]"):
            name, version = None, None
        elif line.startswith('name = "'):
            name = line.split('"')[1]
        elif line.startswith('version = "'):
            version = line.split('"')[1]
        if name == _UV_LOCK_PACKAGE and version is not None:
            break
    else:
        # The loop ran to completion without finding our package: whatever
        # `version` last held belongs to a DIFFERENT package block.
        version = None
    if version is None:
        return [f"{path}: {label}: no version found for {_UV_LOCK_PACKAGE!r}"]
    if version != expected:
        return [f"{path}: {label}: version {version!r}, pyproject says {expected!r}"]
    return []


# One row per version site (14 sites across 11 files). Adding a 15th JSON
# site or badge occurrence is a one-line addition here; only a genuinely new
# FILE FORMAT (neither JSON, regex-matchable text, nor uv.lock's own shape)
# would need a new `_..._check` function alongside it.
SURFACES: tuple[SurfaceCheck, ...] = (
    partial(_json_check, "package.json", ("version",), "version"),
    partial(_json_check, "server.json", ("version",), "version"),
    partial(
        _json_check, "server.json", ("packages", 0, "version"), "packages[0].version"
    ),
    partial(_json_check, "manifest.json", ("version",), "version"),
    partial(_json_check, "gemini-extension.json", ("version",), "version"),
    partial(_json_check, ".claude-plugin/plugin.json", ("version",), "version"),
    partial(
        _json_check,
        ".claude-plugin/marketplace.json",
        ("metadata", "version"),
        "metadata.version",
    ),
    _marketplace_primary_plugin_check,
    partial(
        _json_check,
        "plugins/hypermnesia-mcp-codex/.codex-plugin/plugin.json",
        ("version",),
        "version",
    ),
    partial(_badge_check, _BADGE_ARIA_LABEL, "aria-label"),
    partial(_badge_check, doc_claim_structural.VERSION_BADGE, "<title>"),
    partial(_badge_check, _BADGE_SHADOW_TEXT, "shadow <text>"),
    partial(_badge_check, _BADGE_SOLID_TEXT, "solid <text>"),
    _uv_lock_check,
)


def check_version_surfaces(read_fn: ReadFn) -> list[str]:
    """Every version site's failures, against the canonical pyproject.toml one.

    Raises ClaimError (uncaught) if pyproject.toml itself cannot be read —
    the gate cannot run blind, the same contract check_doc_claims.py's
    canonical readers use.
    """
    expected = doc_claim_sources.canonical_version(read_fn)
    failures: list[str] = []
    for surface_check in SURFACES:
        failures += surface_check(read_fn, expected)
    return failures


def main() -> int:
    try:
        failures = check_version_surfaces(read)
    except ClaimError as error:
        print(f"version-surfaces gate could not run: {error}", file=sys.stderr)
        return 2

    if failures:
        print("Version surfaces disagree with pyproject.toml:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1
    print(
        f"version surfaces OK ({len(SURFACES)} site(s) checked, "
        "all agree with pyproject.toml)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
