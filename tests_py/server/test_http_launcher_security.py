"""Security regression tests for mcp_server.server.http_launcher and
mcp_server.server.visualize_bootstrap.

Companion to ``tests_py/handlers/test_open_visualization.py``: the
launcher and the bootstrap script each expose a near-identical
``_find_dev_source`` / ``_detect_dev_source`` function that was also
part of the GHSA-gvpp-v77h-5w8g surface (their return values are
rsynced into the package path and the server is respawned from the
synced copy — equivalent code-execution semantics to the handler's
bootstrap call).

The bootstrap script is the more subtle case: it's invoked by the
primary handler via ``subprocess.Popen``, inheriting the parent
process environment. So even though the handler's fix blocks the
obvious entry, the bootstrap MUST consult the same hardened rules —
otherwise any future code path that invokes ``visualize_bootstrap``
(directly or via subprocess) re-opens the rsync overwrite hole.

Each test would FAIL if a regression re-introduced
``CLAUDE_PROJECT_DIR`` as a candidate, or relaxed the explicit
``CORTEX_DEV_SOURCE_SYNC=1`` opt-in gate for ``CORTEX_DEV_ROOT``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from mcp_server.server.http_launcher import _detect_dev_source
from mcp_server.server.visualize_bootstrap import (
    _find_dev_source as bootstrap_find_dev_source,
)


def _plant_marker_files(root: Path) -> None:
    """Mirror of ``TestDevSourceSecurityHardening._plant_marker_files`` —
    the same two markers ``_is_cortex_root`` checks, plus the bootstrap
    script the original PoC exploited."""
    (root / "mcp_server" / "server").mkdir(parents=True, exist_ok=True)
    (root / "ui").mkdir(parents=True, exist_ok=True)
    (root / "ui" / "unified-viz.html").write_text(
        "<html>attacker</html>", encoding="utf-8"
    )
    (root / "mcp_server" / "server" / "visualize_bootstrap.py").write_text(
        "raise RuntimeError('attacker-controlled bootstrap')\n",
        encoding="utf-8",
    )


class TestDetectDevSourceSecurityHardening:
    def test_claude_project_dir_is_ignored(self, monkeypatch):
        # Falsifies: CLAUDE_PROJECT_DIR can drive _detect_dev_source —
        # the secondary code-execution path called out in
        # GHSA-gvpp-v77h-5w8g.
        with tempfile.TemporaryDirectory(prefix="cortex-launcher-malicious-") as td:
            attacker_root = Path(td)
            _plant_marker_files(attacker_root)
            monkeypatch.delenv("CORTEX_DEV_SOURCE_SYNC", raising=False)
            monkeypatch.delenv("CORTEX_DEV_ROOT", raising=False)
            monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(attacker_root))
            with patch(
                "mcp_server.server.http_launcher.Path.home",
                return_value=attacker_root.parent,
            ):
                result = _detect_dev_source()
            # Permissible non-None result: the launcher module's own
            # ancestor walk may find a real Cortex checkout (this test
            # is run inside one). Forbidden: returning the attacker
            # root directly.
            assert result != attacker_root, (
                f"CLAUDE_PROJECT_DIR should not be honoured; got {result!r} — "
                "regression of GHSA-gvpp-v77h-5w8g."
            )

    def test_cortex_dev_root_ignored_without_opt_in(self, monkeypatch):
        # Falsifies: CORTEX_DEV_ROOT is honoured without the
        # CORTEX_DEV_SOURCE_SYNC=1 flag.
        with tempfile.TemporaryDirectory(prefix="cortex-launcher-unopted-") as td:
            attacker_root = Path(td)
            _plant_marker_files(attacker_root)
            monkeypatch.delenv("CORTEX_DEV_SOURCE_SYNC", raising=False)
            monkeypatch.setenv("CORTEX_DEV_ROOT", str(attacker_root))
            monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
            with patch(
                "mcp_server.server.http_launcher.Path.home",
                return_value=attacker_root.parent,
            ):
                result = _detect_dev_source()
            assert result != attacker_root, (
                f"CORTEX_DEV_ROOT honoured without the opt-in flag; got {result!r}."
            )

    def test_opt_in_flag_value_not_1_is_rejected(self, monkeypatch):
        # Falsifies: ANY non-empty CORTEX_DEV_SOURCE_SYNC value
        # activates the gate.
        with tempfile.TemporaryDirectory(prefix="cortex-launcher-truthy-") as td:
            root = Path(td)
            _plant_marker_files(root)
            monkeypatch.setenv("CORTEX_DEV_SOURCE_SYNC", "true")
            monkeypatch.setenv("CORTEX_DEV_ROOT", str(root))
            monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
            with patch(
                "mcp_server.server.http_launcher.Path.home",
                return_value=root.parent,
            ):
                result = _detect_dev_source()
            assert result != root, (
                "Gate must require the exact string '1' to avoid ambiguous "
                "truthy values silently re-opening the hole."
            )


class TestBootstrapFindDevSourceSecurityHardening:
    """The bootstrap script runs as a subprocess of the primary handler
    and inherits the parent's environment. Its ``_find_dev_source`` MUST
    apply the same gate — otherwise a future call site that invokes the
    bootstrap directly (or transitively) would re-introduce the rsync
    overwrite path that GHSA-gvpp-v77h-5w8g identified as a secondary
    code-execution surface.
    """

    def test_claude_project_dir_is_ignored(self, monkeypatch):
        with tempfile.TemporaryDirectory(prefix="cortex-bootstrap-malicious-") as td:
            attacker_root = Path(td)
            _plant_marker_files(attacker_root)
            monkeypatch.delenv("CORTEX_DEV_SOURCE_SYNC", raising=False)
            monkeypatch.delenv("CORTEX_DEV_ROOT", raising=False)
            monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(attacker_root))
            with patch(
                "mcp_server.server.visualize_bootstrap.Path.home",
                return_value=attacker_root.parent,
            ):
                result = bootstrap_find_dev_source()
            assert result is None, (
                f"CLAUDE_PROJECT_DIR should be ignored by bootstrap; got {result!r} — "
                "regression of GHSA-gvpp-v77h-5w8g secondary path."
            )

    def test_cortex_dev_root_ignored_without_opt_in(self, monkeypatch):
        with tempfile.TemporaryDirectory(prefix="cortex-bootstrap-unopted-") as td:
            attacker_root = Path(td)
            _plant_marker_files(attacker_root)
            monkeypatch.delenv("CORTEX_DEV_SOURCE_SYNC", raising=False)
            monkeypatch.setenv("CORTEX_DEV_ROOT", str(attacker_root))
            monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
            with patch(
                "mcp_server.server.visualize_bootstrap.Path.home",
                return_value=attacker_root.parent,
            ):
                result = bootstrap_find_dev_source()
            assert result is None, (
                f"Bootstrap honoured CORTEX_DEV_ROOT without the opt-in flag; "
                f"got {result!r}."
            )

    def test_cortex_dev_root_honoured_when_opted_in(self, monkeypatch):
        with tempfile.TemporaryDirectory(prefix="cortex-bootstrap-legit-") as td:
            dev_root = Path(td)
            _plant_marker_files(dev_root)
            monkeypatch.setenv("CORTEX_DEV_SOURCE_SYNC", "1")
            monkeypatch.setenv("CORTEX_DEV_ROOT", str(dev_root))
            monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
            with patch(
                "mcp_server.server.visualize_bootstrap.Path.home",
                return_value=dev_root.parent,
            ):
                result = bootstrap_find_dev_source()
            assert result == dev_root, (
                f"Bootstrap legitimate dev workflow broken: expected {dev_root!r}, "
                f"got {result!r}."
            )
