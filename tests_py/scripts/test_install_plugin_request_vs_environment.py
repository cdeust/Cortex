"""An explicit request the environment contradicts is refused — issue #704.

ADR-1114 decision 7(a): a configured URL or a non-blank
``CORTEX_MEMORY_STORE_BACKEND`` decides at launch before any marker is read.
``--postgres`` and ``CORTEX_BACKEND`` were read first by the installer, so it
provisioned and saved a backend no launch opens (note 2 of the review of #1040,
first note of the review of #1043). The installer now refuses that run and
names the variable to change; a request the environment agrees with is kept.
Driven with the harness of ``test_install_plugin_no_implicit_postgres``.
"""

from __future__ import annotations

import pytest

from tests_py.scripts.test_install_plugin_marker_order import _marker_backend
from tests_py.scripts.test_install_plugin_no_implicit_postgres import _run

_URL = "postgresql://db.example/cortex"


@pytest.mark.parametrize(
    ("request_env", "args", "environment", "launch_opens"),
    [
        ({}, ("--postgres",), {"CORTEX_MEMORY_STORE_BACKEND": "sqlite"}, "sqlite"),
        (
            {"CORTEX_BACKEND": "postgres"},
            (),
            {"CORTEX_MEMORY_STORE_BACKEND": "sqlite"},
            "sqlite",
        ),
        ({}, ("--postgres",), {"CORTEX_BACKEND": "sqlite"}, "sqlite"),
        (
            {"CORTEX_BACKEND": "sqlite"},
            (),
            {"CORTEX_MEMORY_STORE_BACKEND": "auto", "DATABASE_URL": _URL},
            "postgresql",
        ),
    ],
)
def test_a_request_the_environment_contradicts_fails_before_any_setup(
    tmp_path, request_env, args, environment, launch_opens
):
    # Before the fix the request won: Setup provisioned it and the marker
    # saved it, while every launch opened the other backend.
    result, _ = _run(
        tmp_path,
        earlier_state=False,
        extra_env={**request_env, **environment},
        args=args,
    )

    assert result.returncode != 0, f"{result.stdout}\n{result.stderr}"
    assert f"every launch open {launch_opens}" in result.stderr
    assert not (tmp_path / "setup_env").exists()
    assert not (tmp_path / "home" / ".claude" / "methodology" / "backend.json").exists()


@pytest.mark.parametrize(
    ("request_env", "args", "backend"),
    [
        ({"DATABASE_URL": _URL}, ("--postgres",), "postgresql"),
        # CORTEX_BACKEND comes before a URL at launch (resolve_backend_env).
        ({"CORTEX_BACKEND": "sqlite", "DATABASE_URL": _URL}, (), "sqlite"),
    ],
)
def test_a_request_the_environment_agrees_with_is_installed(
    tmp_path, request_env, args, backend
):
    result, _ = _run(tmp_path, earlier_state=False, extra_env=request_env, args=args)

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert f"Backend: {backend}" in result.stdout + result.stderr
    assert _marker_backend(tmp_path) == backend


def test_a_request_with_nothing_deciding_in_the_environment_still_wins(tmp_path):
    # A saved SQLite marker is not the environment: the request replaces it.
    result, _ = _run(
        tmp_path,
        earlier_state=True,
        extra_env={},
        marker='{"backend": "sqlite"}',
        args=("--postgres",),
    )

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "Backend: postgresql" in result.stdout + result.stderr
    assert _marker_backend(tmp_path) == "postgresql"
