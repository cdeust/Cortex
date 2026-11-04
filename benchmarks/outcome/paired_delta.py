"""Paired two-arm outcome scoring for the longitudinal outcome benchmark.

Each trial is one (task, arm, repeat) run scored on outcome: was the answer
correct against the independent answer key, how many turns it took, how many
tokens it spent. The two arms — ``recall`` and ``no_recall`` — run the same
task set with the same repeats, so every recall trial has exactly one
baseline counterpart. Pairing is strict: a missing counterpart, a duplicate
trial, an unknown arm or a task whose repeats differ from the others raises
``ValueError`` rather than being dropped, because a silently unpaired trial
would bias the delta.

For each metric the report gives:

- ``mean_delta``: mean over all pairs of (recall − no_recall);
- ``repeat_std``: sample standard deviation of the per-repeat mean delta
  across repeats, ``None`` with a single repeat — one paired run is an
  anecdote, not a result (issue #343, step 5);
- ``ci95``: percentile bootstrap interval of the mean delta, resampling
  tasks with replacement (each task contributes its mean over repeats, so
  repeats of one task are never treated as independent), ``None`` with
  fewer than two tasks, where every resample is the same task.

A null or negative delta is reported as computed; nothing here clips it.

source: issue #343; Efron & Tibshirani (1993), An Introduction to the
Bootstrap, ch. 13 (percentile interval)"""

from __future__ import annotations

import random
import statistics
from collections.abc import Iterable
from dataclasses import dataclass

ARM_RECALL = "recall"
ARM_NO_RECALL = "no_recall"
METRICS = ("correct", "turns", "tokens")

# source: Efron & Tibshirani (1993) ch. 13 — 95% percentile interval, the
# same level benchmarks/lib/verification_report.py::_bootstrap_ci reports
_CI_ALPHA = 0.05

# source: definition — the sample standard deviation is undefined below two
# samples and a bootstrap over a single task resamples the same value
_MIN_SAMPLES_FOR_SPREAD = 2


@dataclass(frozen=True)
class TrialOutcome:
    task_id: str
    arm: str
    repeat: int
    correct: bool
    turns: int
    tokens: int

    def metric(self, name: str) -> float:
        return float(getattr(self, name))


@dataclass(frozen=True)
class MetricDelta:
    metric: str
    mean_delta: float
    repeat_std: float | None
    ci95: tuple[float, float] | None


@dataclass(frozen=True)
class OutcomeDeltaReport:
    n_tasks: int
    n_repeats: int
    is_anecdote: bool
    deltas: tuple[MetricDelta, ...]


Pairs = dict[tuple[str, int], tuple[TrialOutcome, TrialOutcome]]


def _index_trials(
    trials: Iterable[TrialOutcome],
) -> dict[tuple[str, str, int], TrialOutcome]:
    index: dict[tuple[str, str, int], TrialOutcome] = {}
    for trial in trials:
        if trial.arm not in (ARM_RECALL, ARM_NO_RECALL):
            raise ValueError(f"unknown arm {trial.arm!r} for task {trial.task_id!r}")
        key = (trial.task_id, trial.arm, trial.repeat)
        if key in index:
            raise ValueError(f"duplicate trial {key}")
        index[key] = trial
    if not index:
        raise ValueError("no trials to score")
    return index


def pair_trials(trials: Iterable[TrialOutcome]) -> Pairs:
    """Map (task_id, repeat) to its (recall, no_recall) pair, strictly."""
    index = _index_trials(trials)
    cells = {(task, rep) for task, _, rep in index}
    pairs: Pairs = {}
    for task, rep in sorted(cells):
        recall = index.get((task, ARM_RECALL, rep))
        baseline = index.get((task, ARM_NO_RECALL, rep))
        if recall is None or baseline is None:
            missing = ARM_RECALL if recall is None else ARM_NO_RECALL
            raise ValueError(f"task {task!r} repeat {rep} has no {missing} trial")
        pairs[(task, rep)] = (recall, baseline)
    repeat_sets = {
        task: frozenset(r for t, r in pairs if t == task) for task, _ in pairs
    }
    if len(set(repeat_sets.values())) != 1:
        raise ValueError(f"tasks ran different repeats: {repeat_sets}")
    return pairs


def _pair_deltas(pairs: Pairs, metric: str) -> dict[tuple[str, int], float]:
    return {
        cell: recall.metric(metric) - baseline.metric(metric)
        for cell, (recall, baseline) in pairs.items()
    }


def _grouped_means(deltas: dict[tuple[str, int], float], by: int) -> list[float]:
    groups: dict[object, list[float]] = {}
    for cell, value in sorted(deltas.items()):
        groups.setdefault(cell[by], []).append(value)
    return [statistics.fmean(values) for values in groups.values()]


def _bootstrap_ci(
    task_means: list[float], n_resamples: int, rng: random.Random
) -> tuple[float, float] | None:
    if len(task_means) < _MIN_SAMPLES_FOR_SPREAD:
        return None
    n = len(task_means)
    means = sorted(
        statistics.fmean(rng.choices(task_means, k=n)) for _ in range(n_resamples)
    )
    low = means[int((_CI_ALPHA / 2) * n_resamples)]
    high = means[min(int((1 - _CI_ALPHA / 2) * n_resamples), n_resamples - 1)]
    return (low, high)


def _metric_delta(
    pairs: Pairs, metric: str, n_resamples: int, rng: random.Random
) -> MetricDelta:
    deltas = _pair_deltas(pairs, metric)
    repeat_means = _grouped_means(deltas, by=1)
    return MetricDelta(
        metric=metric,
        mean_delta=statistics.fmean(deltas.values()),
        repeat_std=(
            statistics.stdev(repeat_means)
            if len(repeat_means) >= _MIN_SAMPLES_FOR_SPREAD
            else None
        ),
        ci95=_bootstrap_ci(_grouped_means(deltas, by=0), n_resamples, rng),
    )


def summarize(
    trials: Iterable[TrialOutcome], *, n_resamples: int, seed: int
) -> OutcomeDeltaReport:
    """Score both arms; ``seed`` makes the bootstrap reproducible."""
    if n_resamples < 1:
        raise ValueError("n_resamples must be positive")
    pairs = pair_trials(trials)
    rng = random.Random(seed)
    n_repeats = len({rep for _, rep in pairs})
    return OutcomeDeltaReport(
        n_tasks=len({task for task, _ in pairs}),
        n_repeats=n_repeats,
        is_anecdote=n_repeats < _MIN_SAMPLES_FOR_SPREAD,
        deltas=tuple(_metric_delta(pairs, m, n_resamples, rng) for m in METRICS),
    )
