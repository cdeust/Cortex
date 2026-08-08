"""Retrieval must not reward an untrusted memory with heat (issue #368).

Heat rises on access and is a ranking signal, so without this the demotion
factor is only a delay: a hostile memory that keeps being retrieved keeps
gaining heat, and eventually outranks the trusted one again despite being
multiplied down. The factor and this loop-break are two halves of one
defence — the corpus's `heat_farming` scenario exists for exactly this.

Tested at the pipeline level with a recording store stub rather than against
a live database: the property is "which store writes happen", and a stub
makes the absence of a write observable, where a database only shows the
end state.
"""

from __future__ import annotations

import pytest

from mcp_server.core.capture_origin import (
    ORIGIN_DELIBERATE,
    ORIGIN_LEGACY,
    ORIGIN_NETWORK,
    ORIGIN_UNKNOWN,
)
from mcp_server.core.recall_pipeline import reconsolidation_apply


class RecordingStore:
    """Captures heat writes instead of performing them."""

    def __init__(self) -> None:
        self.heat_writes: list[tuple[int, float]] = []
        self.access_updates: list[int] = []

    def bump_heat_raw(self, memory_id: int, new_heat_base: float) -> None:
        self.heat_writes.append((memory_id, new_heat_base))

    def update_memory_access(self, memory_id: int) -> None:
        self.access_updates.append(memory_id)


def _candidate(origin: str, memory_id: int = 1) -> dict:
    """A candidate shaped like a recall row, worded to earn a heat bump.

    The content deliberately overlaps the query used below: reconsolidation
    grants a positive delta on contextual match, which is the reward path
    under test. A candidate that earned no bump would make every assertion
    here vacuously true.
    """
    return {
        "memory_id": memory_id,
        "content": "deployment rollback procedure for the staging cluster",
        "heat": 0.5,
        "capture_origin": origin,
        "tags": [],
        "created_at": "2026-01-01T00:00:00+00:00",
        "emotional_valence": 0.0,
    }


_QUERY = "deployment rollback procedure staging cluster"


def _heat_written(origin: str) -> bool:
    store = RecordingStore()
    reconsolidation_apply([_candidate(origin)], _QUERY, store)
    return bool(store.heat_writes)


class TestHeatRewardFollowsTrust:
    @pytest.mark.parametrize("origin", [ORIGIN_DELIBERATE, ORIGIN_LEGACY])
    def test_trusted_origin_still_earns_heat(self, origin: str):
        """The loop-break must not disable heat for everyone.

        Asserted first: if trusted memories stopped earning heat too, the
        untrusted assertions below would pass for the wrong reason and the
        whole thermodynamic model would be silently disabled.
        """
        assert _heat_written(origin) is True

    @pytest.mark.parametrize("origin", [ORIGIN_NETWORK, ORIGIN_UNKNOWN])
    def test_untrusted_origin_earns_no_heat(self, origin: str):
        assert _heat_written(origin) is False

    def test_missing_origin_earns_no_heat(self):
        """Fail-closed on a candidate that carries no origin at all.

        A row from a store that does not return the column must not be
        treated as trusted — that would be a free bypass for any backend or
        code path that forgets to select it.
        """
        store = RecordingStore()
        candidate = _candidate(ORIGIN_DELIBERATE)
        del candidate["capture_origin"]
        reconsolidation_apply([candidate], _QUERY, store)
        assert store.heat_writes == []

    def test_access_tracking_is_untouched_for_untrusted(self):
        """Only the heat reward is withheld, not the access bookkeeping.

        access_count is not an amplifier — confidence is
        useful_count/access_count, so an unrated retrieval lowers it. Cutting
        it would change unrelated behaviour and hide retrievals from
        diagnostics.
        """
        store = RecordingStore()
        reconsolidation_apply([_candidate(ORIGIN_NETWORK)], _QUERY, store)
        assert store.heat_writes == []
        assert store.access_updates == [1]
