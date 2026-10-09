"""The one place a hook builds the command line of a child Python process
(consolidation, capture worker and drainer, ingest and re-analyse workers).

Problem: ``scripts/launcher.py`` isolates ``deps/`` from user site-packages
(issue #621, ``launcher_site.isolate_deps``) and wires the composition root
(issue #560). A child started as ``python -m <module>`` runs neither, so a
user-site package (a torchvision built for another torch) shadows ``deps/``
and the embedding engine silently falls back (issue #667). Two spawn sites
each carried their own copy of the "launcher, else ``-m``" choice, and
``session_lifecycle`` carried only the ``-m`` half.

source: issue #667
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp_server.shared.platform import python_executable


def launcher_path() -> Path:
    """The ``scripts/launcher.py`` of the plugin root this process runs from.

    precondition: none. postcondition: the returned path is where the
    launcher would be; it may not exist (see ``child_command``).
    """
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT") or str(
        Path(__file__).resolve().parents[2]
    )
    return Path(plugin_root) / "scripts" / "launcher.py"


def launcher_child_command(module: str, *arguments: str) -> list[str] | None:
    """``[python, launcher, module, *arguments]``, or None without a launcher.

    For a spawn that has no meaning outside a plugin install (it needs
    ``deps/``) and is skipped there, instead of falling back to ``-m``.

    precondition: ``module`` is a dotted hook module name.
    postcondition: non-None only when ``scripts/launcher.py`` exists.

    source: issue #667, ADR-0498
    """
    launcher = launcher_path()
    if not launcher.exists():
        return None
    return [python_executable(), str(launcher), module, *arguments]


def child_command(module: str, *arguments: str) -> list[str]:
    """Command line that runs ``module`` as ``__main__`` in a child process.

    precondition: ``module`` is a dotted hook module name.
    postcondition: when the plugin ships its launcher the command is
    ``[python, launcher, module, *arguments]``, so the child gets deps
    isolation and the composition root exactly as every launcher-started
    hook does. Without a launcher (the wheel runtime of the Codex plugin,
    ``mcp_server.hooks.entry``, whose interpreter is the uvx-managed virtual
    environment with no ``deps/`` and no user site) the command is
    ``[python, "-m", module, *arguments]``; the module's own ``__main__``
    block wires the composition root there.

    source: issue #667, ADR-0498
    """
    return launcher_child_command(module, *arguments) or [
        python_executable(),
        "-m",
        module,
        *arguments,
    ]
