"""Every workflow that runs scripts/ci_unit.sh installs mutmut (ADR-1122).

ci_unit.sh ends with the mutation gate, and mutmut lives in the `dev` dependency
group. `uv-locked-install` syncs with `--no-default-groups`, so a workflow that does
not pass `--group dev` fails with "Failed to spawn: mutmut" before any mutant runs
(#894, supersession-delete-parity).
"""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
# source: .github/actions/uv-locked-install/action.yml, its `set` input.
SET_LINE = re.compile(r"^\s*set:\s*(.+)$", re.MULTILINE)


def _runs_the_unit_suite(text: str) -> bool:
    return "scripts/ci_unit.sh" in text and "uv-locked-install" in text


def test_each_unit_suite_workflow_syncs_the_dev_group():
    checked = []
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        text = workflow.read_text(encoding="utf-8")
        if not _runs_the_unit_suite(text):
            continue
        sets = SET_LINE.findall(text)
        assert sets, f"{workflow.name}: no uv-locked-install `set:` line"
        for value in sets:
            assert "--group dev" in value.split("#")[0], f"{workflow.name}: {value}"
        checked.append(workflow.name)
    assert "supersession-delete-parity.yml" in checked
