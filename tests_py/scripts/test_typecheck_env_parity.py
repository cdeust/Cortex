"""Keep CI and documented local diagnostics on the locked dependency surface.

Issue #253: resolving pyproject ranges instead of uv.lock produced a phantom
local type error. The shared pipeline now reads ci.json and has no pyright job;
these checks preserve lock/interpreter parity without restoring that old gate.
The managed interpreter and pip bootstrap reproduce PR #789's unit environment.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CI = json.loads((REPO / "ci.json").read_text(encoding="utf-8"))
UNIT_SCRIPT = (REPO / "scripts" / "ci_unit.sh").read_text(encoding="utf-8")
PIPELINE = (REPO / ".github/workflows/pipeline.yml").read_text(encoding="utf-8")
CONTRIBUTING = (REPO / "CONTRIBUTING.md").read_text(encoding="utf-8")
CLAUDE_MD = (REPO / "CLAUDE.md").read_text(encoding="utf-8")

_TYPECHECK_SECTION = "### Running pyright locally"
_FENCED_BLOCK = re.compile(r"```bash\n(.*?)```", re.DOTALL)


def _typecheck_block() -> str:
    """The standalone local diagnostic's commands, with continuations joined."""
    start = CONTRIBUTING.find(_TYPECHECK_SECTION)
    assert start != -1, f"CONTRIBUTING.md lost the {_TYPECHECK_SECTION!r} section"
    match = _FENCED_BLOCK.search(CONTRIBUTING, start)
    assert match is not None, "no bash block under the local typecheck heading"
    return match.group(1).replace("\\\n", " ")


def _flag_values(command: str, flag: str) -> set[str]:
    return set(re.findall(rf"--{flag}\s+([A-Za-z0-9._-]+)", command))


def _sync_command(command: str) -> str:
    match = re.search(r"\buv sync\b([^\n&;]*)", command)
    assert match is not None, "the environment must resolve through uv sync"
    return match.group(0)


class DocumentedTypecheckEnvTest(unittest.TestCase):
    """Local diagnostics extend the same locked base used by the test jobs."""

    def test_local_extras_cover_ci_and_optional_type_surface(self) -> None:
        documented = _flag_values(_typecheck_block(), "extra")
        for category in ("unit", "regression"):
            with self.subTest(category=category):
                base = _flag_values(_sync_command(CI[category]), "extra")
                self.assertEqual(documented, base | {"postgresql", "otel"})

    def test_local_typecheck_group_is_explicit_and_isolated(self) -> None:
        command = _sync_command(_typecheck_block())
        self.assertEqual(_flag_values(command, "group"), {"typecheck"})
        self.assertIn("--no-default-groups", command)
        self.assertIn("--locked", command)

    def test_documented_python_matches_the_managed_ci_interpreter(self) -> None:
        block = _typecheck_block()
        self.assertIn("--managed-python", _sync_command(block))
        for category in ("unit", "regression"):
            with self.subTest(category=category):
                versions = _flag_values(_sync_command(CI[category]), "python")
                self.assertEqual(_flag_values(_sync_command(block), "python"), versions)
                for version in versions:
                    self.assertIn(f"uv python install {version}", block)

    def test_pyright_runs_without_resolving_the_environment_again(self) -> None:
        self.assertIn(
            "uv run --no-sync python -m pyright mcp_server/", _typecheck_block()
        )

    def test_docs_preserve_lock_guidance_without_claiming_a_type_gate(self) -> None:
        self.assertIn("#253", CONTRIBUTING)
        self.assertIn("#253", CLAUDE_MD)
        self.assertIn("uv sync --locked", CLAUDE_MD)
        self.assertIn("Optional local type diagnostics", CLAUDE_MD)
        self.assertIn("not a CI gate", CONTRIBUTING)
        self.assertNotIn("Reproducing the pyright gate", CONTRIBUTING + CLAUDE_MD)


class CiPythonEnvironmentTest(unittest.TestCase):
    """Guard the actual ci.json commands against the unit bootstrap regression."""

    def test_test_jobs_share_the_locked_dependency_selection(self) -> None:
        unit = _sync_command(CI["unit"])
        regression = _sync_command(CI["regression"])
        self.assertEqual(unit.strip(), regression.strip() + " --extra postgresql")
        self.assertIn("--locked", unit)
        self.assertEqual(
            _flag_values(unit, "extra"), {"dev", "sqlite", "codebase", "postgresql"}
        )
        self.assertNotIn("--group typecheck", unit)

    def test_test_jobs_bootstrap_managed_python_then_pip_before_pytest(self) -> None:
        for category in ("unit", "regression"):
            with self.subTest(category=category):
                command = CI[category]
                sync = _sync_command(command)
                self.assertIn("--managed-python", sync)
                # source: PR #789 restores the CPython 3.12 CI environment.
                self.assertEqual(_flag_values(sync, "python"), {"3.12"})
                stages = (
                    "uv python install 3.12",
                    sync,
                    "uv pip install pip",
                    "uv run --no-sync bash scripts/ci_unit.sh"
                    if category == "unit"
                    else "uv run --no-sync pytest",
                )
                positions = [command.index(stage) for stage in stages]
                self.assertEqual(positions, sorted(positions))

    def test_test_jobs_use_isolated_offline_backend_settings(self) -> None:
        self.assertIn("CORTEX_MEMORY_STORE_BACKEND=postgresql", UNIT_SCRIPT)
        self.assertIn('export CORTEX_TEST_DATABASE_URL="$DATABASE_URL"', UNIT_SCRIPT)
        self.assertIn("CORTEX_MEMORY_STORE_BACKEND=sqlite", CI["regression"])
        for category in ("unit", "regression"):
            with self.subTest(category=category):
                self.assertIn("CORTEX_RERANKER_OFFLINE=1", CI[category])

    def test_pipeline_executes_the_repository_test_commands(self) -> None:
        for category in ("unit", "regression"):
            with self.subTest(category=category):
                job = re.search(
                    rf"^  {category}:\n(.*?)(?=^  [\w-]+:|\Z)",
                    PIPELINE,
                    re.MULTILINE | re.DOTALL,
                )
                self.assertIsNotNone(job)
                self.assertIn(f"needs.contract.outputs.{category}", job.group(1))
                self.assertIn('bash -eo pipefail -c "$CI_COMMAND"', job.group(1))

    def test_unit_produces_coverage_and_regression_selects_integration(self) -> None:
        self.assertIn("--cov=mcp_server", UNIT_SCRIPT)
        self.assertIn("--cov-report=xml", UNIT_SCRIPT)
        self.assertIn("tests_py/integration", CI["regression"])


if __name__ == "__main__":
    unittest.main()
