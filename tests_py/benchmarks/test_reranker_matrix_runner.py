"""Actual shell invocation with fake uv/docker; exits before any heavy work."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
from mcp_server.shared.platform import resolve_bash

# A bare "bash" on Windows is the System32 WSL stub. source: ADR-1101
BASH = resolve_bash()


def run_driver(tmp_path: Path, flags: list[str]):
    binaries = tmp_path / "bin"
    binaries.mkdir()
    for name in ("uv", "docker"):
        script = binaries / name
        script.write_text(
            '#!/bin/sh\n/usr/bin/touch "$W4_' + name.upper() + '_MARKER"\nexit 1\n'
        )
        script.chmod(0o755)
    environment = dict(
        os.environ,
        PATH=str(binaries) + os.pathsep + os.environ["PATH"],
        W4_UV_MARKER=str(tmp_path / "uv-called"),
        W4_DOCKER_MARKER=str(tmp_path / "docker-called"),
    )
    return subprocess.run(
        [BASH, "benchmarks/reproduce.sh", *flags],
        env=environment,
        capture_output=True,
        text=True,
    )


def test_cell_cache_failure_precedes_docker_and_results_directory(tmp_path):
    output = tmp_path / "result"
    result = run_driver(
        tmp_path,
        ["--no-ablation", "--reranker-cell", "l2-2x", "--results-dir", str(output)],
    )
    assert result.returncode != 0
    assert (tmp_path / "uv-called").exists()
    assert not (tmp_path / "docker-called").exists()
    assert not output.exists()


def test_default_path_does_not_preflight_an_experimental_model(tmp_path):
    result = run_driver(tmp_path, ["--no-ablation"])
    assert result.returncode != 0
    assert not (tmp_path / "uv-called").exists()
    assert (tmp_path / "docker-called").exists()


def test_cell_requires_explicit_no_ablation_before_uv_or_docker(tmp_path):
    result = run_driver(tmp_path, ["--reranker-cell", "l2-2x"])
    assert result.returncode != 0
    assert "requires --no-ablation" in result.stderr
    assert not (tmp_path / "uv-called").exists()
    assert not (tmp_path / "docker-called").exists()
