"""Tests for benchmarks/outcome/paired_delta.py (issue #343, slice 1).

Expected values are computed by hand from the fixture trials, never read
back from the implementation."""

from __future__ import annotations

import pytest

from benchmarks.outcome.paired_delta import (
    ARM_NO_RECALL,
    ARM_RECALL,
    TrialOutcome,
    pair_trials,
    summarize,
)


def _trial(task, arm, rep, correct, turns, tokens):
    return TrialOutcome(task, arm, rep, correct, turns, tokens)


def _two_tasks_two_repeats():
    # Per-pair deltas (recall - no_recall):
    #   correct: t1/r0 +1, t1/r1 0, t2/r0 0, t2/r1 +1  -> mean 0.5
    #   turns:   t1/r0 -4, t1/r1 -2, t2/r0 0, t2/r1 -2 -> mean -2
    return [
        _trial("t1", ARM_RECALL, 0, True, 2, 100),
        _trial("t1", ARM_NO_RECALL, 0, False, 6, 300),
        _trial("t1", ARM_RECALL, 1, True, 3, 150),
        _trial("t1", ARM_NO_RECALL, 1, True, 5, 250),
        _trial("t2", ARM_RECALL, 0, False, 4, 200),
        _trial("t2", ARM_NO_RECALL, 0, False, 4, 200),
        _trial("t2", ARM_RECALL, 1, True, 1, 50),
        _trial("t2", ARM_NO_RECALL, 1, False, 3, 150),
    ]


def _by_metric(report):
    return {d.metric: d for d in report.deltas}


def test_mean_delta_and_repeat_std_match_hand_computation():
    report = summarize(_two_tasks_two_repeats(), n_resamples=1000, seed=7)
    deltas = _by_metric(report)
    assert (report.n_tasks, report.n_repeats, report.is_anecdote) == (2, 2, False)
    assert deltas["correct"].mean_delta == pytest.approx(0.5)
    assert deltas["turns"].mean_delta == pytest.approx(-2.0)
    assert deltas["tokens"].mean_delta == pytest.approx(-100.0)
    # Per-repeat mean turn deltas: r0 = (-4 + 0)/2 = -2, r1 = (-2 - 2)/2 = -2.
    assert deltas["turns"].repeat_std == pytest.approx(0.0)
    # Per-repeat mean correct deltas: r0 = 0.5, r1 = 0.5.
    assert deltas["correct"].repeat_std == pytest.approx(0.0)


def test_ci_is_the_percentile_interval_and_is_seed_reproducible():
    trials = _two_tasks_two_repeats()
    first = _by_metric(summarize(trials, n_resamples=1000, seed=7))["turns"]
    again = _by_metric(summarize(trials, n_resamples=1000, seed=7))["turns"]
    # Task mean turn deltas: t1 = -3, t2 = -1. A two-task resample mean is
    # -3, -2 or -1 with probability 1/4, 1/2, 1/4, so with 1000 resamples the
    # 2.5th percentile is -3 and the 97.5th is -1.
    assert first.ci95 == (-3.0, -1.0)
    assert first.ci95 == again.ci95


def test_single_repeat_is_flagged_as_anecdote_without_variance():
    trials = [t for t in _two_tasks_two_repeats() if t.repeat == 0]
    report = summarize(trials, n_resamples=1000, seed=7)
    assert report.is_anecdote is True
    assert all(d.repeat_std is None for d in report.deltas)


def test_single_task_has_no_bootstrap_interval():
    trials = [t for t in _two_tasks_two_repeats() if t.task_id == "t1"]
    report = summarize(trials, n_resamples=1000, seed=7)
    assert all(d.ci95 is None for d in report.deltas)


def test_negative_delta_is_reported_unclipped():
    trials = [
        _trial("t1", ARM_RECALL, 0, False, 9, 900),
        _trial("t1", ARM_NO_RECALL, 0, True, 1, 100),
    ]
    deltas = _by_metric(summarize(trials, n_resamples=1000, seed=7))
    assert deltas["correct"].mean_delta == pytest.approx(-1.0)
    assert deltas["turns"].mean_delta == pytest.approx(8.0)


@pytest.mark.parametrize(
    ("trials", "message"),
    [
        ([_trial("t1", ARM_RECALL, 0, True, 1, 1)], "no no_recall trial"),
        (
            [
                _trial("t1", ARM_RECALL, 0, True, 1, 1),
                _trial("t1", ARM_RECALL, 0, True, 1, 1),
            ],
            "duplicate trial",
        ),
        ([_trial("t1", "cortex", 0, True, 1, 1)], "unknown arm"),
        ([], "no trials"),
    ],
)
def test_unpairable_input_raises(trials, message):
    with pytest.raises(ValueError, match=message):
        pair_trials(trials)


def test_tasks_with_different_repeats_raise():
    trials = _two_tasks_two_repeats()
    trials = [t for t in trials if not (t.task_id == "t2" and t.repeat == 1)]
    with pytest.raises(ValueError, match="different repeats"):
        pair_trials(trials)


def test_non_positive_resample_count_raises():
    with pytest.raises(ValueError, match="n_resamples"):
        summarize(_two_tasks_two_repeats(), n_resamples=0, seed=7)
