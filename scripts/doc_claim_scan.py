"""Claim-scanning machinery for scripts/check_doc_claims.py.

source: ADR-0729"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator

ReadFn = Callable[[str], str]

# A line introducing a past release states that release's numbers.
HISTORY_MARKER = re.compile(r"\*\*v\d+\.\d+\.\d+")

# source: ADR-0729
NOT_A_CLAIM = re.compile(r"\[not-a-count-claim: ([a-z][a-z ]*)\]")


def scannable_lines(
    scanned_files: tuple[str, ...], read_fn: ReadFn
) -> Iterator[tuple[str, int, str]]:
    """Every (file, line number, text) that describes the present."""
    for relative_path in scanned_files:
        for number, line in enumerate(read_fn(relative_path).splitlines(), start=1):
            if not HISTORY_MARKER.search(line):
                yield relative_path, number, line


def exemption_registry(
    scanned_files: tuple[str, ...], read_fn: ReadFn
) -> list[tuple[str, int, str]]:
    """Every declared not-a-claim marker: (file, line, the family it exempts)."""
    return [
        (path, number, match.group(1))
        for path, number, line in scannable_lines(scanned_files, read_fn)
        for match in NOT_A_CLAIM.finditer(line)
    ]


def scan_claims(
    pattern: re.Pattern[str],
    label: str,
    scanned_files: tuple[str, ...],
    read_fn: ReadFn,
) -> list[tuple[str, int, int]]:
    """Every (file, line number, claimed value) that claims `label`.

    A line declaring ``[not-a-count-claim: <label>]`` states that its number
    counts something else; it is skipped for that family only, so the same
    line still has to answer to every other one.
    """
    return [
        (path, number, int(match.group(1)))
        for path, number, line in scannable_lines(scanned_files, read_fn)
        if label not in {m.group(1) for m in NOT_A_CLAIM.finditer(line)}
        for match in pattern.finditer(line)
    ]


def check_counts(
    pattern: re.Pattern[str],
    expected: int,
    label: str,
    scanned_files: tuple[str, ...],
    read_fn: ReadFn,
) -> list[str]:
    """Report claims that disagree — and the absence of any claim at all.

    source: ADR-0729"""
    claims = scan_claims(pattern, label, scanned_files, read_fn)
    if not claims:
        return [
            f"no {label} claim found in any scanned file — "
            f"the gate would pass vacuously"
        ]
    return [
        f"{path}:{line}: advertises {claimed} {label}, canonical is {expected}"
        for path, line, claimed in claims
        if claimed != expected
    ]
