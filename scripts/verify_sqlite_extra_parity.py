#!/usr/bin/env python3
"""Guard the real install path against silently dropping a [sqlite] extra
package (issue #634's root cause, generalized).

The launcher-base group and the installer set (scripts/launcher_sets.py)
are what ``ensure_deps()``/``scripts/setup.py::install_deps()`` actually
install into the set directory ``<data>/sets/<key>/``. pyproject.toml's own
[sqlite] extra is the source of truth for what the SQLite backend needs.
Issue #634 shipped because the launcher never named sqlite-vec while a CI
shortcut that always inherited [sqlite] did -- so Windows CI ran a
dependency set no real user ever received. This checks the set directory
the REAL install path (``install-plugin.sh`` -> ``scripts/setup.py``)
actually populated, against pyproject.toml directly. The caller names the
plugin DATA directory; the set directory is resolved here with the
launcher's own layout API (``launcher_layout.project_deps_dir``), so the
check never hardcodes where a set lives.

source: ADR-1092
source: ADR-1091
source: ADR-1108"""

from __future__ import annotations

import importlib.metadata
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import launcher_layout  # noqa: E402 — sibling module, resolvable only once SCRIPT_DIR is on sys.path

REPO_ROOT = SCRIPT_DIR.parent
PYPROJECT_TOML = REPO_ROOT / "pyproject.toml"

# The `sqlite = [...]` TOML array under [project.optional-dependencies]:
# captures its bracketed body across lines. Not a general TOML parser --
# This bootstrap utility also runs before the managed Python is selected.
# pyproject.toml's own [sqlite] extra is a short,
# single-key array, so a scoped regex avoids a version-gated stdlib import
# or a new third-party dependency for one list.
_SQLITE_EXTRA_RE = re.compile(r"^sqlite\s*=\s*\[(.*?)\]", re.MULTILINE | re.DOTALL)
# A PEP 508 requirement string's leading distribution name: letters, digits,
# '.', '_', '-'. Stops at the first version specifier, marker, or extra.
_NAME_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


def _normalize(name: str) -> str:
    """PEP 503 normalization: pip/uv/importlib.metadata all treat
    ``sqlite-vec`` and ``sqlite_vec`` as the same distribution name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def sqlite_extra_names(pyproject_text: str) -> list[str]:
    """Distribution names pyproject.toml's ``[sqlite]`` extra declares.

    postcondition: one entry per quoted requirement string inside the
    ``sqlite = [...]`` array, version specifiers and markers stripped.
    Empty when that array is absent or empty -- the caller decides
    whether an empty result is itself an error.
    """
    match = _SQLITE_EXTRA_RE.search(pyproject_text)
    if not match:
        return []
    names = []
    for requirement in re.findall(r'"([^"]+)"', match.group(1)):
        name_match = _NAME_RE.match(requirement.strip())
        if name_match:
            names.append(name_match.group(1))
    return names


def missing_from_deps_dir(names: list[str], deps_dir: Path) -> list[str]:
    """``names`` not resolvable as an installed distribution under ``deps_dir``.

    precondition: ``deps_dir`` is the directory the real install path
    (``ensure_deps()`` / ``scripts/setup.py::install_deps()``) writes
    into -- never a CI-shortcut requirements file's own venv.
    """
    if not deps_dir.is_dir():
        return sorted(names)
    installed = {
        _normalize(dist.metadata["Name"])
        for dist in importlib.metadata.Distribution.discover(path=[str(deps_dir)])
        if dist.metadata is not None and dist.metadata.get("Name")
    }
    return sorted(name for name in names if _normalize(name) not in installed)


def installed_set_dir(data_dir: str, project: Path = REPO_ROOT) -> Path:
    """The set directory plugin tree ``project`` installs into under ``data_dir``.

    postcondition: the directory the real install path writes for this
    tree's uv.lock key (``launcher_layout.project_deps_dir``); it may not
    exist, and ``missing_from_deps_dir`` then reports every name missing.
    """
    return Path(launcher_layout.project_deps_dir(data_dir, project))


def main(argv: list[str]) -> int:
    """Standalone entry point:
    ``python3 scripts/verify_sqlite_extra_parity.py <plugin_data_dir>``."""
    if len(argv) != 1:
        print("usage: verify_sqlite_extra_parity.py <plugin_data_dir>", file=sys.stderr)
        return 2
    deps_dir = installed_set_dir(argv[0])

    names = sqlite_extra_names(PYPROJECT_TOML.read_text(encoding="utf-8"))
    missing = missing_from_deps_dir(names, deps_dir)
    if not missing:
        print(f"OK: [sqlite] extra fully present under {deps_dir}: {names}")
        return 0

    print(
        "The real install path (install-plugin.sh -> scripts/setup.py) did "
        f"not install every package pyproject.toml's [sqlite] extra "
        f"declares. Missing under {deps_dir}: "
        + ", ".join(missing)
        + ". Add the missing package(s) to pyproject.toml's launcher-base "
        "group and to launcher_sets.INSTALLER's extras (issue #634's fix).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
