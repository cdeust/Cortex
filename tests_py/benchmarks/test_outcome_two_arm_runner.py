"""Tests for benchmarks/outcome/two_arm_runner.py (issue #343, slice 4).

A fake agent stands in for the model: it records every call and answers from
a table, so the order of the trials, the scoring against the key and the
served-model check are observed directly, never read back from the runner."""

from __future__ import annotations

import os
import stat

import pytest

from benchmarks.outcome.answer_key import (
    FAMILY_APPROACH,
    FAMILY_COMMIT,
    FAMILY_VALUE,
    OutcomeTask,
)
from benchmarks.outcome.paired_delta import ARM_NO_RECALL, ARM_RECALL, summarize
from benchmarks.outcome.two_arm_runner import (
    AgentResult,
    RunSpec,
    run_two_arms,
    snapshot_corpus,
)
from tests_py.benchmarks.outcome_git import git, make_repo

_SPEC = RunSpec(model="m", effort="high", repeats=2)


def _corpus(tmp_path):
    repo = make_repo(tmp_path / "src")
    first, head = git(repo, "rev-list", "--reverse", "HEAD").split()
    return repo, first, head


def _tasks(commit):
    return (
        OutcomeTask(
            "c", FAMILY_COMMIT, "which commit added f.txt?", {"commit": commit}
        ),
        OutcomeTask("a", FAMILY_APPROACH, "was X tried?", {"tried": False}),
        OutcomeTask(
            "v", FAMILY_VALUE, "value of Z?", {"values": ["7"], "sources": ["z.py"]}
        ),
    )


class _FakeAgent:
    def __init__(self, answers, served=("m", "high")):
        self.answers = answers
        self.served = served
        self.calls = []

    def __call__(self, task, arm, spec):
        self.calls.append((task.task_id, arm))
        turns = 2 if arm == ARM_RECALL else 5
        return AgentResult(
            self.answers[(task.task_id, arm)], turns, 10 * turns, *self.served
        )


def _answers(commit):
    right = {
        "c": {"commit": commit[:7]},
        "a": {"tried": False},
        "v": {"value": "7", "source": "z.py:3"},
    }
    wrong = {
        "c": {"commit": "0000"},
        "a": {"tried": True},
        "v": {"value": "8", "source": "z.py"},
    }
    table = {(t, ARM_RECALL): a for t, a in right.items()}
    table.update({(t, ARM_NO_RECALL): a for t, a in wrong.items()})
    return table


def test_snapshot_is_a_read_only_bare_clone_holding_the_pin(tmp_path):
    repo, _, head = _corpus(tmp_path)
    snap = snapshot_corpus(repo, tmp_path / "snap", head)
    assert git(snap, "rev-parse", "--is-bare-repository") == "true"
    assert not (snap / "objects" / "info" / "alternates").exists()
    for root, dirs, files in os.walk(snap):
        for name in dirs + files:
            assert not os.stat(os.path.join(root, name)).st_mode & stat.S_IWUSR


def test_snapshot_refuses_an_existing_destination_and_a_missing_pin(tmp_path):
    repo, _, _ = _corpus(tmp_path)
    (tmp_path / "taken").mkdir()
    with pytest.raises(ValueError, match="already exists"):
        snapshot_corpus(repo, tmp_path / "taken", "0" * 40)
    with pytest.raises(RuntimeError):
        snapshot_corpus(repo, tmp_path / "snap", "1" * 40)


def test_both_arms_run_the_same_tasks_in_the_same_order_each_sweep(tmp_path):
    repo, first, head = _corpus(tmp_path)
    snap = snapshot_corpus(repo, tmp_path / "snap", head)
    agent = _FakeAgent(_answers(first))
    run_two_arms(_tasks(first), agent, _SPEC, snap)
    sweep = [(t, ARM_RECALL) for t in "cav"] + [(t, ARM_NO_RECALL) for t in "cav"]
    assert agent.calls == sweep * 2


def test_trials_are_scored_against_the_key_and_pair_for_summarize(tmp_path):
    repo, first, head = _corpus(tmp_path)
    snap = snapshot_corpus(repo, tmp_path / "snap", head)
    trials = run_two_arms(_tasks(first), _FakeAgent(_answers(first)), _SPEC, snap)
    assert {(t.arm, t.correct) for t in trials} == {
        (ARM_RECALL, True),
        (ARM_NO_RECALL, False),
    }
    assert {t.repeat for t in trials} == {0, 1}
    report = summarize(trials, n_resamples=40, seed=0)
    by_metric = {d.metric: d.mean_delta for d in report.deltas}
    # recall right (1), baseline wrong (0); turns 2 - 5; tokens 20 - 50.
    assert by_metric == {"correct": 1.0, "turns": -3.0, "tokens": -30.0}
    assert report.n_tasks == 3 and report.n_repeats == 2


@pytest.mark.parametrize("served", [("other", "high"), ("m", "low")])
def test_a_trial_served_by_another_model_or_effort_stops_the_run(tmp_path, served):
    repo, first, head = _corpus(tmp_path)
    snap = snapshot_corpus(repo, tmp_path / "snap", head)
    agent = _FakeAgent(_answers(first), served=served)
    with pytest.raises(ValueError, match="the run requires 'm' at 'high'"):
        run_two_arms(_tasks(first), agent, _SPEC, snap)
    assert len(agent.calls) == 1


def test_a_commit_key_outside_the_snapshot_fails_before_any_trial(tmp_path):
    repo, first, head = _corpus(tmp_path)
    snap = snapshot_corpus(repo, tmp_path / "snap", head)
    agent = _FakeAgent(_answers(first))
    with pytest.raises(ValueError, match="is not a commit of the corpus"):
        run_two_arms(_tasks("f" * 40), agent, _SPEC, snap)
    assert agent.calls == []


def test_an_empty_task_set_is_refused(tmp_path):
    with pytest.raises(ValueError, match="non-empty sequence"):
        run_two_arms((), _FakeAgent({}), _SPEC, tmp_path)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"model": "", "effort": "high", "repeats": 1},
        {"model": "m", "effort": " ", "repeats": 1},
        {"model": "m", "effort": "high", "repeats": 0},
        {"model": "m", "effort": "high", "repeats": True},
    ],
)
def test_run_spec_rejects_an_unusable_configuration(kwargs):
    with pytest.raises(ValueError):
        RunSpec(**kwargs)
