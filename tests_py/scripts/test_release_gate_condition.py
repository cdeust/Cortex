"""Evaluate the release predicate, including GitHub's implicit status guard.

source: issue #628
Primary semantics: https://docs.github.com/en/actions/reference/workflows-and-actions/expressions#status-check-functions
Skipped needs chains: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idneeds
The interpreter intentionally supports only the boolean/equality expression
subset used by this job; unsupported syntax fails rather than silently passing.
"""

import ast
from pathlib import Path
import re

import pytest


def _condition():
    text = (
        Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml"
    ).read_text()
    body = re.search(r"^  release-gate:\n(.*?)(?=^  \S|\Z)", text, re.M | re.S)
    assert body is not None
    condition = re.search(r"^    if: (.+)$", body[1], re.M)
    assert condition is not None
    return condition[1]


def _evaluate(node, values):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return values[node.id]
    if isinstance(node, ast.Call):
        assert isinstance(node.func, ast.Name) and not node.args and not node.keywords
        return values[node.func.id]()
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _evaluate(node.operand, values)
    if isinstance(node, ast.BoolOp):
        results = [_evaluate(value, values) for value in node.values]
        if isinstance(node.op, ast.And):
            return all(results)
        if isinstance(node.op, ast.Or):
            return any(results)
    if isinstance(node, ast.Compare):
        assert len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq)
        return _evaluate(node.left, values) == _evaluate(node.comparators[0], values)
    raise AssertionError(f"Unsupported condition syntax: {ast.dump(node)}")


def _runs(expression, scenario):
    result, ancestors, event, ref, cancelled = scenario
    expression = expression.removeprefix("${{").removesuffix("}}")
    for path in ("needs.ci-green.result", "github.event_name", "github.ref"):
        expression = expression.replace(path, path.replace(".", "_").replace("-", "_"))
    expression = expression.replace("&&", " and ").replace("||", " or ")
    expression = re.sub(r"!(?!=)", " not ", expression)
    tree = ast.parse(expression.strip(), mode="eval").body
    values = {
        "needs_ci_green_result": result,
        "github_event_name": event,
        "github_ref": ref,
        "always": lambda: True,
        "cancelled": lambda: cancelled,
        "success": lambda: all(s == "success" for s in (*ancestors, result)),
        "failure": lambda: "failure" in (*ancestors, result),
    }
    explicit_status = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"always", "cancelled", "success", "failure"}
        for node in ast.walk(tree)
    )
    if not explicit_status and (cancelled or not values["success"]()):
        return False
    return _evaluate(tree, values)


@pytest.mark.parametrize(
    "case",
    [
        ("success", ["success"], "push", "refs/heads/main", False, True),
        # Issue #628: Docker ancestors skipped, but CI Green accepted the run.
        ("success", ["success", "skipped"], "push", "refs/heads/main", False, True),
        ("failure", ["failure"], "push", "refs/heads/main", False, False),
        ("cancelled", ["success"], "push", "refs/heads/main", True, False),
        ("skipped", ["skipped"], "push", "refs/heads/main", False, False),
        ("success", ["success"], "push", "refs/heads/main", True, False),
        ("success", ["skipped"], "pull_request", "refs/heads/main", False, False),
        ("success", ["skipped"], "push", "refs/heads/feature", False, False),
        ("success", ["skipped"], "push", "refs/tags/v4.23.2", False, False),
        ("success", ["skipped"], "workflow_dispatch", "refs/heads/main", False, False),
    ],
)
def test_release_condition(case):
    *scenario, expected = case
    assert _runs(_condition(), scenario) is expected
