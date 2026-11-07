"""ADR-0316 lifecycle acceptance: aging, archive revival and sweep reporting."""

from datetime import datetime, timedelta, timezone
import pytest
from mcp_server.core.wiki_thermodynamics import decay_heat, evaluate_page, summarise

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("state", "heat", "idle_days", "expected", "transitioned"),
    [
        ("active", 0.4, 30, "area", True),
        ("active", 0.3, 14, "active", False),
        ("area", 0.15, 90, "area", False),
        ("area", 0.15, 91, "archived", True),
        ("archived", 0.4, 365, "active", True),
        ("archived", 0.3, 365, "archived", False),
        ("evergreen", 0.1, 365, "evergreen", False),
        ("imported", 0.7, 1, "imported", False),
    ],
)
def test_lifecycle_changes_only_when_heat_and_idle_policy_allow(
    state, heat, idle_days, expected, transitioned
):
    page = {
        "id": 7,
        "heat": heat,
        "lifecycle_state": state,
        "tended": NOW - timedelta(days=idle_days),
    }
    decision = evaluate_page(page, now=NOW)
    assert (decision.new_lifecycle, decision.transitioned) == (expected, transitioned)
    assert decision.archived_at == (
        NOW if expected == "archived" and transitioned else None
    )
    assert decision.page_id == 7 and decision.rationale
    assert page["lifecycle_state"] == state


def test_half_life_and_timezone_normalization_agree_without_future_decay():
    naive = (NOW - timedelta(days=30)).replace(tzinfo=None)
    shifted = (NOW - timedelta(days=30)).astimezone(timezone(timedelta(hours=2)))
    for tended in (naive, shifted):
        assert decay_heat(
            current_heat=0.8, last_tended=tended, lifecycle_state="active", now=NOW
        ) == pytest.approx(0.4)
    assert (
        decay_heat(
            current_heat=0.8,
            last_tended=NOW + timedelta(days=1),
            lifecycle_state="active",
            now=NOW,
        )
        == 0.8
    )


def test_sweep_reports_decays_transitions_floor_and_empty_input():
    pages = [
        {"id": 1, "heat": 0.4, "tended": NOW - timedelta(days=30)},
        {"id": 2, "heat": 0.0},
        {"id": 3, "heat": 0.8, "lifecycle_state": "evergreen"},
    ]
    stats = summarise(
        [evaluate_page(page, now=NOW) for page in pages], {1: 0.4, 2: 0.0, 3: 0.8}
    )
    assert (stats.pages_evaluated, stats.pages_decayed, stats.heat_floor_count) == (
        3,
        1,
        1,
    )
    assert stats.transitions == {"->area": 1}
    assert stats.avg_heat_before == pytest.approx(0.4)
    assert stats.avg_heat_after == pytest.approx(1 / 3)
    empty = summarise([], {})
    assert empty.pages_evaluated == 0 and empty.transitions == {}
    assert empty.avg_heat_before == empty.avg_heat_after == 0
