"""The mutation gate runs only the mutants of the changed functions (ADR-1122).

#865 ran all 262 mutants of one file for six hours, to judge the few in its changed
functions. ``mutation_check.sh`` now hands ``<prefix>*`` names to ``mutmut run``. The
shell cases drive the real script against a fake ``uv`` that records its arguments and
writes the files mutmut 3.8.1 writes, on every bash this host has.
"""

from __future__ import annotations

import json
import os
import platform
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
  grep '^process_isolation' pyproject.toml > "$FAKE_ARGS.isolation"
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
process_isolation = "forkserver"
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


SOURCES = ["mcp_server/a.py"]


def test_the_in_scope_count_reads_mutmuts_meta_files(tmp_path):
    root = _mutants(tmp_path, [f"{PREFIX}1", f"{PREFIX}2", "m.x_other__mutmut_1"])
    assert scope.in_scope_count(root, [PREFIX], SOURCES) == 2
    assert scope.in_scope_count(root, ["m.x_none__mutmut_"], SOURCES) == 0


def test_no_stats_file_means_mutmut_failed_before_judging(tmp_path):
    root = _mutants(tmp_path, ["m.x_other__mutmut_1"], stats=False)
    assert scope.in_scope_count(root, [PREFIX], SOURCES) is None


def test_an_empty_source_list_is_a_usage_error(tmp_path, monkeypatch):
    monkeypatch.setenv(scope.SCOPE_ENV, PREFIX)
    root = _mutants(tmp_path, ["m.x_other__mutmut_1"])
    assert scope.main(["--empty-scope", str(root), "--"]) == 2
    assert scope.main(["--empty-scope", str(root), "--", *SOURCES]) == 0


def test_a_missing_meta_for_a_target_concludes_nothing(tmp_path):
    root = _mutants(tmp_path, ["m.x_other__mutmut_1"])
    assert scope.in_scope_count(root, [PREFIX], [*SOURCES, "mcp_server/b.py"]) is None


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


def _run(bash, root, prefixes, fake):
    """Run the sandboxed script; `fake` sets the fake mutmut's rc, stats and mutants."""
    args = root.parent / "args.txt"
    env = {
        **os.environ,
        "PATH": f"{root.parent / 'bin'}{os.pathsep}{os.environ['PATH']}",
        "MUTATION_ONLY_PREFIXES": prefixes,
        "FAKE_ARGS": str(args),
        "FAKE_RC": str(fake.get("rc", 0)),
        "FAKE_STATS": fake.get("stats", "1"),
        "FAKE_MUTANTS": fake.get("mutants", ""),
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


def _gate(bash, tmp_path, prefixes, **fake):
    return _run(bash, _sandbox(tmp_path), prefixes, fake)


@pytest.mark.parametrize("bash", BASHES, ids=lambda path: f"bash={path}")
def test_a_scoped_run_names_only_the_changed_functions(bash, tmp_path):
    done, ran = _gate(bash, tmp_path, PREFIX)
    assert done.returncode == 0, done.stderr
    assert ran == [f"{PREFIX}*"]


@pytest.mark.parametrize("bash", BASHES, ids=lambda path: f"bash={path}")
def test_without_a_scope_every_mutant_runs_as_before(bash, tmp_path):
    done, ran = _gate(bash, tmp_path, "")
    assert done.returncode == 0, done.stderr
    assert ran == []


@pytest.mark.parametrize("bash", BASHES, ids=lambda path: f"bash={path}")
def test_changed_functions_without_a_mutant_have_nothing_to_judge(bash, tmp_path):
    other = '"m.x_other__mutmut_1": null'
    done, _ = _gate(bash, tmp_path, PREFIX, rc=1, mutants=other)
    assert done.returncode == 0, done.stderr
    assert "hold no mutant" in done.stdout


@pytest.mark.parametrize("bash", BASHES, ids=lambda path: f"bash={path}")
def test_a_failure_before_the_stats_file_still_fails(bash, tmp_path):
    done, _ = _gate(bash, tmp_path, PREFIX, rc=3, stats="")
    assert done.returncode == 3


@pytest.mark.parametrize("bash", BASHES, ids=lambda path: f"bash={path}")
def test_a_failure_with_mutants_in_scope_still_fails(bash, tmp_path):
    done, _ = _gate(bash, tmp_path, PREFIX, rc=3, mutants=f'"{PREFIX}1": null')
    assert done.returncode == 3


@pytest.mark.parametrize("bash", BASHES, ids=lambda path: f"bash={path}")
def test_a_failing_glob_helper_stops_the_gate_before_mutmut(bash, tmp_path):
    root = _sandbox(tmp_path)
    (root / "scripts" / "ci_mutation_scope.py").write_text(
        "raise SystemExit(5)\n", encoding="utf-8"
    )
    done, ran = _run(bash, root, PREFIX, {})
    assert done.returncode == 5
    assert ran is None


@pytest.mark.parametrize("bash", BASHES, ids=lambda path: f"bash={path}")
def test_mutmut_sees_the_isolation_of_this_platform(bash, tmp_path):
    done, _ = _gate(bash, tmp_path, PREFIX)
    assert done.returncode == 0, done.stderr
    seen = (tmp_path / "args.txt.isolation").read_text(encoding="utf-8")
    expected = scope.process_isolation(platform.system())
    assert seen == f'process_isolation = "{expected}"\n'


def test_each_measured_platform_has_its_isolation():
    assert scope.process_isolation("Linux") == "forkserver"
    assert scope.process_isolation("Darwin") == "fork"


def test_an_unmeasured_platform_stops_the_gate():
    with pytest.raises(SystemExit, match="no mutmut process isolation measured"):
        scope.process_isolation("Windows")
