"""Tests for pipeline_discovery — detecting the ai-automatised-pipeline
MCP server and auto-writing mcp-connections.json.

Source: docs/program/phase-5-pool-admission-design.md (marketplace
readiness), user directive "detected and guided".
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from mcp_server.infrastructure import pipeline_discovery


class TestDiscoverCommand:
    def test_binary_on_path_found(self, tmp_path, monkeypatch):
        """shutil.which returning a hit wins over source-checkout lookup."""
        fake_binary = tmp_path / "cortex-pipeline"
        fake_binary.write_text("#!/bin/sh\n")
        fake_binary.chmod(0o755)
        monkeypatch.setattr(
            pipeline_discovery.shutil,
            "which",
            lambda name: str(fake_binary) if name == "cortex-pipeline" else None,
        )
        cmd = pipeline_discovery.discover_pipeline_command()
        assert cmd == [str(fake_binary)]

    def test_no_pipeline_returns_none(self, monkeypatch):
        monkeypatch.setattr(pipeline_discovery.shutil, "which", lambda n: None)
        # No sibling checkouts exist at /nonexistent.
        monkeypatch.setattr(
            pipeline_discovery,
            "_SOURCE_DIRS",
            ("/nonexistent/ai-automatised-pipeline",),
        )
        assert pipeline_discovery.discover_pipeline_command() is None

    def test_source_checkout_with_built_binary(self, tmp_path, monkeypatch):
        """Sibling git checkout wins when PATH has nothing."""
        monkeypatch.setattr(pipeline_discovery.shutil, "which", lambda n: None)
        source = tmp_path / "ai-automatised-pipeline"
        built = source / "target/release/ai-architect-mcp"
        built.parent.mkdir(parents=True)
        built.write_text("#!/bin/sh\n")
        built.chmod(0o755)
        monkeypatch.setattr(
            pipeline_discovery, "_SOURCE_DIRS", (str(source),)
        )
        cmd = pipeline_discovery.discover_pipeline_command()
        assert cmd == [str(built)]


class TestEnsureConnection:
    def test_writes_new_config(self, tmp_path, monkeypatch):
        """Fresh machine — no config file — auto-write."""
        config_path = tmp_path / "mcp-connections.json"
        monkeypatch.setattr(pipeline_discovery, "MCP_CONNECTIONS_PATH", config_path)
        monkeypatch.setattr(
            pipeline_discovery,
            "discover_pipeline_command",
            lambda: ["/usr/local/bin/ai-architect-mcp"],
        )

        result = pipeline_discovery.ensure_pipeline_connection()
        assert result["action"] == "wrote_config"
        assert config_path.exists()
        data = json.loads(config_path.read_text())
        assert data["servers"]["codebase"]["command"] == "/usr/local/bin/ai-architect-mcp"

    def test_no_pipeline_leaves_config_untouched(self, tmp_path, monkeypatch):
        config_path = tmp_path / "mcp-connections.json"
        monkeypatch.setattr(pipeline_discovery, "MCP_CONNECTIONS_PATH", config_path)
        monkeypatch.setattr(pipeline_discovery, "discover_pipeline_command", lambda: None)
        result = pipeline_discovery.ensure_pipeline_connection()
        assert result["action"] == "no_pipeline_found"
        assert not config_path.exists()

    def test_existing_codebase_entry_preserved(self, tmp_path, monkeypatch):
        """User already configured codebase server → we leave it alone."""
        config_path = tmp_path / "mcp-connections.json"
        original = {
            "servers": {
                "codebase": {
                    "command": "/user/custom/path/mcp",
                    "args": ["--flag"],
                    "env": {"FOO": "bar"},
                }
            }
        }
        config_path.write_text(json.dumps(original))
        monkeypatch.setattr(pipeline_discovery, "MCP_CONNECTIONS_PATH", config_path)
        monkeypatch.setattr(
            pipeline_discovery,
            "discover_pipeline_command",
            lambda: ["/usr/local/bin/ai-architect-mcp"],  # would overwrite
        )

        result = pipeline_discovery.ensure_pipeline_connection()
        assert result["action"] == "already_configured"
        # Verify file unchanged.
        data = json.loads(config_path.read_text())
        assert data["servers"]["codebase"]["command"] == "/user/custom/path/mcp"
        assert data["servers"]["codebase"]["args"] == ["--flag"]

    def test_adds_codebase_to_existing_config(self, tmp_path, monkeypatch):
        """Config has other servers but no codebase entry → add it."""
        config_path = tmp_path / "mcp-connections.json"
        original = {
            "servers": {
                "prd-gen": {
                    "command": "node",
                    "args": ["/path/to/prd.js"],
                    "env": {},
                }
            }
        }
        config_path.write_text(json.dumps(original))
        monkeypatch.setattr(pipeline_discovery, "MCP_CONNECTIONS_PATH", config_path)
        monkeypatch.setattr(
            pipeline_discovery,
            "discover_pipeline_command",
            lambda: ["/usr/local/bin/ai-architect-mcp"],
        )

        result = pipeline_discovery.ensure_pipeline_connection()
        assert result["action"] == "added_codebase"
        data = json.loads(config_path.read_text())
        # Both entries preserved
        assert "prd-gen" in data["servers"]
        assert data["servers"]["codebase"]["command"] == "/usr/local/bin/ai-architect-mcp"
