"""Shared loader for scripts/launcher_site.py — issue #621.

The module under test is a script, not an installed package, so both
test modules that drive it load it the same way. Kept here rather than
duplicated so the dotted name stays identical in both: mutmut keys mutant
trampolines on the path-derived name, and a synthetic one makes every
mutant look unreached (issue #262).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "launcher_site.py"


def load_launcher_site():
    """A freshly executed scripts/launcher_site.py module object."""
    spec = importlib.util.spec_from_file_location("scripts.launcher_site", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def launcher_site():
    return load_launcher_site()
