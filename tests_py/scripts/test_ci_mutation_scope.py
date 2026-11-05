"""The mutation gate runs only the mutants of the changed functions (ADR-1122).

#865 ran all 262 mutants of one file for six hours, to judge the few in its changed
functions. ``mutation_check.sh`` now hands ``<prefix>*`` names to ``mutmut run``. The
shell cases drive the real script against a fake ``uv`` that records its arguments and
writes the files mutmut 3.8.1 writes, on every bash this host has.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from mcp_server.shared.platform import resolve_bash

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import ci_mutation_scope as scope  # noqa: E402

PREFIX = "mcp_server.core.a.x_f__mutmut_"
BASHES = sorted(
    {
        path
        for path in ("/bin/bash", resolve_bash())
        if path and os.access(path, os.X_OK)
    }
)
# A fake `uv run mutmut ...`: records `run` arguments, writes mutmut's files per
# FAKE_STATS / FAKE_MUTANTS, exits FAKE_RC; `results` lists nothing.
FAKE_UV = """#!/bin/sh
shift 2
if [ "$1" = run ]; then
  shift
  printf '%s\\n' "$@" > "$FAKE_ARGS"
  mkdir -p mutants/mcp_server/core
  [ -n "$FAKE_STATS" ] && echo '{}' > mutants/mutmut-stats.json
  meta=mutants/mcp_server/core/a.py.meta
  printf '{"exit_code_by_key": {%s}}' "$FAKE_MUTANTS" > "$meta"
  exit "$FAKE_RC"
fi
exit 0
"""
PYPROJECT = """[tool.mutmut]
source_paths = ["mcp_server"]
only_mutate = ["x"]
pytest_add_cli_args_test_selection = ["x"]
"""


def test_each_changed_function_becomes_a_name_glob():
    assert scope.name_globs([PREFIX, "m.xǁCǁg__mutmut_"]) == [
        f"{PREFIX}*",
        "m.xǁCǁg__mutmut_*",
    ]


def _mutants(tmp_path: Path, names: list[str], stats: bool = True) -> Path:
    root = tmp_path / "mutants"
    (root / "mcp_server").mkdir(parents=True)
    if stats:
        (root / scope.STATS_FILE).write_text("{}", encoding="utf-8")
    meta = {scope.MUTANTS_KEY: {name: None for name in names}}
    (root / "mcp_server" / "a.py.meta").write_text(json.dumps(meta), encoding="utf-8")
    return root


def test_the_in_scope_count_reads_mutmuts_meta_files(tmp_path):
    root = _mutants(tmp_path, [f"{PREFIX}1", f"{PREFIX}2", "m.x_other__mutmut_1"])
    assert scope.in_scope_count(root, [PREFIX]) == 2
    assert scope.in_scope_count(root, ["m.x_none__mutmut_"]) == 0


def test_no_stats_file_means_mutmut_failed_before_judging(tmp_path):
    root = _mutants(tmp_path, ["m.x_other__mutmut_1"], stats=False)
    assert scope.in_scope_count(root, [PREFIX]) is None


def _sandbox(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    for name in ("mutation_check.sh", "ci_mutation_scope.py", "ci_mutation_diff.py"):
        shutil.copy(REPO / "scripts" / name, root / "scripts" / name)
    shutil.copy(REPO / "scripts" / "ci_diff_lines.py", root / "scripts")
    (root / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    fake = tmp_path / "bin" / "uv"
    fake.parent.mkdir()
    fake.write_text(FAKE_UV, encoding="utf-8")
    fake.chmod(0o755)
    return root


def _gate(bash, tmp_path, *, prefixes, rc=0, stats="1", mutants=""):
    root = _sandbox(tmp_path)
    args = tmp_path / "args.txt"
    env = {
        **os.environ,
        "PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}",
        "MUTATION_ONLY_PREFIXES": prefixes,
        "FAKE_ARGS": str(args),
        "FAKE_RC": str(rc),
        "FAKE_STATS": stats,
        "FAKE_MUTANTS": mutants,
    }
    script = str(root / "scripts" / "mutation_check.sh")
    done = subprocess.run(
        [bash, script, "tests_py/test_a.py", "--", "mcp_server/core/a.py"],
        capture_output=True,
        text=True,
        env=env,
    )
    ran = args.read_text(encoding="utf-8").split() if args.exists() else None
    return done, ran


@pytest.mark.parametrize("bash", BASHES, ids=lambda path: f"bash={path}")
def test_a_scoped_run_names_only_the_changed_functions(bash, tmp_path):
    done, ran = _gate(bash, tmp_path, prefixes=PREFIX)
    assert done.returncode == 0, done.stderr
    assert ran == [f"{PREFIX}*"]


@pytest.mark.parametrize("bash", BASHES, ids=lambda path: f"bash={path}")
def test_without_a_scope_every_mutant_runs_as_before(bash, tmp_path):
    done, ran = _gate(bash, tmp_path, prefixes="")
    assert done.returncode == 0, done.stderr
    assert ran == []


@pytest.mark.parametrize("bash", BASHES, ids=lambda path: f"bash={path}")
def test_changed_functions_without_a_mutant_have_nothing_to_judge(bash, tmp_path):
    other = '"m.x_other__mutmut_1": null'
    done, _ = _gate(bash, tmp_path, prefixes=PREFIX, rc=1, mutants=other)
    assert done.returncode == 0, done.stderr
    assert "hold no mutant" in done.stdout


@pytest.mark.parametrize("bash", BASHES, ids=lambda path: f"bash={path}")
def test_a_failure_before_the_stats_file_still_fails(bash, tmp_path):
    done, _ = _gate(bash, tmp_path, prefixes=PREFIX, rc=1, stats="")
    assert done.returncode == 1


@pytest.mark.parametrize("bash", BASHES, ids=lambda path: f"bash={path}")
def test_a_failure_with_mutants_in_scope_still_fails(bash, tmp_path):
    done, _ = _gate(bash, tmp_path, prefixes=PREFIX, rc=1, mutants=f'"{PREFIX}1": null')
    assert done.returncode == 1
