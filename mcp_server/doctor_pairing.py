"""`cortex doctor` check: is this a supported plugin/runtime pairing (#729).

The Claude plugin does not pin a runtime by version: its launcher puts the
plugin directory first on ``sys.path`` and ``PYTHONPATH``
(``scripts/launcher.py`` ``_resolve_paths`` and ``_set_import_paths``, the
directory read from ``CLAUDE_PLUGIN_ROOT``), so the code it runs is the
``mcp_server`` package of that directory. The supported pairing is therefore:

- the process imports ``mcp_server`` from ``$CLAUDE_PLUGIN_ROOT/mcp_server``;
- the plugin manifest ``.claude-plugin/plugin.json`` declares the version of
  that code (an installed wheel's version, or the source tree's
  ``pyproject.toml`` ``[project] version``).

Anything else is unsupported: a fix published in the plugin's version cannot
be attributed to the code this process runs. The Codex side is checked at
launch by ``plugins/hypermnesia-mcp-codex/scripts/runtime.py``
``installed_python`` (the installed wheel's version must equal the Codex
manifest's), so this check reads only the Claude plugin.

Without ``CLAUDE_PLUGIN_ROOT`` the process was not launched by the Claude
plugin (a checkout, the Codex runtime, a ``.mcpb``): the check says so and
passes, it does not guess a plugin directory.

source: issue #729 (acceptance: define supported plugin/runtime pairings and
diagnose unsupported combinations; remaining slice 2 of the 2026-11-06 comment)
"""

from __future__ import annotations

import json
import os
import tomllib
from importlib import metadata
from pathlib import Path
from typing import Any, Callable, Mapping

import mcp_server
from mcp_server.doctor_artifact import DISTRIBUTION, PACKAGE

NAME = "Plugin/runtime pairing"  # source: issue #729 (acceptance criterion 1)
ROOT_ENV = "CLAUDE_PLUGIN_ROOT"  # source: scripts/launcher.py _resolve_paths
MANIFEST = Path(".claude-plugin") / "plugin.json"  # source: Claude plugin layout
_REINSTALL = (
    "Update or reinstall the Claude plugin so its directory holds the code its "
    "manifest declares"
)
_RELAUNCH = (
    "Run the doctor through the plugin launcher (`python3 {plugin}/scripts/"
    "launcher.py mcp_server.doctor`), which puts the plugin directory first on "
    "the import path, or unset {env} outside the plugin"
)


def manifest_version(plugin: Path) -> str:
    """The ``version`` the Claude plugin manifest under ``plugin`` declares.

    Raises OSError when the manifest cannot be read, ValueError when it is not
    JSON or names no string version."""
    # json reads bytes as UTF-8 (RFC 8259 section 8.1), whatever the locale.
    data = json.loads((plugin / MANIFEST).read_bytes())
    version = data.get("version") if isinstance(data, dict) else None
    if not isinstance(version, str) or not version:
        raise ValueError(f"{plugin / MANIFEST} declares no version")
    return version


def runtime_version(root: Path) -> tuple[str, str]:
    """The version of the ``mcp_server`` package at ``root`` and where it was read.

    An installed distribution that locates this package gives its own version;
    otherwise the source tree's ``pyproject.toml`` does. Raises OSError or
    ValueError when neither can be read."""
    try:
        dist = metadata.distribution(DISTRIBUTION)
    except metadata.PackageNotFoundError:
        dist = None
    if dist is not None and Path(str(dist.locate_file(PACKAGE))).resolve() == root:
        return dist.version, f"installed {DISTRIBUTION}"
    pyproject = root.parent / "pyproject.toml"
    with pyproject.open("rb") as file:  # tomllib reads binary files only
        project = tomllib.load(file).get("project")
    version = project.get("version") if isinstance(project, dict) else None
    if not isinstance(version, str) or not version:
        raise ValueError(f"{pyproject} declares no [project] version")
    return version, str(pyproject)


def plugin_pairing(
    check: Callable[..., Any], environ: Mapping[str, str] = os.environ
) -> Any:
    """Say whether this process is a supported Claude plugin/runtime pairing.

    Pre-condition: ``check`` is doctor's ``Check`` constructor.
    Post-condition: an optional check; it fails when ``CLAUDE_PLUGIN_ROOT`` is
    set and the process imports ``mcp_server`` from elsewhere, when the
    manifest's version differs from the running code's, or when either cannot
    be read (the failure names it)."""
    plugin = environ.get(ROOT_ENV)
    if not plugin:
        detail = f"{ROOT_ENV} unset: not launched by the Claude plugin, no pairing"
        return check(NAME, True, detail, optional=True)
    try:
        return _pair(check, Path(plugin).resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        # A symlink loop is this check's failure, not doctor's. Up to Python 3.12
        # resolve() raises RuntimeError on one; from 3.13 only strict=True raises
        # (OSError), so the path is resolved strictly.
        detail = f"cannot read the Claude plugin pairing: {exc}"
        return check(NAME, False, detail, _REINSTALL, optional=True)


def _pair(check: Callable[..., Any], plugin: Path) -> Any:
    declared = manifest_version(plugin)
    root = Path(mcp_server.__file__).resolve().parent
    if root != (plugin / PACKAGE).resolve():
        detail = (
            f"Claude plugin {declared} at {plugin}, but this process imports "
            f"{PACKAGE} from {root}: unsupported pairing"
        )
        fix = _RELAUNCH.format(plugin=plugin, env=ROOT_ENV)
        return check(NAME, False, detail, fix, optional=True)
    version, where = runtime_version(root)
    if version != declared:
        detail = (
            f"Claude plugin manifest declares {declared}, its {PACKAGE} is "
            f"{version} ({where}): unsupported pairing"
        )
        return check(NAME, False, detail, _REINSTALL, optional=True)
    detail = f"Claude plugin {declared} runs its own {PACKAGE} {version} ({where})"
    return check(NAME, True, detail, optional=True)
