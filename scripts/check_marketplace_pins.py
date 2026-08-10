#!/usr/bin/env python3
"""Marketplace pin-staleness gate. CANONICAL COPY: cdeust/Cortex.

A byte-identical copy of this file AND its five sibling modules
(marketplace_pins_http.py, marketplace_pins_semver.py,
marketplace_pins_github.py, marketplace_pins_self.py,
marketplace_pins_manifests.py, marketplace_pins_registry.py) lives in
cdeust/ai-architect-mcp-codebase (its CI diffs against these files weekly
and fails on drift), so the gate is ONE artifact guarding both repos —
never two copies that diverge into a no-op. This file used to be the
whole gate in one file; it was split (issue: crossed the 300-line §4.1
cap once REGISTRY_VERSION_STALE was added) into a thin composition root
(this file: CLI entry point + per-plugin dispatch) over five single-
purpose modules — AP's mirror needs the same split or its weekly diff
will show it, which is the intended signal, not a regression.

Releasing does not ship: delivery is gated by pins in
``.claude-plugin/marketplace.json``. Six zetetic-team-subagents releases and
two cortex-viz releases were withheld silently (Cortex #179); AP's own
manifests sat a three-way split with its tag (AP #67). Failure classes:

- PIN_BEHIND_TAG: local-source pin < this repo's latest semver git tag.
  Offline, reads git only — detects the #67 incident even when every
  manifest agrees (they were BOTH stale).
- PIN_BEHIND_RELEASE: github-source pin < that repo's latest release, but
  a release matching the pin DOES exist.
- PIN_VERSION_UNPUBLISHED: the pinned version has no matching tag/release
  in the target repo AT ALL — not "behind", genuinely never cut.
  `PIN_BEHIND_*` only ever compared the pin to the *latest* known tag, so
  a pin sitting AHEAD of every real release (a version nobody ever
  tagged) read as "current" and passed silently. Incident: Cortex's own
  marketplace.json pinned `hypermnesia-mcp-viz` at cortex-viz version
  "3.0.0" for six days; cortex-viz's own tag history never contained a
  v3.0.0 — v2.8.0 was, and remained, the latest real tag. `3.0.0 < 2.8.0`
  is false, so the old `PIN_BEHIND_RELEASE` check never fired: a pin
  ahead of the truth is invisible to a "behind" comparison. Diagnostic
  method: put the declared versions and the actually-tagged versions
  side by side; the gap is only visible in the join, never in either
  list read alone, and never in the manifest file by itself — the
  manifest doesn't know what wasn't tagged.
- SELF_PIN_MISMATCH: local-source pin != the plugin's own plugin.json.
- SERVER_JSON_SPLIT: root server.json version != the primary local pin
  (the unguarded third leg of AP's three-way split).
- PIN_SHA_UNREACHABLE: github-source pin names a `sha` that is not
  reachable from that repo's default branch. Cortex #351 pinned
  cortex-viz twice at an unmerged PR head (ee0d41db, then 7e297ebc);
  both were `ahead` of main, so a squash-merge would have left the
  marketplace serving an orphaned commit. Version checks cannot see
  this: the pin read 3.0.0 and was current on every run.
- MANIFEST_JSON_SPLIT: root manifest.json version != the primary local
  pin. AP shipped manifest.json stuck at 0.8.0 for TWO releases while
  every other pin read 0.8.2 and this gate exited 0, because it only
  ever read server.json (AP #172). The file is copied verbatim into
  the .mcpb bundle, so the wrong version shipped to every install.
- REGISTRY_VERSION_STALE: the public MCP registry
  (registry.modelcontextprotocol.io) serves a version != this repo's
  authoritative one for server.json's own `name`. A THIRD version
  surface, independent of the marketplace pin and PyPI: measured
  2026-08-10, io.github.cdeust/hypermnesia-mcp was published at 4.17.1
  while the tag/server.json/PyPI were already at 4.17.2 — the registry
  publish step lived only in prose (no committed workflow ran it), same
  failure shape as #179 and PIN_VERSION_UNPUBLISHED above. Equality,
  not "behind": a registry entry ahead of the repo (a republish of an
  untagged version) is exactly as false as one that lags.
- UNVERIFIED_SOURCE_TYPE: a plugin's `source.source` is a schema-legal
  type (npm/url/git-subdir) this gate has no checker for. Never silent
  — a dispatcher recognizing only some schema-legal shapes and passing
  the rest through unflagged is the same defect class as the above.
- UNRECOGNIZED_SOURCE: a plugin's `source` matches no schema shape at
  all (wrong type, unknown `source` key) — same non-silence principle.

Network failures DEGRADE TO SILENCE (NOTICE + exit 0): a gate that reddens
every PR during a GitHub outage gets disabled, and then the six-release gap
recurs with the gate nominally in place. The offline path is tested.

Frozen pins: deliberately never-advancing pins (deprecation shims) are
listed in FROZEN_PINS (marketplace_pins_self.py) with a reason — audited
allowlist, not silence.

Pending pins: a pin correctly flagged PIN_VERSION_UNPUBLISHED because the
release that will cut its tag is genuinely in flight (tracked by an already
-open upstream PR, not a promise) is listed in PENDING_PINS
(marketplace_pins_github.py) with that PR's URL — printed every run as a
NOTICE, never swallowed, and dead code the moment the tag lands and the pin
is bumped to point at it (source: schema verified against
https://json.schemastore.org/claude-code-marketplace.json 2026-08-10 — the
github-source `source` object accepts an optional `ref` field, "Git branch
or tag to use", so a tag-based pin is schema-legal; a prior report claiming
the schema accepts only a raw `sha` was not checked against the schema and
was wrong. `sha` remains additionally used here for immutability — a tag
ref alone can be force-moved after the fact — and this gate verifies `sha`
reachability independently via PIN_SHA_UNREACHABLE). PENDING_REGISTRY
(marketplace_pins_registry.py) is the same mechanism for
REGISTRY_VERSION_STALE.

Exit codes: 0 current (or degraded, with NOTICE), 1 stale pin(s), 2 error.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Bare sibling imports: see marketplace_pins_semver.py's bootstrap comment
# for why this file inserts its own directory onto sys.path before them —
# both direct execution (`python3 scripts/check_marketplace_pins.py`) and
# the test suite's `importlib.util.spec_from_file_location` load need it.
_scripts_dir = str(Path(__file__).resolve().parent)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from marketplace_pins_github import (  # noqa: E402
    PENDING_PINS,
    check_github_pin,
    check_pin_sha,
)
from marketplace_pins_manifests import check_root_manifests  # noqa: E402
from marketplace_pins_registry import (  # noqa: E402
    check_registry_surface,
    check_registry_version,
)
from marketplace_pins_self import FROZEN_PINS, check_self_pin  # noqa: E402
from marketplace_pins_semver import (  # noqa: E402
    latest_local_tag,
    parse_semver,
    tags_between,
)

__all__ = [
    "FROZEN_PINS",
    "PENDING_PINS",
    "check_github_pin",
    "check_pin_sha",
    "check_root_manifests",
    "check_registry_surface",
    "check_registry_version",
    "check_self_pin",
    "latest_local_tag",
    "main",
    "parse_semver",
    "tags_between",
]

MARKETPLACE = (
    Path(__file__).resolve().parent.parent / ".claude-plugin" / "marketplace.json"
)


# Every `source` shape the marketplace schema defines (verified live against
# https://json.schemastore.org/claude-code-marketplace.json 2026-08-10: the
# schema's `plugins[].source` is an anyOf of exactly these five — a bare
# local-path string, plus four typed objects keyed by `source`). This gate
# has a checker for "github" (check_github_pin/check_pin_sha) and for the
# bare-string local form (check_self_pin). It does NOT verify npm/url/
# git-subdir pins — no marketplace entry uses them today (source: read
# every `plugins[].source` in .claude-plugin/marketplace.json, 2026-08-10),
# so this is not an active incident, but a dispatcher that silently returns
# (no failure, no notice) for a shape it does not recognize is exactly the
# defect class this gate exists to close. UNVERIFIED_SOURCE_TYPE below
# fails loudly instead: a real npm/url/git-subdir pin must not pass through
# an unimplemented checker as if it were current.
KNOWN_TYPED_SOURCES = frozenset({"npm", "url", "git-subdir"})


def _check_github_source_pin(name: str, pin: str, source: dict):
    """The `source.get("source") == "github"` branch of `_check_plugin_pin`,
    split out to keep the caller under the §4.2 method-size cap.
    """
    failures: list[str] = []
    notices: list[str] = []
    failure, notice = check_github_pin(name, source["repo"], pin)
    if failure:
        failures.append(failure)
    if notice:
        notices.append(notice)
    # A pin may name an exact commit as well as a version. Both are
    # delivery-gating and they fail independently: #351's sha was
    # unreachable while its version was perfectly current.
    if sha := source.get("sha"):
        failure, notice = check_pin_sha(name, source["repo"], sha)
        if failure:
            failures.append(failure)
        if notice:
            notices.append(notice)
    return failures, notices


def _check_plugin_pin(name: str, pin: str, source, root: Path):
    """One marketplace entry -> (failures, notices, primary_pin_or_None).

    `primary_pin` is non-None only for the entry whose local source is the
    repo root itself ("./") — the one whose version the root manifests
    (server.json/manifest.json) and the public registry are checked against.
    """
    failures: list[str] = []
    notices: list[str] = []
    if isinstance(source, str):
        failures.extend(check_self_pin(name, source, pin, root))
        primary = pin if source.strip("/") in ("", ".") else None
        return failures, notices, primary
    if isinstance(source, dict):
        source_type = source.get("source")
        if source_type == "github":
            gh_failures, gh_notices = _check_github_source_pin(name, pin, source)
            return failures + gh_failures, notices + gh_notices, None
        if source_type in KNOWN_TYPED_SOURCES:
            failures.append(
                f"UNVERIFIED_SOURCE_TYPE: {name}: source type {source_type!r} "
                f"is schema-legal but this gate has no checker for it — add "
                f"one (see marketplace_pins_github.py for the github-source "
                f"pattern) before relying on this pin's currency"
            )
            return failures, notices, None
        failures.append(
            f"UNRECOGNIZED_SOURCE: {name}: source {source!r} does not match "
            f"any known marketplace source shape (github/npm/url/git-subdir/"
            f"local-path)"
        )
        return failures, notices, None
    failures.append(
        f"UNRECOGNIZED_SOURCE: {name}: source {source!r} is neither a local-"
        f"path string nor a source object"
    )
    return failures, notices, None


def _report(failures: list[str], notices: list[str]) -> int:
    for line in notices:
        print(line)
    for line in failures:
        print(line)
    if failures:
        print(
            f"\n{len(failures)} stale pin(s). A release is not shipped until "
            f"its pin moves — bump .claude-plugin/marketplace.json "
            f"(and server.json / manifest.json)."
        )
        return 1
    print(
        "All marketplace pins current."
        + (" (network-degraded checks noticed above)" if notices else "")
    )
    return 0


def main() -> int:
    if not MARKETPLACE.is_file():
        print(f"ERROR: {MARKETPLACE} not found", file=sys.stderr)
        return 2
    root = MARKETPLACE.parent.parent
    data = json.loads(MARKETPLACE.read_text())
    failures: list[str] = []
    notices: list[str] = []
    primary_pin = ""
    for plugin in data.get("plugins", []):
        name, pin, source = (
            plugin.get("name", "?"),
            plugin.get("version", ""),
            plugin.get("source"),
        )
        if not pin:
            continue
        f, n, primary = _check_plugin_pin(name, pin, source, root)
        failures.extend(f)
        notices.extend(n)
        if primary:
            primary_pin = primary
    if primary_pin:
        failures.extend(check_root_manifests(root, primary_pin))
        reg_failures, reg_notices = check_registry_surface(root, primary_pin)
        failures.extend(reg_failures)
        notices.extend(reg_notices)
    return _report(failures, notices)


if __name__ == "__main__":
    sys.exit(main())
