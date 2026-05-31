"""Tests for mcp_server.handlers.open_visualization — unified 3D graph launcher."""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from mcp_server.handlers import open_visualization
from mcp_server.handlers.open_visualization import _find_dev_source, handler


class TestOpenVisualizationSchema:
    def test_exports_schema_and_handler(self):
        assert open_visualization.schema is not None
        assert open_visualization.handler is not None
        assert callable(open_visualization.handler)
        assert open_visualization.schema["description"]
        assert open_visualization.schema["inputSchema"]

    def test_domain_is_optional(self):
        required = open_visualization.schema["inputSchema"].get("required", [])
        assert "domain" not in required


class TestOpenVisualizationHandler:
    """The handler now drives the full prepare-then-render pipeline:
    after launching the standalone server it polls /api/graph/progress,
    invokes /api/recompute_layout, and only then opens the browser at
    the ``?viz=force`` path. Tests stub ``_prepare_layout`` so they
    don't issue real HTTP traffic."""

    def test_returns_url(self):
        with (
            patch(
                "mcp_server.handlers.open_visualization.launch_server",
                return_value="http://localhost:3458",
            ),
            patch("mcp_server.handlers.open_visualization.open_in_browser"),
            patch(
                "mcp_server.handlers.open_visualization._prepare_layout",
                return_value={"status": "ok", "node_count": 0, "cached": True},
            ),
        ):
            result = asyncio.run(handler({}))

        assert result["url"] == "http://localhost:3458/?viz=force"
        assert "localhost" in result["message"]

    def test_default_args_none(self):
        with (
            patch(
                "mcp_server.handlers.open_visualization.launch_server",
                return_value="http://localhost:3458",
            ),
            patch("mcp_server.handlers.open_visualization.open_in_browser"),
            patch(
                "mcp_server.handlers.open_visualization._prepare_layout",
                return_value={"status": "ok", "node_count": 0, "cached": True},
            ),
        ):
            result = asyncio.run(handler(None))
        assert result["url"] == "http://localhost:3458/?viz=force"

    def test_launches_unified_server_type(self):
        mock_launch = MagicMock(return_value="http://localhost:3458")
        with (
            patch(
                "mcp_server.handlers.open_visualization.launch_server",
                mock_launch,
            ),
            patch("mcp_server.handlers.open_visualization.open_in_browser"),
            patch(
                "mcp_server.handlers.open_visualization._prepare_layout",
                return_value={"status": "ok", "node_count": 0, "cached": True},
            ),
        ):
            asyncio.run(handler({}))

        mock_launch.assert_called_once_with("unified")

    def test_opens_browser_at_tilemap_url(self):
        """When extras are present the browser opens at the tilemap URL."""
        with (
            patch(
                "mcp_server.handlers.open_visualization.launch_server",
                return_value="http://localhost:5555",
            ),
            patch(
                "mcp_server.handlers.open_visualization.open_in_browser",
            ) as mock_open,
            patch(
                "mcp_server.handlers.open_visualization._prepare_layout",
                return_value={"status": "ok", "node_count": 0, "cached": True},
            ),
        ):
            asyncio.run(handler({}))
        mock_open.assert_called_once_with("http://localhost:5555/?viz=force")

    def test_opens_browser_at_force_url_unconditionally(self):
        """Handler always opens the force-directed URL — graph build happens on
        demand via the UI's Graph button, not on launch.

        Previously a fallback path opened the legacy URL when
        ``_prepare_layout`` reported ``igraph_missing``; that branch
        was removed when the on-launch layout precomputation was
        dropped (2026-05). The handler now returns immediately after
        opening ``?viz=force`` regardless of any layout state."""
        with (
            patch(
                "mcp_server.handlers.open_visualization.launch_server",
                return_value="http://localhost:5555",
            ),
            patch(
                "mcp_server.handlers.open_visualization.open_in_browser",
            ) as mock_open,
        ):
            result = asyncio.run(handler({}))
        mock_open.assert_called_once_with("http://localhost:5555/?viz=force")
        assert "force" in result["url"]
        assert "Workflow graph" in result["message"]


class TestDevSourceSecurityHardening:
    """Falsification tests for GHSA-gvpp-v77h-5w8g — `_find_dev_source`
    must not be persuadable by attacker-controllable env vars.

    Each test would fail if a regression re-introduced
    ``CLAUDE_PROJECT_DIR`` as a candidate, or removed the explicit
    ``CORTEX_DEV_SOURCE_SYNC=1`` opt-in for ``CORTEX_DEV_ROOT``. The
    threat model is: an attacker tricks the user into opening a
    malicious project in Claude Code (which sets
    ``CLAUDE_PROJECT_DIR``); the malicious project contains the two
    marker files (``mcp_server/`` directory + ``ui/unified-viz.html``)
    that ``_is_cortex_root`` checks, plus a
    ``mcp_server/server/visualize_bootstrap.py`` containing arbitrary
    Python. When the user runs ``/cortex-visualize`` the handler used
    to ``subprocess.run`` that file, giving the attacker local ACE.
    """

    @staticmethod
    def _plant_marker_files(root: Path) -> None:
        (root / "mcp_server" / "server").mkdir(parents=True, exist_ok=True)
        (root / "ui").mkdir(parents=True, exist_ok=True)
        (root / "ui" / "unified-viz.html").write_text(
            "<html>attacker</html>", encoding="utf-8"
        )
        (root / "mcp_server" / "server" / "visualize_bootstrap.py").write_text(
            "raise RuntimeError('attacker-controlled bootstrap')\n",
            encoding="utf-8",
        )

    def test_claude_project_dir_is_ignored(self, monkeypatch):
        # Falsifies: CLAUDE_PROJECT_DIR can drive _find_dev_source.
        with tempfile.TemporaryDirectory(prefix="cortex-malicious-") as td:
            attacker_root = Path(td)
            self._plant_marker_files(attacker_root)
            # Make sure no other env var or home-fallback satisfies
            # the search — otherwise the test would be vacuous.
            monkeypatch.delenv("CORTEX_DEV_SOURCE_SYNC", raising=False)
            monkeypatch.delenv("CORTEX_DEV_ROOT", raising=False)
            monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(attacker_root))
            with patch(
                "mcp_server.handlers.open_visualization.Path.home",
                return_value=attacker_root.parent,
            ):
                # parent dir contains the malicious dir but lacks
                # ``Documents/Developments/Cortex`` so home-fallback
                # cannot accidentally satisfy.
                result = _find_dev_source()
            assert result is None, (
                f"CLAUDE_PROJECT_DIR should be ignored; got {result!r} — "
                "this would re-introduce GHSA-gvpp-v77h-5w8g."
            )

    def test_cortex_dev_root_ignored_without_opt_in(self, monkeypatch):
        # Falsifies: CORTEX_DEV_ROOT is honoured without the
        # CORTEX_DEV_SOURCE_SYNC=1 flag.
        with tempfile.TemporaryDirectory(prefix="cortex-unopted-") as td:
            attacker_root = Path(td)
            self._plant_marker_files(attacker_root)
            monkeypatch.delenv("CORTEX_DEV_SOURCE_SYNC", raising=False)
            monkeypatch.setenv("CORTEX_DEV_ROOT", str(attacker_root))
            monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
            with patch(
                "mcp_server.handlers.open_visualization.Path.home",
                return_value=attacker_root.parent,
            ):
                result = _find_dev_source()
            assert result is None, (
                f"CORTEX_DEV_ROOT honoured without the opt-in flag; got {result!r}."
            )

    def test_cortex_dev_root_honoured_when_explicitly_opted_in(self, monkeypatch):
        # Falsifies: opt-in flag is broken (legitimate dev workflow
        # would also break). This test exists so we don't over-lock
        # the door and lose the intended developer affordance.
        with tempfile.TemporaryDirectory(prefix="cortex-dev-real-") as td:
            dev_root = Path(td)
            self._plant_marker_files(dev_root)
            monkeypatch.setenv("CORTEX_DEV_SOURCE_SYNC", "1")
            monkeypatch.setenv("CORTEX_DEV_ROOT", str(dev_root))
            monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
            with patch(
                "mcp_server.handlers.open_visualization.Path.home",
                return_value=dev_root.parent,
            ):
                result = _find_dev_source()
            assert result == dev_root, (
                f"Opt-in path broken: expected {dev_root!r}, got {result!r}."
            )

    def test_opt_in_flag_value_not_1_is_rejected(self, monkeypatch):
        # Falsifies: ANY non-empty CORTEX_DEV_SOURCE_SYNC value
        # activates the gate (would let an accidental "true"/"yes"
        # in a shell rc file pull in CORTEX_DEV_ROOT).
        with tempfile.TemporaryDirectory(prefix="cortex-truthy-") as td:
            root = Path(td)
            self._plant_marker_files(root)
            monkeypatch.setenv("CORTEX_DEV_SOURCE_SYNC", "true")
            monkeypatch.setenv("CORTEX_DEV_ROOT", str(root))
            monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
            with patch(
                "mcp_server.handlers.open_visualization.Path.home",
                return_value=root.parent,
            ):
                result = _find_dev_source()
            assert result is None, (
                "Gate must require the exact string '1' to avoid "
                "ambiguous truthy values silently re-opening the hole."
            )
