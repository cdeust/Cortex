"""Reclassify legacy global rows; dry-run unless --apply. source: ADR-1083"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp_server.core.global_detector import detect_global
from mcp_server.core.thermodynamics import is_decision_content
from mcp_server.hooks.wiring import wire_composition_root  # noqa: E402 — source: issue #560
from scripts.reclassify_team_scope_db import ScopeDatabase, verify_backup

wire_composition_root()


@dataclass(frozen=True)
class ScopeRow:
    id: int
    content: str
    tags: list[str]
    domain: str
    directory_context: str
    agent_context: str
    is_global: bool
    is_team_decision: bool


@dataclass(frozen=True)
class ScopeChange:
    id: int
    directory_context: str
    is_global: bool
    is_team_decision: bool
    reason: str


@dataclass(frozen=True)
class ScopeMappings:
    domains: dict[str, str]
    memories: dict[str, str]
    keep_global_ids: frozenset[int]
    clear_global_ids: frozenset[int] = frozenset()


def load_mappings(path: Path | None) -> ScopeMappings:
    data = json.loads(path.read_text()) if path else {}
    if not isinstance(data, dict) or set(data) - {
        "domains",
        "memories",
        "keep_global_ids",
        "clear_global_ids",
    }:
        raise ValueError(
            "mappings accept domains, memories, keep_global_ids, clear_global_ids"
        )
    domains, memories = data.get("domains", {}), data.get("memories", {})
    for mapping in (domains, memories):
        if not isinstance(mapping, dict):
            raise ValueError("project mappings must be objects")
        for key, directory in mapping.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("empty mapping key")
            if not isinstance(directory, str):
                raise ValueError("project directory must be a string")
            project = Path(directory)
            if not project.is_absolute() or not project.is_dir():
                raise ValueError(f"project directory must exist: {directory}")
            if str(project.resolve()) != directory:
                raise ValueError(f"project directory must be canonical: {directory}")
    if any(not key.isdecimal() for key in memories):
        raise ValueError("memory mapping keys must be decimal IDs")
    id_lists = []
    for key in ("keep_global_ids", "clear_global_ids"):
        ids = data.get(key, [])
        if not isinstance(ids, list) or any(type(item) is not int for item in ids):
            raise ValueError(f"{key} must be a list of integers")
        id_lists.append(frozenset(ids))
    if id_lists[0] & id_lists[1]:
        raise ValueError("an id cannot be both kept and cleared")
    return ScopeMappings(domains, memories, id_lists[0], id_lists[1])


def classify(row: ScopeRow, mappings: ScopeMappings) -> ScopeChange:
    directory = row.directory_context
    reason = "recorded_project"
    if not directory:
        directory = mappings.memories.get(str(row.id), "")
        reason = "owner_memory_mapping"
        if not directory:
            directory = mappings.domains.get(row.domain, "")
            reason = "verified_domain_mapping"
    if not directory:
        return ScopeChange(
            row.id, "", row.is_global, row.is_team_decision, "unresolved_project"
        )
    detected, _, _ = detect_global(row.content, row.tags)
    # Only the ADR-0200 promotion is undone: a decision written under an agent
    # context. Any other global row was made global by an explicit act this
    # script cannot see, so it stays global. source: ADR-1083
    promoted = bool(row.agent_context) and is_decision_content(row.content)
    kept = row.id in mappings.keep_global_ids or detected
    cleared = row.id in mappings.clear_global_ids  # the owner's explicit call
    global_scope = kept or (row.is_global and not promoted and not cleared)
    team = row.is_team_decision or promoted
    if global_scope and not kept:
        reason = "global_origin_not_the_defect"
    return ScopeChange(row.id, directory, global_scope, team, reason)


def changes_scope(row: ScopeRow, change: ScopeChange) -> bool:
    return (
        row.directory_context != change.directory_context
        or row.is_global != change.is_global
        or row.is_team_decision != change.is_team_decision
    )


def make_report(rows: list[ScopeRow], mappings: ScopeMappings) -> dict:
    changes = [classify(row, mappings) for row in rows]
    updates = [
        change
        for row, change in zip(rows, changes, strict=True)
        if changes_scope(row, change)
    ]
    return {
        "candidate_count": len(rows),
        "change_count": len(updates),
        "clear_global_count": sum(not change.is_global for change in updates),
        "unresolved_ids": [
            change.id for change in changes if change.reason == "unresolved_project"
        ],
        "retained_global_ids": [change.id for change in changes if change.is_global],
        "unexplained_global_ids": [
            change.id
            for change in changes
            if change.reason == "global_origin_not_the_defect"
        ],
        "changes": [asdict(change) for change in updates],
    }


def run(args: argparse.Namespace) -> dict:
    mappings = load_mappings(args.mappings)
    if args.apply and args.database_url:
        verify_backup(args.backup)
    with ScopeDatabase(args.database_url, args.sqlite_path) as database:
        raw_rows = database.fetch_rows(require_marker=args.apply)
        rows = [ScopeRow(**row) for row in raw_rows]
        report = make_report(rows, mappings)
        if args.apply:
            database.apply_changes(report["changes"])
        report["applied"] = args.apply
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--database-url", help="Explicit PostgreSQL DSN; no env default"
    )
    target.add_argument("--sqlite-path", type=Path)
    parser.add_argument(
        "--mappings", type=Path, help="Verified project/owner mappings JSON"
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--backup", type=Path, help="Verified pg_dump -Fc archive for apply"
    )
    args = parser.parse_args()
    print(json.dumps(run(args), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
