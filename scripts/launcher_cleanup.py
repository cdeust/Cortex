"""Audit dependency directories; remove selected orphans only on owner opt-in.

Runbook: set CORTEX_CLAUDE_DIR and CLAUDE_PLUGIN_DATA to explicit absolute
paths, stop sessions using the selected plugin, then run launcher.py
--cleanup-deps --dry-run --plugin-id old@marketplace; review the JSON, then
replace --dry-run with --apply. Only deps is removed, never the identity folder.

Startup is audit-only: Claude's inline/synced plugins have no install record,
and registries cannot enumerate every project, managed setting or live session.
Source: https://code.claude.com/docs/en/plugins-reference . An explicit
--plugin-id supplies the owner-verified identity, not an inferred folder suffix.
The owner must verify absence from undiscovered settings and stopped sessions.
Missing/corrupt/incomplete known registries refuse deletion. Python 3.10 and
platforms without descriptor-bound symlink protection refuse --apply.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from launcher_cleanup_fs import (
    CleanupRefusedError,
    child_names,
    directory,
    inspect_deps,
    remove_deps,
    require_removal_support,
)
from launcher_cleanup_registry import CleanupScope, identity, protections

logger = logging.getLogger(__name__)


@dataclass
class CleanupReport:
    """Candidates are verified only within the explicit, known registry scope."""

    candidates: list[str] = field(default_factory=list)
    protected: list[str] = field(default_factory=list)
    indeterminate: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)


def _selected(plugin_ids: list[str]) -> set[str]:
    result: set[str] = set()
    for plugin_id in plugin_ids:
        name = identity(plugin_id)
        if plugin_id.endswith(("@inline", "@synced")) or name.endswith(
            ("-inline", "-synced")
        ):
            raise CleanupRefusedError(
                f"unregistered inline/synced identity cannot be verified: {plugin_id}"
            )
        result.add(name)
    return result


def _audit(scope: CleanupScope, selected: set[str], report: CleanupReport) -> None:
    protected = protections(scope)
    # Validate the current directory's ancestors even when it has no deps yet.
    with directory(scope.current_deps.parent):
        names = child_names(scope.data_root)
    for name in names:
        path = scope.data_root / name / "deps"
        if not inspect_deps(path):
            continue
        if name in protected:
            report.protected.append(str(path))
        elif name in selected:
            inspect_deps(path, recursive=True)
            report.candidates.append(str(path))
        else:
            report.indeterminate.append(str(path))
    missing = selected - {Path(path).parent.name for path in report.candidates}
    if missing:
        raise CleanupRefusedError(
            f"selected identities protected, absent or without deps: {sorted(missing)}"
        )


def _apply(scope: CleanupScope, report: CleanupReport) -> None:
    require_removal_support()
    for candidate in report.candidates:
        path = Path(candidate)
        # Re-read all registries immediately before each deletion. The owner
        # must stop sessions; no cross-process Claude registry lock is published.
        if path.parent.name in protections(scope):
            raise CleanupRefusedError(
                f"identity became protected before removal: {path.parent.name}"
            )
        remove_deps(path)
        report.removed.append(candidate)


def sweep(
    scope: CleanupScope, plugin_ids: list[str], *, apply: bool = False
) -> CleanupReport:
    """Audit first, then optionally remove only explicitly selected candidates."""
    report = CleanupReport()
    try:
        selected = _selected(plugin_ids)
        if apply and not selected:
            raise CleanupRefusedError(
                "--apply requires at least one owner-verified --plugin-id"
            )
        _audit(scope, selected, report)
        if apply:
            _apply(scope, report)
    except (OSError, ValueError) as exc:
        report.refused.append(str(exc))
        logger.warning("dependency cleanup refused: %s", exc)
    return report


def _scope_from_environment() -> CleanupScope:
    root = os.environ.get("CORTEX_CLAUDE_DIR")
    current = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not root or not current:
        raise CleanupRefusedError(
            "CORTEX_CLAUDE_DIR and CLAUDE_PLUGIN_DATA are required for cleanup"
        )
    return CleanupScope(Path(root), Path(current) / "deps")


def audit_startup() -> None:
    """Opt-in audit; an unset root does no I/O and emits no diagnostic."""
    if not os.environ.get("CORTEX_CLAUDE_DIR"):
        return
    try:
        scope = _scope_from_environment()
    except CleanupRefusedError as exc:
        logger.warning("dependency cleanup refused: %s", exc)
        return
    report = sweep(scope, [])
    if report.indeterminate:
        logger.warning(
            "dependency cleanup audit retained unverified dirs: %s",
            report.indeterminate,
        )


def cli(arguments: list[str]) -> int:
    """Handle cleanup before dependency installation or backend imports."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cleanup-deps", action="store_true", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="list only (the default)")
    mode.add_argument(
        "--apply", action="store_true", help="owner confirms selected plugins unused"
    )
    parser.add_argument("--plugin-id", action="append", default=[])
    options = parser.parse_args(arguments)
    try:
        scope = _scope_from_environment()
    except CleanupRefusedError as exc:
        logger.warning("dependency cleanup refused: %s", exc)
        print(json.dumps(asdict(CleanupReport(refused=[str(exc)]))))
        return 1
    report = sweep(scope, options.plugin_id, apply=options.apply)
    print(json.dumps(asdict(report), indent=2))
    return int(bool(report.refused))
