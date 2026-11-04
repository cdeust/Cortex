"""Paired two-arm outcome scoring for the longitudinal outcome benchmark.

Each trial is one (task, arm, repeat) run scored on outcome: was the answer
correct against the independent answer key, how many turns it took, how many
tokens it spent. The two arms — ``recall`` and ``no_recall`` — run the same
task set with the same repeats, so every recall trial has exactly one
baseline counterpart. A repeat ``r`` is one full pass over the task set in
the same order (issue #343, step 3), so the same ``r`` across tasks belongs
to one sweep; the runner (slice 4) must keep that labelling.

Input is checked strictly and ``ValueError`` is raised, never a silent drop,
because an unpaired or malformed trial would bias the delta: a malformed
field, an unknown arm, an unknown metric name, a duplicate trial, a missing
counterpart, tasks run with different repeat labels, empty input, or a
resample count that is not an int large enough to place both percentile
bounds (at least 40 for a 95% interval), or a seed that is not an int (a
``None`` seed would silently draw from OS entropy and make the interval
irreproducible). The resample count and the seed are checked up front, even
when too few tasks leave no interval to compute, so a bad configuration
fails on its first run rather than on its first large one.

For each metric the report gives:

- ``mean_delta``: mean over all pairs of (recall − no_recall);
- ``repeat_std``: sample standard deviation of the per-sweep mean delta,
  ``None`` with a single repeat — one paired run is an anecdote, not a
  result (issue #343, step 5);
- ``ci95``: percentile bootstrap interval of the mean delta, resampling
  tasks with replacement (each task contributes its mean over repeats, so
  repeats of one task are never treated as independent). The same task
  resamples are used for every metric. ``None`` below the minimum task
  count ``benchmarks/lib/verification_report.py`` requires for an interval.

A null or negative delta is reported as computed; nothing here clips it.

source: issue #343; Efron & Tibshirani (1993), An Introduction to the
Bootstrap, ch. 13 (percentile interval)"""

from __future__ import annotations

import random
import statistics
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

ARM_RECALL = "recall"
ARM_NO_RECALL = "no_recall"
METRICS = ("correct", "turns", "tokens")

# source: Efron & Tibshirani (1993) ch. 13 — 95% percentile interval, the
# same level benchmarks/lib/verification_report.py::_bootstrap_ci reports
_CI_ALPHA = 0.05

# source: borrowed, for consistency only, from the minimum sample count
# benchmarks/lib/verification_report.py::_bootstrap_ci requires before it
# reports any interval (_MIN_VALUES_FOR_CI). ADR-0090 records that value as
# a pre-existing tuned one whose provenance was never recorded; it is not
# justified here either. Here the samples are tasks.
_MIN_TASKS_FOR_CI = 10

# source: definition — the sample standard deviation is undefined below two
# samples
_MIN_REPEATS_FOR_SPREAD = 2


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


@dataclass(frozen=True)
class TrialOutcome:
    task_id: str
    arm: str
    repeat: int
    correct: bool
    turns: int
    tokens: int

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id:
            raise ValueError(f"task_id must be a non-empty string: {self.task_id!r}")
        if self.arm not in (ARM_RECALL, ARM_NO_RECALL):
            raise ValueError(f"unknown arm {self.arm!r} for task {self.task_id!r}")
        if not isinstance(self.correct, bool):
            raise ValueError(f"correct must be a bool: {self.correct!r}")
        for name in ("repeat", "turns", "tokens"):
            if not _is_count(getattr(self, name)):
                raise ValueError(
                    f"{name} must be a non-negative int: {getattr(self, name)!r}"
                    f" for task {self.task_id!r}"
                )

    def metric(self, name: str) -> float:
        if name not in METRICS:
            raise ValueError(f"unknown metric {name!r}; expected one of {METRICS}")
        return float(getattr(self, name))


@dataclass(frozen=True)
class MetricDelta:
    metric: str
    mean_delta: float
    # Spread of one sweep's mean delta across sweeps — not the standard error
    # of ``mean_delta``, which averages over all sweeps.
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
    pairs: Pairs = {}
    repeat_sets: dict[str, set[int]] = defaultdict(set)
    for task, rep in sorted({(task, rep) for task, _, rep in index}):
        recall = index.get((task, ARM_RECALL, rep))
        baseline = index.get((task, ARM_NO_RECALL, rep))
        if recall is None or baseline is None:
            missing = ARM_RECALL if recall is None else ARM_NO_RECALL
            raise ValueError(f"task {task!r} repeat {rep} has no {missing} trial")
        pairs[(task, rep)] = (recall, baseline)
        repeat_sets[task].add(rep)
    if len({frozenset(reps) for reps in repeat_sets.values()}) != 1:
        raise ValueError(f"tasks ran different repeats: {dict(repeat_sets)}")
    return pairs


def _pair_deltas(pairs: Pairs, metric: str) -> dict[tuple[str, int], float]:
    return {
        cell: recall.metric(metric) - baseline.metric(metric)
        for cell, (recall, baseline) in pairs.items()
    }


def _grouped_means(deltas: dict[tuple[str, int], float], by: int) -> list[float]:
    groups: dict[object, list[float]] = defaultdict(list)
    for cell, value in sorted(deltas.items()):
        groups[cell[by]].append(value)
    return [statistics.fmean(groups[key]) for key in sorted(groups)]


def _percentile_ranks(n_resamples: int) -> tuple[int, int]:
    """Symmetric ranks: as many resamples below ``low`` as above ``high``."""
    if not _is_count(n_resamples):
        raise ValueError(f"n_resamples must be a non-negative int: {n_resamples!r}")
    tail = int((_CI_ALPHA / 2) * n_resamples)
    if tail < 1:
        raise ValueError(
            f"n_resamples={n_resamples} leaves no resample in a "
            f"{_CI_ALPHA / 2:.3f} tail; both percentile bounds need one"
        )
    return tail, n_resamples - 1 - tail


def _draw_resamples(
    n_tasks: int, n_resamples: int, seed: int
) -> list[list[int]] | None:
    """Task indices for every resample, shared by all metrics."""
    if n_tasks < _MIN_TASKS_FOR_CI:
        return None
    rng = random.Random(seed)
    return [rng.choices(range(n_tasks), k=n_tasks) for _ in range(n_resamples)]


def _bootstrap_ci(
    task_means: list[float], resamples: list[list[int]] | None
) -> tuple[float, float] | None:
    if resamples is None:
        return None
    means = sorted(statistics.fmean(task_means[i] for i in draw) for draw in resamples)
    low, high = _percentile_ranks(len(resamples))
    return (means[low], means[high])


def _metric_delta(
    pairs: Pairs, metric: str, resamples: list[list[int]] | None
) -> MetricDelta:
    deltas = _pair_deltas(pairs, metric)
    sweep_means = _grouped_means(deltas, by=1)
    return MetricDelta(
        metric=metric,
        mean_delta=statistics.fmean(deltas.values()),
        repeat_std=(
            statistics.stdev(sweep_means)
            if len(sweep_means) >= _MIN_REPEATS_FOR_SPREAD
            else None
        ),
        ci95=_bootstrap_ci(_grouped_means(deltas, by=0), resamples),
    )


def summarize(
    trials: Iterable[TrialOutcome], *, n_resamples: int, seed: int
) -> OutcomeDeltaReport:
    """Score both arms; ``seed`` makes the bootstrap reproducible."""
    # Checked before pairing on purpose: see the module docstring.
    _percentile_ranks(n_resamples)
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError(f"seed must be an int: {seed!r}")
    pairs = pair_trials(trials)
    n_tasks = len({task for task, _ in pairs})
    n_repeats = len({rep for _, rep in pairs})
    resamples = _draw_resamples(n_tasks, n_resamples, seed)
    return OutcomeDeltaReport(
        n_tasks=n_tasks,
        n_repeats=n_repeats,
        is_anecdote=n_repeats < _MIN_REPEATS_FOR_SPREAD,
        deltas=tuple(_metric_delta(pairs, m, resamples) for m in METRICS),
    )
