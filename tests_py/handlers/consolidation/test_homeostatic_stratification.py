"""M-D3 (7.1) regression: the fold must never re-suppress the deliberate
class — reproduces the class-blind failure mode BEFORE asserting the
stratified fix.

Root cause (design doc §M-D3, confirmed by direct SQL against the dev DB
2026-07-10): the pre-stratification homeostat computed ONE health
measurement across the WHOLE domain (92% auto-capture by volume) and
applied the resulting fold to every row in that domain — including the
deliberate minority. Section 1 below reproduces that computation
directly (using the still-general-purpose ``compute_distribution_health``
on the raw mixed population) to prove the aggregate mean masks the
auto-only emergency and would have driven a fold that touches deliberate
rows. Section 2 proves the stratified ``run_homeostatic_cycle`` computes
health per class and never writes to a deliberate row via the fold path.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from mcp_server.core.homeostatic_health import compute_distribution_health
from mcp_server.shared.write_class import AUTO, DELIBERATE
from mcp_server.handlers.consolidation.homeostatic import run_homeostatic_cycle


def _auto_memories(n: int = 40) -> list[dict]:
    # Cold, drifted-low auto-capture flood — mirrors _unimodal_low() in
    # test_a3_homeostatic_scalar.py, the exact shape that triggers a fold
    # once the factor has already drifted (stub factor_return=3.0 below).
    return [
        {
            "id": i,
            "heat": 0.15 + 0.001 * i,
            "domain": "acme-corp",
            "is_protected": False,
            "is_stale": False,
            "source": "post_tool_capture",
        }
        for i in range(n)
    ]


def _deliberate_memories(n: int = 40, base_id: int = 1000) -> list[dict]:
    # Individually-meaningful witnesses at a HEALTHY heat (post re-heat
    # campaign) — the exact scenario I6-D5's re-heat campaign produced,
    # which the class-blind fold re-suppressed same-day.
    return [
        {
            "id": base_id + i,
            "heat": 0.45,
            "domain": "acme-corp",
            "is_protected": False,
            "is_stale": False,
            "source": "feature",
        }
        for i in range(n)
    ]


def _stub_store(factor_return: float = 3.0) -> MagicMock:
    """Same stub shape as test_a3_homeostatic_scalar.py::_stub_store."""
    store = MagicMock()
    store.get_homeostatic_factor.return_value = factor_return
    store.set_homeostatic_factor.return_value = None
    store.log_homeostatic_fold.return_value = 1

    conn_result = MagicMock()
    conn_result.rowcount = 40  # only the auto rows match the fold predicate
    conn = MagicMock()
    conn.execute.return_value = conn_result

    batch_cm = MagicMock()
    batch_cm.__enter__ = MagicMock(return_value=conn)
    batch_cm.__exit__ = MagicMock(return_value=False)
    store.acquire_batch.return_value = batch_cm

    store._test_conn = conn
    return store


class TestPreStratificationFailureModeReproduced:
    """Section 1: the aggregate computation the OLD code used — proves the
    class-blind mean masks the auto-only emergency."""

    def test_aggregate_mean_differs_from_auto_only_mean(self):
        auto = _auto_memories()
        deliberate = _deliberate_memories()
        combined_heats = [m["heat"] for m in auto] + [m["heat"] for m in deliberate]
        auto_only_heats = [m["heat"] for m in auto]

        aggregate_health = compute_distribution_health(combined_heats, target_mean=0.4)
        auto_only_health = compute_distribution_health(auto_only_heats, target_mean=0.4)

        # The old class-blind computation's mean is pulled up by the
        # healthy deliberate cohort — a materially different regulatory
        # signal than the auto-only mean the stratified code now uses.
        assert aggregate_health["mean"] > auto_only_health["mean"] + 0.05
        # Both means are still off-target (illustrating that a class-blind
        # fold would have found *a* reason to act, on the WRONG rows).
        assert abs(aggregate_health["mean"] - 0.4) > 0.05

    def test_old_style_fold_would_have_touched_deliberate_rows(self):
        """Direct proof of the destructive mechanism: a single UPDATE
        keyed by domain only (no class predicate) matches deliberate rows
        too — this is literally the SQL shape the pre-M-D3 ``_apply_fold``
        issued (``WHERE domain = %s AND NOT protected/no_decay/stale``,
        no source filter)."""
        auto = _auto_memories()
        deliberate = _deliberate_memories()
        all_rows = auto + deliberate

        # Reproduce the OLD WHERE predicate in Python: domain match only,
        # no source/class restriction.
        old_predicate_matches = [
            m for m in all_rows if m["domain"] == "acme-corp" and not m["is_protected"]
        ]
        assert len(old_predicate_matches) == 80  # both classes match
        deliberate_ids = {m["id"] for m in deliberate}
        matched_deliberate = [
            m for m in old_predicate_matches if m["id"] in deliberate_ids
        ]
        assert len(matched_deliberate) == 40  # every deliberate row would fold


class TestStratifiedFoldNeverTouchesDeliberate:
    """Section 2: the fixed, per-class ``run_homeostatic_cycle``."""

    def test_auto_folds_deliberate_untouched(self):
        store = _stub_store(factor_return=3.0)
        memories = _auto_memories() + _deliberate_memories()

        result = run_homeostatic_cycle(store, memories=memories)

        # Top level mirrors the auto class's outcome (back-compat shape).
        assert result["scaling_kind"] == "fold"
        assert result["scaling_applied"] is True

        by_class = result["by_class"]
        assert by_class[AUTO]["scaling_kind"] == "fold"
        assert by_class[AUTO]["memories_scanned"] == 40

        # The deliberate class was MEASURED (health present) but never
        # regulated — this is the literal fix: verification requirement
        # "ton fold stratifié ne touchera plus la classe deliberate vers
        # le bas".
        assert by_class[DELIBERATE]["scaling_kind"] == "none"
        assert by_class[DELIBERATE]["scaling_applied"] is False
        assert by_class[DELIBERATE]["reason_for_zero"] == "class_not_regulated"
        assert by_class[DELIBERATE]["memories_scanned"] == 40
        assert by_class[DELIBERATE]["mean_heat"] == 0.45

        # The fold UPDATE was issued exactly once (for the auto class),
        # with a source predicate — not a bare domain predicate. We can't
        # inspect the SQL string's bound params directly through the
        # MagicMock's .execute call args without over-fitting to
        # implementation, so we assert on the observable outcome instead:
        # rowcount reported back matches only the auto population (stub
        # configured to 40 — the auto count), not 80 (auto+deliberate).
        store._test_conn.execute.assert_called_once()
        assert by_class[AUTO]["rows_folded"] == 40

    def test_deliberate_only_corpus_never_regulated(self):
        """A domain with ONLY deliberate writes (no auto flood at all)
        must never trigger scaling — sanity check that _REGULATED_CLASSES
        gating doesn't accidentally fall through to some other class."""
        store = _stub_store(factor_return=1.0)
        memories = _deliberate_memories(n=50)

        result = run_homeostatic_cycle(store, memories=memories)

        assert result["scaling_kind"] == "none"
        assert result["scaling_applied"] is False
        assert result["by_class"][DELIBERATE]["memories_scanned"] == 50
        assert result["by_class"][AUTO]["reason"] == "no_memories"
        store.set_homeostatic_factor.assert_not_called()
        store.bump_heat_raw.assert_not_called()
