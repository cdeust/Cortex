"""The documented pyright environment must be CI's (issue #253).

The type gate is zero-diagnostic, so its verdict is only meaningful if the
contributor reproducing it resolves the same dependency versions CI does. On
2026-07-29 they did not: CI installed the hash-pinned export of `uv.lock`
while `CLAUDE.md` pointed at `pyproject.toml`'s ranges, and the two landed
seven minor versions apart on `tree-sitter-language-pack` — one environment
reporting an error the other never saw.

Both sides now read `uv.lock`, and what CI installs is the `set:` its Type
Check job hands `.github/actions/uv-locked-install`. These tests reconcile
the artifacts that must agree with it — the `uv sync` line in
CONTRIBUTING.md and the pointer in CLAUDE.md — so a change to any one of
them alone fails here instead of in a contributor's terminal weeks later.

source: ADR-1092
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

CI_YML = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
CONTRIBUTING = (REPO / "CONTRIBUTING.md").read_text(encoding="utf-8")
CLAUDE_MD = (REPO / "CLAUDE.md").read_text(encoding="utf-8")

# The fenced block under the type-gate heading — anchored on the heading and
# not on `uv sync`, because CONTRIBUTING documents a second sync (dev setup)
# whose extras are deliberately different.
_TYPECHECK_SECTION = "### Reproducing the pyright gate locally"
_FENCED_BLOCK = re.compile(r"```bash\n(.*?)```", re.DOTALL)


def _ci_typecheck_set() -> str:
    """The selection flags CI's Type Check job installs into .venv."""
    job = CI_YML[CI_YML.index("name: Type Check") :]
    match = re.search(
        r"uses: ./.github/actions/uv-locked-install\n\s+with:\n\s+set: (.+)", job
    )
    assert match is not None, "Type Check no longer installs through uv-locked-install"
    return match.group(1)


def _typecheck_block() -> str:
    """The commands CONTRIBUTING gives for reproducing the gate, one line."""
    start = CONTRIBUTING.find(_TYPECHECK_SECTION)
    assert start != -1, f"CONTRIBUTING.md lost the {_TYPECHECK_SECTION!r} section"
    match = _FENCED_BLOCK.search(CONTRIBUTING, start)
    assert match is not None, "no ```bash block under the type-gate heading"
    block = match.group(1).replace("\\\n", " ")
    assert "uv sync" in block, "the type-gate block no longer resolves from uv.lock"
    return block


def _flag_values(command: str, flag: str) -> set[str]:
    return set(re.findall(rf"--{flag}\s+([A-Za-z0-9._-]+)", command))


class DocumentedTypecheckEnvTest(unittest.TestCase):
    """CONTRIBUTING's `uv sync` selects exactly what CI's Type Check selects."""

    def test_extras_match_the_ci_typecheck_set(self) -> None:
        documented = _flag_values(_typecheck_block(), "extra")
        self.assertEqual(documented, _flag_values(_ci_typecheck_set(), "extra"))

    def test_groups_match_the_ci_typecheck_set(self) -> None:
        documented = _flag_values(_typecheck_block(), "group")
        self.assertEqual(documented, _flag_values(_ci_typecheck_set(), "group"))
        self.assertEqual(documented, {"typecheck"})

    def test_default_groups_are_excluded_like_ci(self) -> None:
        """CI's sync passes --no-default-groups; a local sync that does not
        installs packages CI never had."""
        self.assertIn("--no-default-groups", _typecheck_block())
        action = (REPO / ".github/actions/uv-locked-install/action.yml").read_text()
        self.assertIn(
            "--locked --inexact --no-install-project --no-default-groups", action
        )

    def test_pyright_is_run_from_that_environment(self) -> None:
        self.assertIn(".venv/bin/python -m pyright mcp_server/", _typecheck_block())

    def test_range_resolution_is_documented_as_forbidden(self) -> None:
        """The failure mode has to be named where the command is, or the next
        contributor re-derives the env from pyproject and repeats #253."""
        self.assertIn("#253", CONTRIBUTING)
        self.assertIn("#253", CLAUDE_MD)


class CiTypecheckJobTest(unittest.TestCase):
    """CI's Type Check job installs from the lock, not from ranges."""

    def test_job_installs_the_locked_set_into_the_venv(self) -> None:
        job = CI_YML[CI_YML.index("name: Type Check") :]
        self.assertIn("environment: .venv", job[: job.index("Record the resolved")])

    def test_job_installs_the_project_without_resolving_its_ranges(self) -> None:
        self.assertIn(".venv/bin/pip install --no-deps -e .", CI_YML)

    def test_job_records_the_resolved_type_surface(self) -> None:
        """A gate whose answer depends on the environment must log it."""
        self.assertIn("Record the resolved type surface", CI_YML)
        probed = "for pkg in pyright tree-sitter tree-sitter-language-pack"
        self.assertIn(probed, CI_YML)

    def test_job_does_not_pip_install_an_extra_range(self) -> None:
        """`pip install -e ".[dev,...]"` in this workflow is what re-opens the
        divergence: it resolves from pyproject.toml instead of the lock."""
        self.assertNotIn('pip install -e ".[', CI_YML)


if __name__ == "__main__":
    unittest.main()
