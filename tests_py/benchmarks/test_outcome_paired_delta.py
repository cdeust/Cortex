"""Tests for benchmarks/outcome/paired_delta.py (issue #343, slice 1).

Expected values are computed by hand from the fixture trials, never read
back from the implementation."""

from __future__ import annotations

import math
import random

import pytest

from benchmarks.outcome.paired_delta import (
    ARM_NO_RECALL,
    ARM_RECALL,
    TrialOutcome,
    _bootstrap_ci,
    _percentile_ranks,
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


def _ten_tasks(n_tasks=10):
    # Task i: turn delta -i, token delta -100*i, one repeat.
    trials = []
    for i in range(n_tasks):
        trials.append(_trial(f"t{i}", ARM_RECALL, 0, True, 10, 1000))
        trials.append(_trial(f"t{i}", ARM_NO_RECALL, 0, True, 10 + i, 1000 + 100 * i))
    return trials


def _ten_tasks_two_repeats():
    # Task i: turn deltas -i-1 (repeat 0) and -i+1 (repeat 1), so each task
    # mean is -i, the same task means as _ten_tasks().
    trials = []
    for i in range(10):
        for rep, baseline_turns in ((0, 11 + i), (1, 9 + i)):
            trials.append(_trial(f"t{i}", ARM_RECALL, rep, True, 10, 1000))
            trials.append(
                _trial(f"t{i}", ARM_NO_RECALL, rep, True, baseline_turns, 1000)
            )
    return trials


def _by_metric(report):
    return {d.metric: d for d in report.deltas}


def test_mean_delta_matches_hand_computation():
    report = summarize(_two_tasks_two_repeats(), n_resamples=1000, seed=7)
    deltas = _by_metric(report)
    assert (report.n_tasks, report.n_repeats, report.is_anecdote) == (2, 2, False)
    assert deltas["correct"].mean_delta == pytest.approx(0.5)
    assert deltas["turns"].mean_delta == pytest.approx(-2.0)
    assert deltas["tokens"].mean_delta == pytest.approx(-100.0)
    # Per-sweep mean deltas are equal for every metric (turns: r0 = (-4+0)/2,
    # r1 = (-2-2)/2; correct: 0.5 and 0.5; tokens: -100 and -100), so the
    # spread is 0. Flat over pairs it would not be; grouped by task, turns
    # and tokens would not be.
    assert [d.repeat_std for d in report.deltas] == [0.0, 0.0, 0.0]


def test_repeat_std_is_the_sample_std_of_sweep_means():
    # One task, three sweeps with turn deltas -4, -2, 0: sample std is 2
    # (population std would be sqrt(8/3)).
    trials = []
    for rep, baseline_turns in enumerate((6, 4, 2)):
        trials.append(_trial("t1", ARM_RECALL, rep, True, 2, 10))
        trials.append(_trial("t1", ARM_NO_RECALL, rep, True, baseline_turns, 10))
    report = summarize(trials, n_resamples=1000, seed=7)
    assert (report.n_tasks, report.n_repeats) == (1, 3)
    assert _by_metric(report)["turns"].repeat_std == pytest.approx(2.0)
    assert _by_metric(report)["tokens"].repeat_std == pytest.approx(0.0)


def test_below_ten_tasks_reports_no_interval():
    report = summarize(_two_tasks_two_repeats(), n_resamples=1000, seed=7)
    assert all(d.ci95 is None for d in report.deltas)
    nine = summarize(_ten_tasks(n_tasks=9), n_resamples=1000, seed=7)
    assert all(d.ci95 is None for d in nine.deltas)
    ten = summarize(_ten_tasks(), n_resamples=1000, seed=7)
    assert all(d.ci95 is not None for d in ten.deltas)


def test_interval_resamples_task_means_not_pairs():
    # Same task means, two repeats each: resampling tasks gives the same
    # interval as the one-repeat run; resampling the 20 pairs would not.
    one = _by_metric(summarize(_ten_tasks(), n_resamples=1000, seed=7))["turns"]
    two = _by_metric(summarize(_ten_tasks_two_repeats(), n_resamples=1000, seed=7))
    assert two["turns"].ci95 == one.ci95


def test_interval_lies_strictly_inside_the_task_mean_range():
    turns = _by_metric(summarize(_ten_tasks(), n_resamples=1000, seed=7))["turns"]
    low, high = turns.ci95
    # Task means span [-9, 0]; their mean is -4.5. Percentile bounds of
    # 1000 ten-task resamples are almost never the extremes: reaching -9 or
    # 0 needs that one task drawn ten times (probability 0.1**10 per draw).
    assert -9.0 < low < -4.5 < high < 0.0


def test_interval_bounds_are_the_2_5_and_97_5_percentiles():
    # Nine tasks with delta 0, the last one with delta -10: a resample mean is -k,
    # k ~ Binomial(10, 0.1). P(k >= 3) = 0.070 and P(k >= 4) = 0.013, so the
    # 2.5th percentile is -3; P(k = 0) = 0.349, so the 97.5th is 0. The most
    # extreme of 1000 resamples is k >= 4 (expected count 12.8), so returning
    # the resample min/max instead of the percentiles fails this test. The
    # seed is fixed. Empirical sweep, not a hand-worked value: all of seeds
    # 0-199 gave (-3, 0). The outlier is the last task, so a resampler that
    # never draws it gives (0, 0) and fails.
    trials = []
    for i in range(10):
        trials.append(_trial(f"t{i}", ARM_RECALL, 0, True, 0, 0))
        trials.append(_trial(f"t{i}", ARM_NO_RECALL, 0, True, 10 if i == 9 else 0, 0))
    turns = _by_metric(summarize(trials, n_resamples=1000, seed=7))["turns"]
    assert turns.ci95 == (-3.0, 0.0)


def test_metrics_share_the_same_task_resamples():
    # Token deltas are exactly 100x turn deltas per task, so with shared
    # resamples the token interval is exactly 100x the turn interval.
    deltas = _by_metric(summarize(_ten_tasks(), n_resamples=1000, seed=7))
    t_low, t_high = deltas["turns"].ci95
    assert deltas["tokens"].ci95 == (
        pytest.approx(100 * t_low),
        pytest.approx(100 * t_high),
    )


def test_seed_controls_the_interval_and_input_order_does_not():
    trials = _ten_tasks()
    first = summarize(trials, n_resamples=40, seed=1)
    shuffled = list(trials)
    random.Random(3).shuffle(shuffled)
    assert summarize(shuffled, n_resamples=40, seed=1) == first
    intervals = {
        _by_metric(summarize(trials, n_resamples=40, seed=s))["turns"].ci95
        for s in range(5)
    }
    assert len(intervals) > 1


def test_bootstrap_ci_takes_ranks_1_and_38_of_40_resamples():
    # Seed-free: 40 single-task resamples whose means are 0..39, unsorted.
    # Ranks (1, 38) of the sorted means are 1.0 and 38.0.
    task_means = [float(v) for v in range(40)]
    resamples = [[v] for v in random.Random(0).sample(range(40), 40)]
    assert _bootstrap_ci(task_means, resamples) == (1.0, 38.0)


def test_percentile_ranks_are_symmetric():
    # 25 resamples below rank 25 and 25 above rank 974.
    assert _percentile_ranks(1000) == (25, 974)
    assert _percentile_ranks(40) == (1, 38)


def test_too_few_resamples_for_both_bounds_raises():
    with pytest.raises(ValueError, match="n_resamples=39"):
        summarize(_two_tasks_two_repeats(), n_resamples=39, seed=7)


@pytest.mark.parametrize("n_resamples", [1000.0, True, "1000"])
def test_non_int_resample_count_raises(n_resamples):
    with pytest.raises(ValueError, match="n_resamples must be"):
        summarize(_ten_tasks(), n_resamples=n_resamples, seed=7)


def test_single_repeat_is_flagged_as_anecdote_without_variance():
    trials = [t for t in _two_tasks_two_repeats() if t.repeat == 0]
    report = summarize(trials, n_resamples=1000, seed=7)
    assert report.is_anecdote is True
    assert all(d.repeat_std is None for d in report.deltas)


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
        ([("t1", ARM_RECALL, 0, True, 1, 1)], "no no_recall trial"),
        ([("t1", ARM_NO_RECALL, 0, True, 1, 1)], "no recall trial"),
        ([("t1", ARM_RECALL, 0, True, 1, 1)] * 2, "duplicate trial"),
        ([], "no trials"),
    ],
)
def test_unpairable_input_raises(trials, message):
    with pytest.raises(ValueError, match=message):
        pair_trials([_trial(*fields) for fields in trials])


def test_tasks_with_different_repeats_raise():
    trials = _two_tasks_two_repeats()
    trials = [t for t in trials if not (t.task_id == "t2" and t.repeat == 1)]
    with pytest.raises(ValueError, match="different repeats"):
        pair_trials(trials)


def test_tasks_with_equal_counts_but_different_repeat_labels_raise():
    # t1 ran sweeps {0, 1}, t2 ran {0, 2}: same count, different sweeps.
    trials = [
        TrialOutcome(
            t.task_id,
            t.arm,
            2 if t.task_id == "t2" and t.repeat == 1 else t.repeat,
            t.correct,
            t.turns,
            t.tokens,
        )
        for t in _two_tasks_two_repeats()
    ]
    with pytest.raises(ValueError, match="different repeats"):
        pair_trials(trials)


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        (("t1", "cortex", 0, True, 1, 1), "unknown arm"),
        (("", ARM_RECALL, 0, True, 1, 1), "task_id"),
        ((5, ARM_RECALL, 0, True, 1, 1), "task_id"),
        (("t1", ARM_RECALL, True, True, 1, 1), "repeat"),
        (("t1", ARM_RECALL, "0", True, 1, 1), "repeat"),
        (("t1", ARM_RECALL, 0, 1, 1, 1), "correct"),
        (("t1", ARM_RECALL, 0, True, -1, 1), "turns"),
        (("t1", ARM_RECALL, 0, True, 1, math.inf), "tokens"),
    ],
)
def test_malformed_trial_raises(fields, message):
    with pytest.raises(ValueError, match=message):
        _trial(*fields)


@pytest.mark.parametrize("name", ["task_id", "repeat", "arm"])
def test_metric_rejects_a_non_metric_field(name):
    with pytest.raises(ValueError, match="unknown metric"):
        _trial("t1", ARM_RECALL, 0, True, 1, 1).metric(name)


@pytest.mark.parametrize("seed", [None, True, "7", 7.0])
def test_non_int_seed_raises_even_below_the_interval_minimum(seed):
    # Two tasks: no interval is drawn, so only the up-front check can fail.
    with pytest.raises(ValueError, match="seed must be an int"):
        summarize(_two_tasks_two_repeats(), n_resamples=1000, seed=seed)


def test_resample_count_is_checked_before_pairing():
    with pytest.raises(ValueError, match="n_resamples=39"):
        summarize([], n_resamples=39, seed=7)
