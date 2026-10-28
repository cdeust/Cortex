"""First-install .pth processing before the dependency success stamp.

Source: PR792 Windows Setup failure; issue #621; Python 3.12 site.addsitedir.
The locked pywin32 312 wheel uses .pth paths and an import bootstrap. This
portable subprocess fixture exercises both mechanisms without native binaries.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"

_FIRST_INSTALL = r"""
import importlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, sys.argv[1])
import launcher_deps as deps
import launcher_site

target = Path(sys.argv[2]) / "deps"
target.mkdir()
launcher_site.isolate_deps(str(target))
assert importlib.util.find_spec("fixture_vendor") is None

def install(directory, selection):
    root = Path(directory)
    vendor = root / "vendor"
    vendor.mkdir()
    content = "VALUE = 'loaded after install'\n"
    if sys.argv[3] == "broken":
        content = "raise ImportError('fixture missing native library')\n"
    (vendor / "fixture_vendor.py").write_text(content)
    (root / "fixture_bootstrap.py").write_text(
        "import sys; sys.fixture_bootstrapped = True\n"
    )
    (root / "fixture.pth").write_text("vendor\nimport fixture_bootstrap\n")
    return True

deps._locked_set_digest = lambda *_: "fixture-set"
deps._install_locked_set = install
started = time.perf_counter()
deps._install_and_stamp(str(target), "base", (), ("fixture_vendor",), "fixture-lock")
print(json.dumps({
    "stamp": deps._stamp(str(target), "base"),
    "bootstrap": getattr(sys, "fixture_bootstrapped", False),
    "module": getattr(sys.modules.get("fixture_vendor"), "VALUE", None),
    "seconds": time.perf_counter() - started,
}))
"""


def _first_install(tmp_path: Path, mode: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-I", "-c", _FIRST_INSTALL, str(SCRIPTS), str(tmp_path), mode],
        capture_output=True,
        text=True,
        check=True,
    )


def test_first_install_processes_new_pth_before_import_and_success_stamp(tmp_path):
    result = _first_install(tmp_path, "ready")
    receipt = json.loads(result.stdout)
    assert receipt["bootstrap"] is True
    assert receipt["module"] == "loaded after install"
    assert receipt["stamp"]["lock"] == "fixture-lock"
    assert receipt["stamp"]["set"] == "fixture-set"
    assert result.stderr == ""


def test_import_failure_names_cause_on_stderr_and_does_not_stamp(tmp_path):
    result = _first_install(tmp_path, "broken")
    assert json.loads(result.stdout)["stamp"] == {}
    assert "fixture_vendor" in result.stderr
    assert "fixture missing native library" in result.stderr
    assert "fixture missing native library" not in result.stdout
