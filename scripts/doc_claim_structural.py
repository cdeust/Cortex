"""Badge and structural-integrity checks for scripts/check_doc_claims.py.

source: ADR-0731"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

ReadFn = Callable[[str], str]

# The version and test badges are COMMITTED SVGs under assets/, not hotlinked
# shields.io URLs, so their figures are read out of the files' own <title>.
# These patterns replaced URL-shaped ones when the badges were self-hosted:
# had they been left matching "badge/version-X.Y.Z", they would have found
# nothing in the new README and both gates would have gone quiet while still
# reporting success. A gate that cannot find its subject must fail, not pass.
VERSION_BADGE = re.compile(r"<title>Version (\d+\.\d+\.\d+)</title>")
TESTS_BADGE = re.compile(r"<title>(\d+) tests passing</title>")

# Self-hosting the badges is only durable if reverting it is loud. Any
# reintroduced shields.io hotlink in the README is a third-party beacon AND
# silently detaches whichever claim it carries from the checks below.
SHIELDS_HOTLINK = re.compile(r"img\.shields\.io")

# source: ADR-0731
CONFLICT_MARKER = re.compile(r"^(?:<{7}|>{7}) \S")


def check_badge(
    relative_path: str,
    pattern: re.Pattern[str],
    expected: str,
    label: str,
    read_fn: ReadFn,
) -> list[str]:
    """One committed badge SVG states one figure, and it must be the right one.

    source: ADR-0731"""
    try:
        body = read_fn(relative_path)
    except FileNotFoundError:
        return [f"{relative_path}: missing — run scripts/generate_repo_badges.py"]
    match = pattern.search(body)
    if match is None:
        return [
            f"{relative_path}: no {label} figure in its <title>; the badge and"
            " this gate have diverged"
        ]
    if match.group(1) != expected:
        return [
            f"{relative_path}: {label} badge says {match.group(1)},"
            f" canonical is {expected}"
        ]
    return []


def check_badge_floor(
    relative_path: str,
    pattern: re.Pattern[str],
    actual: int,
    label: str,
    read_fn: ReadFn,
) -> list[str]:
    """Like check_badge, but `actual` is a floor — see check_floor_counts.

    Applies to the tests badge specifically: it is regenerated from a live
    count that varies per branch, so an exact match would reintroduce the
    same cross-branch conflict this floor family exists to remove.
    """
    try:
        body = read_fn(relative_path)
    except FileNotFoundError:
        return [f"{relative_path}: missing — run scripts/generate_repo_badges.py"]
    match = pattern.search(body)
    if match is None:
        return [
            f"{relative_path}: no {label} figure in its <title>; the badge and"
            " this gate have diverged"
        ]
    claimed = int(match.group(1))
    if claimed > actual:
        return [
            f"{relative_path}: {label} badge says {claimed}, which exceeds"
            f" the live count of {actual}"
        ]
    return []


def check_no_hotlinked_badges(read_fn: ReadFn) -> list[str]:
    """The README's repo-derived badges stay self-hosted."""
    failures = []
    for number, line in enumerate(read_fn("README.md").splitlines(), start=1):
        if SHIELDS_HOTLINK.search(line):
            failures.append(
                f"README.md:{number}: hotlinked shields.io badge — these are"
                " committed under assets/ (scripts/generate_repo_badges.py)"
            )
    return failures


def check_no_conflict_markers(
    scanned_files: tuple[str, ...], read_fn: ReadFn
) -> list[str]:
    """No scanned file states both sides of a claim at once.

    source: ADR-0731"""
    failures = []
    for relative_path in scanned_files:
        try:
            body = read_fn(relative_path)
        except FileNotFoundError:
            failures.append(f"{relative_path}: missing — the doc-claim gate reads it")
            continue
        for number, line in enumerate(body.splitlines(), start=1):
            if CONFLICT_MARKER.match(line):
                failures.append(
                    f"{relative_path}:{number}: unresolved merge conflict marker"
                    f" ({line.strip()!r}) — the file states both sides of its claims"
                )
    return failures


def check_scanned_json_parses(
    scanned_files: tuple[str, ...], read_fn: ReadFn
) -> list[str]:
    """Every scanned .json file is still machine-readable.

    source: ADR-0731"""
    failures = []
    for relative_path in scanned_files:
        if not relative_path.endswith(".json"):
            continue
        try:
            body = read_fn(relative_path)
        except FileNotFoundError:
            failures.append(f"{relative_path}: missing — the doc-claim gate reads it")
            continue
        try:
            json.loads(body)
        except json.JSONDecodeError as error:
            failures.append(f"{relative_path}: not valid JSON — {error}")
    return failures
