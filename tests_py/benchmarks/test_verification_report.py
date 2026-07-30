"""Direct unit tests for `benchmarks.lib.verification_report`'s ExpResult
free functions (issue #282: dataclass mutation blindspot).

`ExpResult` is a plain `@dataclass`; mutmut categorically skips the body of
any `@dataclass`-decorated class (`mutmut/mutation/file_mutation.py:236`),
so the lookup/verdict logic that used to live on `ExpResult.name` /
`.threshold` / `.verdict` carries zero mutation coverage unless exercised
directly against the extracted free functions. No test module for
`verification_report.py` existed prior to this file.
"""

from __future__ import annotations

from benchmarks.lib.verification_report import (
    HYPOTHESES,
    ExpResult,
    exp_result_name,
    exp_result_threshold,
    exp_result_verdict,
)


def test_exp_result_name_looks_up_hypotheses_table():
    r = ExpResult(exp_id="E1")
    assert exp_result_name(r) == HYPOTHESES["E1"]["name"]


def test_exp_result_threshold_looks_up_hypotheses_table():
    r = ExpResult(exp_id="E3")
    assert exp_result_threshold(r) == HYPOTHESES["E3"]["threshold"]


def test_verdict_inconclusive_when_not_found():
    r = ExpResult(exp_id="E1", found=False)
    assert exp_result_verdict(r) == "INCONCLUSIVE"


def test_verdict_inconclusive_when_found_but_no_observed_value():
    r = ExpResult(exp_id="E1", found=True, observed=None)
    assert exp_result_verdict(r) == "INCONCLUSIVE"


def test_verdict_pass_for_ge_operator():
    # E1's pass_op is ">=", pass_value 0.01.
    r = ExpResult(exp_id="E1", found=True, observed=0.01)
    assert exp_result_verdict(r) == "PASS"


def test_verdict_fail_for_ge_operator_below_threshold():
    r = ExpResult(exp_id="E1", found=True, observed=0.001)
    assert exp_result_verdict(r) == "FAIL"


def test_verdict_pass_for_lt_operator():
    # E3's pass_op is "<", pass_value 0.05.
    r = ExpResult(exp_id="E3", found=True, observed=0.049)
    assert exp_result_verdict(r) == "PASS"


def test_verdict_fail_for_lt_operator_at_boundary():
    r = ExpResult(exp_id="E3", found=True, observed=0.05)
    assert exp_result_verdict(r) == "FAIL"


# ── The ">" / "<=" branches + the unrecognized-op fallback (issue #282:
# no HYPOTHESES entry currently uses ">" or "<=" as pass_op, so those two
# `cmp` dict branches and the `cmp.get(op, False)` default value are
# unreachable through the real table alone — a monkeypatched HYPOTHESES
# entry exercises them directly rather than leaving them permanently
# invisible to mutation testing). ──────────────────────────────────────
def test_verdict_gt_operator_pass_and_fail(monkeypatch):
    monkeypatch.setitem(
        HYPOTHESES,
        "ZZ_GT",
        {"name": "n", "threshold": "t", "pass_op": ">", "pass_value": 1.0},
    )
    assert (
        exp_result_verdict(ExpResult(exp_id="ZZ_GT", found=True, observed=1.5))
        == "PASS"
    )
    assert (
        exp_result_verdict(ExpResult(exp_id="ZZ_GT", found=True, observed=1.0))
        == "FAIL"
    )


def test_verdict_le_operator_pass_and_fail(monkeypatch):
    monkeypatch.setitem(
        HYPOTHESES,
        "ZZ_LE",
        {"name": "n", "threshold": "t", "pass_op": "<=", "pass_value": 1.0},
    )
    assert (
        exp_result_verdict(ExpResult(exp_id="ZZ_LE", found=True, observed=1.0))
        == "PASS"
    )
    assert (
        exp_result_verdict(ExpResult(exp_id="ZZ_LE", found=True, observed=1.5))
        == "FAIL"
    )


def test_verdict_unrecognized_operator_defaults_to_fail(monkeypatch):
    monkeypatch.setitem(
        HYPOTHESES,
        "ZZ_BAD",
        {"name": "n", "threshold": "t", "pass_op": "!=", "pass_value": 1.0},
    )
    assert (
        exp_result_verdict(ExpResult(exp_id="ZZ_BAD", found=True, observed=99.0))
        == "FAIL"
    )
