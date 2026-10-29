"""Run the real ``scripts/launcher.py`` for a test, with its base set reported ready.

A hook installs nothing (ADR-1108): ``launcher.py <hook>`` exits 1 unless the
plugin's ``deps/`` carries a stamp for this uv.lock and Python. A test that
drives a hook through the launcher is about the hook, not about what the
machine running it has installed (the test interpreter already has the
packages), so it starts the launcher through this driver: the real
``launcher.py`` run as ``__main__``, with the one readiness question answered.

source: ADR-1108
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

READY_DRIVER = (
    "import runpy, sys\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "import launcher_deps\n"
    "launcher_deps.ensure_deps = launcher_deps.ensure_all_deps = lambda d: None\n"
    "launcher_deps.set_ready = lambda d, kind: True\n"
    "sys.argv = sys.argv[2:]\n"
    "runpy.run_path(sys.argv[0], run_name='__main__')\n"
)


def ready_launcher_argv(launcher: Path, *arguments: str) -> list[str]:
    """``python launcher.py <arguments>`` with the base set reported installed."""
    return [
        sys.executable,
        "-c",
        READY_DRIVER,
        str(launcher.parent),
        str(launcher),
        *arguments,
    ]


def ready_plugin_env(tmp_path: Path) -> dict[str, str]:
    """``CLAUDE_PLUGIN_ROOT`` (this tree) and a ``CLAUDE_PLUGIN_DATA`` whose base
    set is stamped installed for it.

    A hook started through the patched driver above may itself spawn the real
    launcher (``post_tool_capture`` starts its capture worker that way, issue
    #667). That child sees no patch: without a ready set it refuses and starts
    the detached ``--install-base-job``, and without ``CLAUDE_PLUGIN_DATA`` the
    launcher uses the checkout as its data directory, so the job installed uv
    and ``sets/`` into the repository and outlived the test (measured
    2026-10-20). A data directory stamped the way a successful install stamps
    it makes the child as ready as the parent, as in a real plugin install.
    """
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        import launcher_deps  # noqa: PLC0415 — a script module, importable only from scripts/
        import launcher_layout  # noqa: PLC0415 — idem
    finally:
        sys.path.remove(str(REPO_ROOT / "scripts"))
    data = tmp_path / "plugin-data"
    key = launcher_deps.lock_key() or launcher_layout.NO_LOCK
    deps = Path(launcher_layout.deps_dir(data, key))
    deps.mkdir(parents=True, exist_ok=True)
    launcher_deps._write_stamp(str(deps), "base", key, "test")
    return {"CLAUDE_PLUGIN_ROOT": str(REPO_ROOT), "CLAUDE_PLUGIN_DATA": str(data)}
