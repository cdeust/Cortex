"""uv.lock is the only dependency source, and every install verifies it.

Three invariants the removal of requirements/*.txt rests on: every registry
artifact in uv.lock carries a sha256 (``uv sync`` verifies hashes the lock
has but does not require them), every pinned uv is the one version the
launcher bootstraps, and no dependency file other than uv.lock remains for
Dependabot to patch by hand.

source: ADR-1092"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:  # pytest itself depends on tomli below 3.11
    import tomli as tomllib

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import launcher_sets  # noqa: E402
import launcher_uv  # noqa: E402

LOCK = tomllib.loads((REPO / "uv.lock").read_text(encoding="utf-8"))
PYPROJECT = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
UV_PINS = (
    ".github/actions/uv-locked-install/action.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/release.yml",
)
UV_IMAGES = (
    "Dockerfile",
    "docker/Dockerfile",
    ".devcontainer/Dockerfile",
    ".clusterfuzzlite/Dockerfile",
)


def _registry_packages() -> list[dict]:
    return [p for p in LOCK["package"] if "registry" in p.get("source", {})]


def test_every_registry_artifact_in_the_lock_carries_a_sha256() -> None:
    unhashed = [
        f"{package['name']}=={package['version']}: {artifact.get('url')}"
        for package in _registry_packages()
        for artifact in [package.get("sdist", {}), *package.get("wheels", [])]
        if artifact and not str(artifact.get("hash", "")).startswith("sha256:")
    ]
    assert len(_registry_packages()) > 100
    assert unhashed == []


@pytest.mark.parametrize("path", UV_PINS)
def test_ci_installs_the_uv_the_launcher_bootstraps(path: str) -> None:
    text = (REPO / path).read_text(encoding="utf-8")
    pins = re.findall(r'^\s*version:\s*"([^"]+)"', text, re.MULTILINE)
    uses = len(re.findall(r"astral-sh/setup-uv@", text))
    assert len(pins) == uses
    assert set(pins) <= {launcher_uv.UV_VERSION}


@pytest.mark.parametrize("path", UV_IMAGES)
def test_images_copy_the_uv_the_launcher_bootstraps(path: str) -> None:
    text = (REPO / path).read_text(encoding="utf-8")
    tags = re.findall(r"COPY --from=ghcr\.io/astral-sh/uv:([^@\s]+)@sha256:", text)
    assert tags == [launcher_uv.UV_VERSION]


def _group(name: str) -> list[str]:
    return PYPROJECT["dependency-groups"][name]


def _import_name(requirement: str) -> str:
    return re.split(r"[\[<>=;! ]", requirement, maxsplit=1)[0].replace("-", "_")


def test_launcher_import_checks_match_the_launcher_groups() -> None:
    base = [_import_name(r) for r in _group("launcher-base")]
    ml = [_import_name(r) for r in _group("launcher-ml")]
    assert tuple(base) == launcher_sets.BASE_IMPORTS
    assert set(launcher_sets.ML_IMPORTS) <= set(ml)
    assert launcher_sets.BASE == ("--only-group", "launcher-base")
    assert launcher_sets.ML == ("--only-group", "launcher-ml")


def test_launcher_groups_pin_nothing_themselves() -> None:
    """A version in pyproject's group would be a second source next to the lock."""
    for name in ("launcher-base", "launcher-ml"):
        assert all(not re.search(r"[<>=~]", r) for r in _group(name)), name


def test_no_dependency_file_but_the_lock_is_left_for_dependabot() -> None:
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    shallow = [p for p in tracked if p.count("/") <= 1 and p.endswith((".txt", ".in"))]
    assert shallow == []
    dependabot = (REPO / ".github/dependabot.yml").read_text(encoding="utf-8")
    assert 'package-ecosystem: "uv"' in dependabot
    assert 'package-ecosystem: "pip"' not in dependabot
