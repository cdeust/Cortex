"""Badge and structural-integrity checks for scripts/check_doc_claims.py.

Extracted (issue #287, Extract Function/Move Function) to keep
check_doc_claims.py under the repo's 300-line file cap. Two concerns live
here because both fail CLOSED on a file the gate cannot read or parse: badge
freshness (does a committed SVG's own figure agree with the canonical one)
and file structural integrity (unresolved merge conflicts, invalid JSON).

`read_fn`/`scanned_files` are explicit parameters — see doc_claim_scan.py's
module docstring for why (test-patch propagation through
check_doc_claims.py's thin wrappers).
"""

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

# An unresolved merge conflict inside a scanned file states BOTH sides of a
# claim at once, so every check above reads a file that no longer says one
# thing. This is not hypothetical: `.bestpractices.json` was committed with
# four such blocks (branch sec/pin-dependencies-and-fuzzing, commit c090278,
# found 2026-07-29) and shipped through the whole gate, because the claim
# regexes matched the first side and never looked at the file's structure.
#
# Matched on the labelled markers only (`<<<<<<< HEAD`, `>>>>>>> origin/main`
# — git always writes a ref after the seven characters). A bare `=======` is
# deliberately NOT matched: it is a legal setext H1 underline in Markdown, and
# half the scanned files are Markdown, so matching it would fail honest docs.
CONFLICT_MARKER = re.compile(r"^(?:<{7}|>{7}) \S")


def check_badge(
    relative_path: str,
    pattern: re.Pattern[str],
    expected: str,
    label: str,
    read_fn: ReadFn,
) -> list[str]:
    """One committed badge SVG states one figure, and it must be the right one.

    Fails closed on an unreadable or unmatched badge. The predecessor of this
    check was `if badge and ...` against a regex over the README, which passed
    silently the moment the badge stopped matching — the failure mode that
    makes a gate worse than no gate, because it still reports success.
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

    A file left with git's conflict markers is not a document that drifted —
    it is a document that says two contradictory things and parses as neither.
    The claim regexes above cannot see this: they match the first side and
    report success, which is how four such blocks reached a green CI run.
    A file the gate cannot read at all is a failure too, for the same reason
    the badge check fails closed — a check that skips its subject is worse
    than no check, because it still prints OK.
    """
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

    `.bestpractices.json` is transcribed into the OpenSSF questionnaire and
    `manifest.json` is read by the plugin loader, so a file that no longer
    parses is a broken consumer, not just a stale number. Derived from
    the caller's scanned-file set rather than a second hand-kept list, so
    adding a JSON file to the gate enrols it here with no edit to this
    function.
    """
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
