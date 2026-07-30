"""Tests for core.procedural_memory (B1 procedural/skill memory).

Verifies the pure-logic contract: action normalization, frequent-subsequence
mining (Graybiel chunking), the reinforcement/proficiency update (Schultz RPE),
habitual graduation, and situational retrieval.
"""

from __future__ import annotations

from mcp_server.core.procedural_memory import (
    ActionStep,
    ProceduralSkill,
    HABITUAL_THRESHOLD,
    MIN_SKILL_SUPPORT,
    action_step_key,
    context_signature,
    infer_target_kind,
    match_skills,
    mine_skills,
    normalize_actions,
    procedural_skill_as_dict,
    procedural_skill_is_habitual,
    reinforce,
    skill_id_for,
)


# ── Normalization ───────────────────────────────────────────────────────────
def test_normalize_accepts_string_form():
    steps = normalize_actions(["read_file", "edit_file", "bash"])
    assert [s.tool for s in steps] == ["read_file", "edit_file", "bash"]
    assert all(s.target_kind is None for s in steps)


def test_normalize_collapses_consecutive_duplicates():
    steps = normalize_actions(["read_file", "read_file", "read_file", "bash"])
    assert [s.tool for s in steps] == ["read_file", "bash"]


def test_normalize_rich_form_infers_target_kind():
    steps = normalize_actions(
        [
            {"tool": "edit_file", "target": "tests_py/core/test_x.py"},
            {"tool": "bash", "target": "pytest"},
        ]
    )
    assert steps[0].target_kind == "test"
    assert action_step_key(steps[0]) == "edit_file:test"


def test_infer_target_kind_classes():
    assert infer_target_kind("config.yaml") == "config"
    assert infer_target_kind("README.md") == "doc"
    assert infer_target_kind("schema.sql") == "schema"
    assert infer_target_kind("module.py") == "code"
    assert infer_target_kind(None) is None


def test_skill_id_stable_and_order_sensitive():
    a = (ActionStep("read_file"), ActionStep("edit_file"))
    b = (ActionStep("edit_file"), ActionStep("read_file"))
    assert skill_id_for(a) == skill_id_for(a)
    assert skill_id_for(a) != skill_id_for(b)


# ── Mining (Graybiel chunking) ──────────────────────────────────────────────
def _session(
    tools, outcome="success", domain="cortex", cwd="/repo/cortex", ts="2026-07-01"
):
    return {
        "tools_used": tools,
        "outcome": outcome,
        "domain": domain,
        "cwd": cwd,
        "timestamp": ts,
    }


def test_mine_requires_min_support():
    # The routine appears in only 2 sessions -> below default support (3).
    sessions = [
        _session(["read_file", "edit_file", "bash"]),
        _session(["read_file", "edit_file", "bash"]),
    ]
    skills = mine_skills(sessions)
    assert skills == []


def test_mine_extracts_recurring_routine():
    routine = ["read_file", "edit_file", "bash"]
    sessions = [_session(routine) for _ in range(MIN_SKILL_SUPPORT)]
    skills = mine_skills(sessions)
    assert skills, "expected at least one mined skill"
    # The full 3-step routine should be among the mined skills.
    seqs = {tuple(procedural_skill_as_dict(s)["sequence"]) for s in skills}
    assert ("read_file", "edit_file", "bash") in seqs
    top = skills[0]
    assert top.occurrences >= MIN_SKILL_SUPPORT
    assert top.proficiency > 0.5  # all-success routine


def test_mine_counts_sequence_once_per_session():
    # Same pair repeated within a session must not inflate support.
    sessions = [
        _session(["a", "b", "c", "a", "b", "c"]) for _ in range(MIN_SKILL_SUPPORT)
    ]
    skills = mine_skills(sessions)
    ab = next(
        (
            s
            for s in skills
            if tuple(procedural_skill_as_dict(s)["sequence"])[:2] == ("a", "b")
        ),
        None,
    )
    assert ab is not None
    # occurrences == number of sessions, not number of in-session repeats
    assert ab.occurrences == MIN_SKILL_SUPPORT


def test_mine_failure_lowers_proficiency():
    routine = ["plan", "apply", "verify"]
    good = [_session(routine, outcome="success") for _ in range(3)]
    bad = [_session(routine, outcome="failure") for _ in range(3)]
    p_good = mine_skills(good)[0].proficiency
    p_bad = mine_skills(bad)[0].proficiency
    assert p_good > 0.6
    assert p_bad < 0.4


# ── Reinforcement (Schultz RPE) ─────────────────────────────────────────────
def test_reinforce_moves_toward_reward():
    s = ProceduralSkill(sequence=(ActionStep("a"), ActionStep("b")))
    s1 = reinforce(s, "success")
    s2 = reinforce(s1, "success")
    assert s2.proficiency > s1.proficiency
    assert s2.success_count == 2
    assert s2.occurrences == 2


def test_reinforce_failure_decreases_proficiency():
    s = ProceduralSkill(
        sequence=(ActionStep("a"), ActionStep("b")),
        proficiency=0.9,
        occurrences=4,
        success_count=4,
    )
    s1 = reinforce(s, "failure")
    assert s1.proficiency < 0.9
    assert s1.failure_count == 1


def test_reinforce_neutral_outcome_is_noop_on_rate():
    s = ProceduralSkill(
        sequence=(ActionStep("a"), ActionStep("b")),
        proficiency=0.7,
        occurrences=3,
        success_count=2,
    )
    s1 = reinforce(s, None)
    assert s1.proficiency == 0.7  # rate unchanged
    assert s1.occurrences == 4  # but the observation is counted
    assert s1.success_count == 2


def test_habitual_graduation():
    s = ProceduralSkill(sequence=(ActionStep("a"), ActionStep("b")))
    for _ in range(HABITUAL_THRESHOLD):
        s = reinforce(s, "success")
    assert procedural_skill_is_habitual(s)
    # one fewer success is not yet habitual
    s2 = ProceduralSkill(
        sequence=(ActionStep("a"), ActionStep("b")),
        success_count=HABITUAL_THRESHOLD - 1,
    )
    assert not procedural_skill_is_habitual(s2)


# ── Situational retrieval ───────────────────────────────────────────────────
def test_context_signature_domain_and_leaf():
    sig = context_signature({"domain": "Cortex", "cwd": "/home/u/repo/cortex"})
    assert sig == "cortex|cortex"


def test_match_filters_low_proficiency():
    reliable = ProceduralSkill(
        sequence=(ActionStep("read_file"), ActionStep("edit_file")),
        context_signature="cortex",
        occurrences=6,
        success_count=6,
        proficiency=0.9,
    )
    flaky = ProceduralSkill(
        sequence=(ActionStep("x"), ActionStep("y")),
        context_signature="cortex",
        occurrences=6,
        success_count=1,
        proficiency=0.2,
    )
    out = match_skills(
        {"domain": "cortex", "cwd": "/repo/cortex"},
        [reliable, flaky],
        min_proficiency=0.5,
    )
    ids = {m["skill"]["skill_id"] for m in out}
    assert reliable.skill_id in ids
    assert flaky.skill_id not in ids


def test_match_prefers_context_overlap():
    here = ProceduralSkill(
        sequence=(ActionStep("a"), ActionStep("b")),
        context_signature="cortex|cortex",
        occurrences=5,
        success_count=5,
        proficiency=0.9,
    )
    elsewhere = ProceduralSkill(
        sequence=(ActionStep("c"), ActionStep("d")),
        context_signature="otherproj|otherproj",
        occurrences=5,
        success_count=5,
        proficiency=0.9,
    )
    out = match_skills({"domain": "cortex", "cwd": "/repo/cortex"}, [elsewhere, here])
    assert out[0]["skill"]["skill_id"] == here.skill_id


def test_match_priming_bonus():
    skill = ProceduralSkill(
        sequence=(ActionStep("read_file"), ActionStep("edit_file")),
        context_signature="cortex",
        occurrences=5,
        success_count=5,
        proficiency=0.9,
    )
    primed = match_skills(
        {"domain": "cortex", "cwd": "/repo/cortex", "tools_used": ["read_file"]},
        [skill],
    )
    unprimed = match_skills(
        {"domain": "cortex", "cwd": "/repo/cortex", "tools_used": ["grep"]}, [skill]
    )
    assert primed[0]["score"] > unprimed[0]["score"]


# ── procedural_skill_as_dict shape (issue #282: dataclass mutation blindspot) —
def test_procedural_skill_as_dict_full_shape():
    skill = ProceduralSkill(
        sequence=(ActionStep("read_file"), ActionStep("edit_file", "test")),
        context_signature="cortex|repo",
        occurrences=7,
        success_count=6,
        failure_count=1,
        # A 5th-decimal digit so round(x, 4) vs round(x, 5) and vs
        # round(x, None)/round(x) (int truncation) are all observably
        # different — a value like 0.9 rounds identically at every
        # precision and can't distinguish the mutants.
        proficiency=0.912345,
        last_seen="2026-01-01T00:00:00+00:00",
    )
    d = procedural_skill_as_dict(skill)
    assert d == {
        "skill_id": skill.skill_id,
        "sequence": ["read_file", "edit_file:test"],
        "context_signature": "cortex|repo",
        "occurrences": 7,
        "success_count": 6,
        "failure_count": 1,
        "proficiency": round(0.912345, 4),
        "is_habitual": True,  # success_count 6 >= HABITUAL_THRESHOLD 5
        "last_seen": "2026-01-01T00:00:00+00:00",
    }
