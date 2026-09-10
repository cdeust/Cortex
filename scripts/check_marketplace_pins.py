#!/usr/bin/env python3
"""Marketplace pin-staleness gate. CANONICAL COPY: cdeust/Cortex.

Exit codes: 0 current (or degraded, with NOTICE), 1 stale pin(s), 2 error.

source: ADR-0714"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# source: ADR-0714
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
    check_server_json_schema,
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
    "check_server_json_schema",
    "check_self_pin",
    "latest_local_tag",
    "main",
    "parse_semver",
    "tags_between",
]

MARKETPLACE = (
    Path(__file__).resolve().parent.parent / ".claude-plugin" / "marketplace.json"
)


# source: ADR-0714
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
