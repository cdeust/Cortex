"""Claim-scanning machinery for scripts/check_doc_claims.py.

Extracted (issue #287, Extract Function/Move Function) to keep
check_doc_claims.py under the repo's 300-line file cap. Answers "does a
scanned file's prose claim (a count, phrased as 'N things') agree with a
canonical number" and "which lines have declared they are not a claim."

`scanned_files`/`read_fn` are explicit parameters rather than module
globals, so check_doc_claims.py's thin wrappers (which do reference its own
`SCANNED_FILES`/`read` bare names, and so DO see `gate.read = fake` /
`gate.SCANNED_FILES = (...)` patches in tests_py/scripts/test_check_doc_claims.py)
can forward them through unchanged.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator

ReadFn = Callable[[str], str]

# A line introducing a past release states that release's numbers.
HISTORY_MARKER = re.compile(r"\*\*v\d+\.\d+\.\d+")

# A line whose number counts something else declares which family it is not a
# claim for. Rewording the prose to dodge a pattern would hide a true, measured
# number to keep the gate quiet; declaring it keeps the number and puts the
# exemption on the record, at the one site that knows why it is not a claim.
# The label must match a claim family exactly — an unrecognised or misspelled
# label exempts nothing, so the marker fails closed.
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

    A pattern that matches nothing would pass silently forever, which is how a
    gate becomes decorative: the vacuity guard makes a reworded (or deleted)
    claim a build failure rather than an unnoticed loss of coverage.
    """
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


def check_floor_counts(
    pattern: re.Pattern[str],
    actual: int,
    label: str,
    scanned_files: tuple[str, ...],
    read_fn: ReadFn,
) -> list[str]:
    """Like check_counts, but `actual` is a floor, not an exact fact.

    The test count is the one claim family no single PR branch can state
    exactly: it is a property of the post-merge tree, and two branches that
    each add tests compute two different, both-true, live counts (issue
    #287 — the six-file conflict class, and the same race made main's own
    gate flap red twice: PR #280 synced to its own total, #278 then added
    more tests, and the committed figure was a true-when-written but now
    stale UNDER-claim). A claim that understates the true count is not
    false, so only an OVER-claim (someone hand-typed a number no measurement
    backs, or tests were removed below what is claimed) is reported.
    """
    claims = scan_claims(pattern, label, scanned_files, read_fn)
    if not claims:
        return [
            f"no {label} claim found in any scanned file — "
            f"the gate would pass vacuously"
        ]
    return [
        f"{path}:{line}: advertises {claimed} {label}, which exceeds the"
        f" live count of {actual}"
        for path, line, claimed in claims
        if claimed > actual
    ]
