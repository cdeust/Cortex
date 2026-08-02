"""Tests for the constraints-file extras strip in scripts/launcher_deps_install.py.

Source: measured 2026-08-02 on macOS, Python 3.14.4 / pip 26.0.1. A plugin
install of the ML stack aborted with ``ERROR: Constraints cannot have
extras``. ``launcher_deps.ensure_all_deps`` passes ``BASE_PACKAGES``
verbatim as the ``-c`` constraints file, and one of its entries carries an
extra (``psycopg[binary]==3.3.4``). pip has always documented constraints
files as version-only; it now rejects extras outright. Reproduced the same
day on pip 25.2 / Python 3.13, so this is not a pip-26-only regression.

The damage was silent: only the ML install passes constraints, so the base
stack installed fine while sentence-transformers and flashrank never landed
— leaving recall on first-stage scores with no failed check to notice, the
same failure shape as the 2026-07-10 FlashRank incident.

The first test is the regression proper: it asserts the bytes written to the
constraints file, which is what pip actually parses. The last is the
end-to-end guard against the real pin list drifting back into a spec pip
rejects.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"


def _load(module_name: str):
    """Import a launcher module by path — they live outside the package."""
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location(
        module_name, SCRIPTS_DIR / f"{module_name}.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


install = _load("launcher_deps_install")
pins = _load("launcher_pins")


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("psycopg[binary]==3.3.4", "psycopg==3.3.4"),
        ("pkg[a,b]==1.0", "pkg==1.0"),
        ("pkg[extra]>=1.0,<2.0", "pkg>=1.0,<2.0"),
        # No extras clause — must pass through byte-identical.
        ("numpy==2.5.1", "numpy==2.5.1"),
        ("pgvector==0.5.0", "pgvector==0.5.0"),
        # Unbalanced bracket: not ours to rewrite, hand it to pip untouched
        # so pip's own error names the malformed spec.
        ("pkg[broken==1.0", "pkg[broken==1.0"),
    ],
)
def test_constraint_without_extras(spec: str, expected: str) -> None:
    assert install.constraint_without_extras(spec) == expected


def test_written_constraints_file_carries_no_extras(monkeypatch, tmp_path) -> None:
    """The regression: assert the file pip parses, not just the helper.

    A correct helper wired in at the wrong place would still ship the bug.
    """
    written: dict[str, str] = {}
    real_open = open

    def spy_open(path, mode="r", *args, **kwargs):
        handle = real_open(path, mode, *args, **kwargs)
        if "w" in mode and str(path).endswith(".txt"):

            class _Spy:
                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    handle.close()
                    return False

                def write(self, data):
                    written[str(path)] = written.get(str(path), "") + data
                    return handle.write(data)

            return _Spy()
        return handle

    monkeypatch.setattr("builtins.open", spy_open)

    class _PipReachedError(Exception):
        """Raised in place of spawning pip — the file is written by then."""

    def no_pip(*_args, **_kwargs):
        raise _PipReachedError

    monkeypatch.setattr(install.subprocess, "run", no_pip)

    deps_dir = str(tmp_path / "deps")
    with pytest.raises(_PipReachedError):
        install.pip_install(
            deps_dir, ["flashrank==0.2.10"], constraints=["psycopg[binary]==3.3.4"]
        )

    assert written, "no constraints file was written"
    body = next(iter(written.values()))
    assert "[binary]" not in body
    assert "psycopg==3.3.4" in body


def test_real_base_pins_survive_the_strip() -> None:
    """Guard the actual pin list, so a future extra can't reintroduce this."""
    stripped = [
        install.constraint_without_extras(spec) for _name, spec in pins.BASE_PACKAGES
    ]
    assert not any("[" in spec for spec in stripped)
    # The strip must not silently drop a pin or its version.
    assert len(stripped) == len(pins.BASE_PACKAGES)
    assert all("==" in spec for spec in stripped)
