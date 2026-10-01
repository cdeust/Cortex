"""scripts/setup.py's dependency install must come from uv.lock — issue #538.

Prior state: ``install_deps()`` built its own ``packages = ["mcp>=2.0.0",
...]`` list of loose version ranges and passed it straight to ``pip
install --target``. No pin, no hash, no reference to uv.lock. It now hands
the deps directory to ``scripts/launcher_deps.py``, which exports the
installer set from uv.lock and installs it, hash-checked, through scratch;
a failure stops the setup instead of printing a warning and carrying on.

source: ADR-1063
source: ADR-1092"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
SETUP_MODULE_PATH = SCRIPTS_DIR / "setup.py"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
import launcher_sets  # noqa: E402


def _load_setup_module():
    """Import scripts/setup.py fresh, dotted to match mutmut's path-derived
    trampoline name (issue #262) — see test_setup_py_backend_skip.py.
    """
    spec = importlib.util.spec_from_file_location("scripts.setup", SETUP_MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_install_deps_hands_only_the_deps_dir_to_the_launcher():
    mod = _load_setup_module()
    fake_run = mock.Mock(return_value=mock.Mock(returncode=0, stderr=""))
    with mock.patch.object(mod, "run", fake_run):
        mod.install_deps()
    (argv,), _kwargs = fake_run.call_args
    assert argv == [
        sys.executable,
        str(SCRIPTS_DIR / "launcher_deps.py"),
        mod.DEPS_DIR,
    ]


def test_install_deps_failure_stops_the_setup_with_the_cause(capsys):
    mod = _load_setup_module()
    failed = mock.Mock(returncode=1, stderr="could not install uv 0.11.3 from PyPI")
    with mock.patch.object(mod, "run", mock.Mock(return_value=failed)):
        with pytest.raises(SystemExit) as stopped:
            mod.install_deps()
    assert stopped.value.code == 1
    assert "could not install uv 0.11.3 from PyPI" in capsys.readouterr().out


def test_installer_set_keeps_the_extras_setup_txt_carried():
    """postgresql + sqlite (ADR-1089) + codebase + benchmarks (datasets)."""
    assert launcher_sets.INSTALLER == (
        "--extra",
        "postgresql",
        "--extra",
        "sqlite",
        "--extra",
        "codebase",
        "--extra",
        "benchmarks",
    )
