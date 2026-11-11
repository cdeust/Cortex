"""What a tree does not carry as a backup manifest says (issue #731, slice 4).

A restore compares two manifests of the same backend table: the one the backup
was written with, and the one scanned from a tree (the backup itself before
anything is written, then the restored copy). ``manifest_differences`` names
every resource and file on which they disagree, so a refusal says what is
missing, what is extra and what changed; an empty list means the tree carries
exactly the manifest's files, with its digests and sizes.

``created_at`` is not compared: it dates the scan, not the data.

Pure: the scan is ``infrastructure/backup_scan.py``.

source: issue #731; docs/audits/owned-resources-backup-2026-11-05.md §5
"""

from __future__ import annotations

from typing import Any, Mapping

_ABSENT = "absent"
_EXTRA = "not in the manifest"


def _entry_differences(want: Mapping[str, Any], got: Mapping[str, Any]) -> list[str]:
    """One resource: its presence first, then file by file in path order."""
    if want["present"] != got["present"]:
        return [f"{want['path']}: {_ABSENT if want['present'] else _EXTRA}"]
    wanted = {file["path"]: file for file in want["files"]}
    found = {file["path"]: file for file in got["files"]}
    lines = []
    for path in sorted(wanted.keys() | found.keys()):
        if path not in found:
            lines.append(f"{path}: {_ABSENT}")
        elif path not in wanted:
            lines.append(f"{path}: {_EXTRA}")
        elif found[path] != wanted[path]:
            lines.append(f"{path}: content differs from the manifest")
    return lines


def manifest_differences(
    expected: Mapping[str, Any], actual: Mapping[str, Any]
) -> list[str]:
    """The disagreements of ``actual`` (a tree's scan) with ``expected``.

    Both are manifests of one backend, so their entries are the same table in
    the same order (``parse_manifest`` and ``build_manifest`` guarantee it);
    two tables of different lengths are a ``ValueError``.
    """
    lines: list[str] = []
    for want, got in zip(expected["entries"], actual["entries"], strict=True):
        lines.extend(_entry_differences(want, got))
    return lines
