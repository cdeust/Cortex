"""Decide, per domain, whether a rescan may replace the stored profile.

A stored domain profile accumulates: ``record_session_end`` adds one session
to ``sessionCount`` and folds it into the cognitive-style EMA, and no
transcript can rebuild that state once Claude Code has deleted the transcript
(default retention). A rescan therefore sees a sliding window. Replacing a
profile built from N recorded sessions with one built from M < N transcripts
destroys evidence, so a rescan that sees fewer sessions keeps the stored
profile unless the caller explicitly asks to replace it.

source: measured 2026-10-10 on the owner's machine, a forced rebuild turned
the cortex domain from 32 recorded sessions into 8 (April backup of the same
key). The accumulation it protects is ADR-0434's record_session_end; the rule
itself is a new decision, pending registration as a wiki ADR.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Action = Literal["created", "rebuilt", "kept", "replaced"]


@dataclass(frozen=True)
class DomainOutcome:
    """What a rescan did to one domain the scan saw conversations for."""

    domain: str
    action: Action
    stored_sessions: int
    scanned_sessions: int
    resulting_sessions: int

    def to_dict(self) -> dict:
        return {
            "domain": self.domain,
            "action": self.action,
            "storedSessions": self.stored_sessions,
            "scannedSessions": self.scanned_sessions,
            "resultingSessions": self.resulting_sessions,
        }


def stored_session_count(domain_id: str, stored: dict | None) -> int:
    """Sessions the stored profile records.

    Precondition: ``stored`` is the persisted profile of ``domain_id`` or None.
    Postcondition: returns a non-negative int; 0 when there is no profile or it
    records no count. Raises ValueError when ``sessionCount`` is present but is
    not an int: a count that cannot be compared must stop the rebuild, not be
    read as 0 (which would let the scan overwrite the profile).
    """
    if not stored:
        return 0
    count = stored.get("sessionCount")
    if count is None:
        return 0
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError(
            f"stored profile {domain_id!r} has sessionCount={count!r}; "
            "expected a non-negative integer"
        )
    return count


def decide_domain_outcome(
    domain_id: str,
    stored: dict | None,
    scanned_sessions: int,
    replace_accumulated: bool,
) -> DomainOutcome:
    """Pick the action for one domain the scan saw ``scanned_sessions`` for.

    Precondition: ``scanned_sessions`` >= 1.
    Postcondition: ``kept`` iff the scan saw fewer sessions than the stored
    profile records and ``replace_accumulated`` is False; the resulting count
    is then the stored count. Otherwise the profile is built from the scan and
    the resulting count is ``scanned_sessions`` (``created`` when nothing was
    stored, ``replaced`` when the scan saw fewer and the caller asked for it,
    ``rebuilt`` when the scan saw at least as many).
    """
    stored_sessions = stored_session_count(domain_id, stored)
    if not stored:
        action: Action = "created"
    elif scanned_sessions >= stored_sessions:
        action = "rebuilt"
    elif replace_accumulated:
        action = "replaced"
    else:
        action = "kept"
    resulting = stored_sessions if action == "kept" else scanned_sessions
    return DomainOutcome(
        domain=domain_id,
        action=action,
        stored_sessions=stored_sessions,
        scanned_sessions=scanned_sessions,
        resulting_sessions=resulting,
    )


@dataclass(frozen=True)
class ProfileBuild:
    """The assembled profile set plus what the rescan did to each scanned domain."""

    profiles: dict
    outcomes: list[DomainOutcome]
