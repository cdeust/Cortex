"""Published dependencies must protect Codex uvx from Intel source builds.

source: ADR-1092
cryptography >=49 has no macOS Intel wheel.
source: 2026-10-02 session-end-queue/worker.log:7998-8025, arm64 host
resolving an Intel Python attempted cryptography 50.0.2 and failed.
"""

from __future__ import annotations

from pathlib import Path
import tomllib

from packaging.requirements import Requirement
import pytest


def _published_cryptography_bounds() -> list[Requirement]:
    project = Path(__file__).resolve().parents[2] / "pyproject.toml"
    metadata = tomllib.loads(project.read_text())
    return [
        requirement
        for value in metadata["project"]["dependencies"]
        if (requirement := Requirement(value)).name == "cryptography"
    ]


@pytest.mark.parametrize(
    ("system", "machine", "version", "accepted"),
    [
        ("darwin", "x86_64", "48.0.1", True),
        ("darwin", "x86_64", "49.0.0", False),
        ("darwin", "x86_64", "50.0.2", False),
        ("darwin", "arm64", "50.0.2", True),
        ("linux", "x86_64", "50.0.2", True),
        ("win32", "AMD64", "50.0.2", True),
    ],
)
def test_published_metadata_prevents_unsupported_intel_builds(
    system: str, machine: str, version: str, accepted: bool
) -> None:
    bounds = _published_cryptography_bounds()
    assert bounds, "uvx cannot see compatibility bounds in dependency groups"
    environment = {"sys_platform": system, "platform_machine": machine}
    active = [bound for bound in bounds if bound.marker.evaluate(environment)]
    assert all(bound.specifier.contains(version) for bound in active) is accepted
