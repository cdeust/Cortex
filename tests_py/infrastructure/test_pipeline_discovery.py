"""Tests for pipeline_discovery — detecting the ai-automatised-pipeline
MCP server and auto-writing mcp-connections.json.

Source: docs/program/phase-5-pool-admission-design.md (marketplace
readiness), user directive "detected and guided".
"""

from __future__ import annotations

import json
from pathlib import Path


from mcp_server.infrastructure import pipeline_discovery


def _isolate_install_symlink(monkeypatch, tmp_path):
    """Point _INSTALL_SYMLINK at a path that does not exist so tests
    don't see the user's real auto-installed binary."""
    monkeypatch.setattr(
        pipeline_discovery,
        "_INSTALL_SYMLINK",
        tmp_path / "nonexistent" / "mcp-server",
    )


class TestDiscoverCommand:
    def test_binary_on_path_found(self, tmp_path, monkeypatch):
        """shutil.which returning a hit wins over source-checkout lookup."""
        _isolate_install_symlink(monkeypatch, tmp_path)
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

    def test_no_pipeline_returns_none(self, monkeypatch, tmp_path):
        _isolate_install_symlink(monkeypatch, tmp_path)
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
        _isolate_install_symlink(monkeypatch, tmp_path)
        monkeypatch.setattr(pipeline_discovery.shutil, "which", lambda n: None)
        source = tmp_path / "ai-automatised-pipeline"
        built = source / "target/release/ai-architect-mcp"
        built.parent.mkdir(parents=True)
        built.write_text("#!/bin/sh\n")
        built.chmod(0o755)
        monkeypatch.setattr(pipeline_discovery, "_SOURCE_DIRS", (str(source),))
        cmd = pipeline_discovery.discover_pipeline_command()
        assert cmd == [str(built)]

    def test_install_symlink_wins_when_present(self, tmp_path, monkeypatch):
        """Auto-installed symlink under ~/.claude/methodology/bin/ takes
        precedence over PATH/source-checkout discovery so the user's
        last successful install is sticky."""
        symlink = tmp_path / "mcp-server"
        target = tmp_path / "ai-architect-mcp"
        target.write_text("#!/bin/sh\n")
        target.chmod(0o755)
        symlink.symlink_to(target)
        monkeypatch.setattr(pipeline_discovery, "_INSTALL_SYMLINK", symlink)
        # PATH and sources empty — should still find the symlink.
        monkeypatch.setattr(pipeline_discovery.shutil, "which", lambda n: None)
        monkeypatch.setattr(pipeline_discovery, "_SOURCE_DIRS", ())
        cmd = pipeline_discovery.discover_pipeline_command()
        assert cmd == [str(symlink)]


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
        assert (
            data["servers"]["codebase"]["command"] == "/usr/local/bin/ai-architect-mcp"
        )

    def test_no_pipeline_leaves_config_untouched(self, tmp_path, monkeypatch):
        config_path = tmp_path / "mcp-connections.json"
        monkeypatch.setattr(pipeline_discovery, "MCP_CONNECTIONS_PATH", config_path)
        monkeypatch.setattr(
            pipeline_discovery, "discover_pipeline_command", lambda: None
        )
        result = pipeline_discovery.ensure_pipeline_connection()
        assert result["action"] == "no_pipeline_found"
        assert not config_path.exists()

    def test_existing_codebase_entry_preserved(self, tmp_path, monkeypatch):
        """User already configured codebase server with a real binary
        → we leave it alone (don't overwrite custom config)."""
        config_path = tmp_path / "mcp-connections.json"
        # Use a path that actually exists and is executable so the
        # validation gate accepts it as a live config.
        real_binary = tmp_path / "user-custom-mcp"
        real_binary.write_text("#!/bin/sh\n")
        real_binary.chmod(0o755)
        original = {
            "servers": {
                "codebase": {
                    "command": str(real_binary),
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
        assert data["servers"]["codebase"]["command"] == str(real_binary)
        assert data["servers"]["codebase"]["args"] == ["--flag"]

    def test_stale_codebase_entry_purged(self, tmp_path, monkeypatch):
        """Existing codebase entry pointing at a deleted binary is
        purged so the install path can re-run instead of silently
        breaking ingest_codebase."""
        config_path = tmp_path / "mcp-connections.json"
        config_path.write_text(json.dumps({
            "servers": {
                "codebase": {"command": "/nonexistent/mcp", "args": []},
                "other": {"command": "node", "args": ["/x.js"]},
            }
        }))
        monkeypatch.setattr(pipeline_discovery, "MCP_CONNECTIONS_PATH", config_path)
        # Simulate fresh discovery finding nothing (no install attempted
        # because we monkeypatch install_pipeline import).
        monkeypatch.setattr(pipeline_discovery, "discover_pipeline_command", lambda: None)
        from mcp_server.infrastructure import pipeline_installer
        monkeypatch.setattr(
            pipeline_installer,
            "install_pipeline",
            lambda: {"action": "missing_toolchain", "missing": ["cargo"]},
        )

        result = pipeline_discovery.ensure_pipeline_connection()
        # Other servers preserved; stale codebase entry gone.
        data = json.loads(config_path.read_text())
        assert "codebase" not in data["servers"]
        assert "other" in data["servers"]
        assert result["action"] == "no_pipeline_found"

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
        assert (
            data["servers"]["codebase"]["command"] == "/usr/local/bin/ai-architect-mcp"
        )

    def test_new_entries_set_unbounded_call_timeout(self, tmp_path, monkeypatch):
        """Auto-written codebase entries must use callTimeoutMs=0
        (unbounded) so fresh-codebase indexing isn't capped at 10 min."""
        config_path = tmp_path / "mcp-connections.json"
        monkeypatch.setattr(pipeline_discovery, "MCP_CONNECTIONS_PATH", config_path)
        monkeypatch.setattr(
            pipeline_discovery,
            "discover_pipeline_command",
            lambda: ["/usr/local/bin/ai-architect-mcp"],
        )
        pipeline_discovery.ensure_pipeline_connection()
        data = json.loads(config_path.read_text())
        assert data["servers"]["codebase"]["callTimeoutMs"] == 0


class TestInstallPipeline:
    def test_disabled_via_env(self, monkeypatch):
        from mcp_server.infrastructure import pipeline_installer

        monkeypatch.setenv("CORTEX_AUTO_INSTALL_PIPELINE", "0")
        result = pipeline_installer.install_pipeline()
        assert result["action"] == "disabled"

    def test_already_installed_short_circuits(self, tmp_path, monkeypatch):
        """A usable managed-install symlink short-circuits with
        already_installed pointing at the symlink (NOT at any stale
        PATH binary)."""
        from mcp_server.infrastructure import pipeline_installer

        # Build a fake installed binary (must clear the size threshold).
        target = tmp_path / "ai-architect-mcp"
        target.write_bytes(b"\x00" * (pipeline_installer._MIN_BINARY_BYTES + 1))
        target.chmod(0o755)
        symlink = tmp_path / "mcp-server"
        symlink.symlink_to(target)
        monkeypatch.setattr(pipeline_installer, "_INSTALL_SYMLINK", symlink)
        monkeypatch.delenv("CORTEX_AUTO_INSTALL_PIPELINE", raising=False)
        # Clear all CI signals so the test machine doesn't trigger
        # the new ci_skipped short-circuit.
        for k in pipeline_installer._CI_ENV_VARS:
            monkeypatch.delenv(k, raising=False)
        result = pipeline_installer.install_pipeline()
        assert result["action"] == "already_installed"
        assert result["binary"] == str(symlink)

    def test_zero_byte_binary_not_trusted(self, tmp_path, monkeypatch):
        """A 0-byte symlink target (disk-full / interrupted build)
        must NOT count as already_installed."""
        from mcp_server.infrastructure import pipeline_installer

        target = tmp_path / "ai-architect-mcp"
        target.write_bytes(b"")  # corrupted / 0 bytes
        target.chmod(0o755)
        symlink = tmp_path / "mcp-server"
        symlink.symlink_to(target)
        monkeypatch.setattr(pipeline_installer, "_INSTALL_SYMLINK", symlink)
        for k in pipeline_installer._CI_ENV_VARS:
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("CORTEX_AUTO_INSTALL_RUST", "0")
        # No cargo on PATH and no ~/.cargo/bin — should fall through
        # to missing_toolchain rather than short-circuit.
        monkeypatch.setattr(pipeline_installer.shutil, "which", lambda n: None)
        monkeypatch.setattr(
            pipeline_installer,
            "_CARGO_HOME_BIN",
            pipeline_installer.Path("/nonexistent/.cargo/bin"),
        )
        result = pipeline_installer.install_pipeline()
        assert result["action"] == "missing_toolchain"

    def test_ci_environment_skips_install(self, monkeypatch):
        """CI default: skip the 5-8 min cold install unless explicitly
        opted in via CORTEX_AUTO_INSTALL_PIPELINE=1."""
        from mcp_server.infrastructure import pipeline_installer

        monkeypatch.setenv("CI", "true")
        monkeypatch.delenv("CORTEX_AUTO_INSTALL_PIPELINE", raising=False)
        result = pipeline_installer.install_pipeline()
        assert result["action"] == "ci_skipped"

    def test_ci_opt_in_overrides_skip(self, tmp_path, monkeypatch):
        """CORTEX_AUTO_INSTALL_PIPELINE=1 forces install even in CI."""
        from mcp_server.infrastructure import pipeline_installer

        # Place a usable binary so install short-circuits at
        # already_installed (we just need to prove we got past the
        # CI gate).
        target = tmp_path / "ai-architect-mcp"
        target.write_bytes(b"\x00" * (pipeline_installer._MIN_BINARY_BYTES + 1))
        target.chmod(0o755)
        symlink = tmp_path / "mcp-server"
        symlink.symlink_to(target)
        monkeypatch.setattr(pipeline_installer, "_INSTALL_SYMLINK", symlink)
        monkeypatch.setenv("CI", "true")
        monkeypatch.setenv("CORTEX_AUTO_INSTALL_PIPELINE", "1")
        result = pipeline_installer.install_pipeline()
        assert result["action"] == "already_installed"

    def test_missing_toolchain_returns_structured_failure(self, tmp_path, monkeypatch):
        from mcp_server.infrastructure import pipeline_installer

        monkeypatch.delenv("CORTEX_AUTO_INSTALL_PIPELINE", raising=False)
        for k in pipeline_installer._CI_ENV_VARS:
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("CORTEX_AUTO_INSTALL_RUST", "0")
        # Point _INSTALL_SYMLINK at a non-existent path so the short
        # circuit doesn't fire.
        monkeypatch.setattr(
            pipeline_installer,
            "_INSTALL_SYMLINK",
            tmp_path / "nonexistent" / "mcp-server",
        )
        from mcp_server.infrastructure import pipeline_install_rust
        monkeypatch.setattr(pipeline_installer.shutil, "which", lambda n: None)
        monkeypatch.setattr(pipeline_install_rust.shutil, "which", lambda n: None)
        monkeypatch.setattr(
            pipeline_install_rust,
            "_CARGO_HOME_BIN",
            Path("/nonexistent/.cargo/bin"),
        )
        result = pipeline_installer.install_pipeline()
        assert result["action"] == "missing_toolchain"
        assert "cargo" in result["missing"]
        assert result["rust_install_action"] == "rust_disabled"

    def test_rust_disabled_via_env(self, monkeypatch):
        from mcp_server.infrastructure import pipeline_install_rust

        monkeypatch.setenv("CORTEX_AUTO_INSTALL_RUST", "0")
        result = pipeline_install_rust.install_rust_toolchain()
        assert result["action"] == "rust_disabled"

    def test_install_lock_contended_returns_in_progress(self, tmp_path, monkeypatch):
        """Concurrent install_pipeline runs: the second caller gets
        ``install_in_progress`` immediately rather than blocking."""
        from mcp_server.infrastructure import pipeline_install_lock, pipeline_installer

        # Hold the lock for the duration of the test by acquiring it
        # in a thread that exits via an Event. Cleaner: fake the lock
        # context to always raise BlockingIOError.
        def fake_lock():
            from contextlib import contextmanager

            @contextmanager
            def busy():
                raise pipeline_install_lock.InstallLockBusy("test-busy")
                yield  # pragma: no cover

            return busy()

        monkeypatch.setattr(pipeline_installer, "install_lock", fake_lock)
        monkeypatch.setattr(
            pipeline_installer,
            "_INSTALL_SYMLINK",
            tmp_path / "nonexistent" / "mcp-server",
        )
        for k in pipeline_installer._CI_ENV_VARS:
            monkeypatch.delenv(k, raising=False)
        monkeypatch.delenv("CORTEX_AUTO_INSTALL_PIPELINE", raising=False)

        result = pipeline_installer.install_pipeline()
        assert result["action"] == "install_in_progress"

    def test_prebuilt_unsupported_platform(self, monkeypatch):
        """Unsupported os/arch returns ``prebuilt_unsupported_platform``
        (caller falls through to source build)."""
        from mcp_server.infrastructure import pipeline_install_release

        monkeypatch.delenv("CORTEX_DISABLE_PREBUILT", raising=False)
        monkeypatch.setattr(pipeline_install_release.platform, "system", lambda: "OpenBSD")
        result = pipeline_install_release.try_install_prebuilt(Path("/tmp/symlink"))
        assert result["action"] == "prebuilt_unsupported_platform"

    def test_prebuilt_disabled_via_env(self, monkeypatch):
        from mcp_server.infrastructure import pipeline_install_release

        monkeypatch.setenv("CORTEX_DISABLE_PREBUILT", "1")
        result = pipeline_install_release.try_install_prebuilt(Path("/tmp/symlink"))
        assert result["action"] == "prebuilt_disabled"

    def test_rustup_hash_manifest_parsing(self, tmp_path, monkeypatch):
        """Hash manifest: comment lines and whitespace are ignored;
        first valid 64-hex token is the pinned digest."""
        from mcp_server.infrastructure import pipeline_install_rust

        manifest = tmp_path / "rustup-init.sha256"
        good_hash = "a" * 64
        manifest.write_text(f"# comment\n\n{good_hash}\n# trailing\n")
        monkeypatch.setattr(pipeline_install_rust, "_HASH_MANIFEST", manifest)
        assert pipeline_install_rust._read_pinned_hash() == good_hash

    def test_rustup_hash_manifest_empty_returns_none(self, tmp_path, monkeypatch):
        """Comment-only manifest = pinning OFF (returns None so caller
        falls back to legacy curl|sh path)."""
        from mcp_server.infrastructure import pipeline_install_rust

        manifest = tmp_path / "rustup-init.sha256"
        manifest.write_text("# comments only\n# no digest yet\n")
        monkeypatch.setattr(pipeline_install_rust, "_HASH_MANIFEST", manifest)
        assert pipeline_install_rust._read_pinned_hash() is None

    def test_rustup_hash_manifest_rejects_short_token(self, tmp_path, monkeypatch):
        """Tokens that aren't 64-hex are rejected (no false-pin)."""
        from mcp_server.infrastructure import pipeline_install_rust

        manifest = tmp_path / "rustup-init.sha256"
        manifest.write_text("not-a-hash\n")
        monkeypatch.setattr(pipeline_install_rust, "_HASH_MANIFEST", manifest)
        assert pipeline_install_rust._read_pinned_hash() is None

    def test_install_failure_in_ensure_does_not_crash(self, tmp_path, monkeypatch):
        """When install_pipeline can't recover, ensure_pipeline_connection
        falls through to no_pipeline_found instead of raising."""
        from mcp_server.infrastructure import pipeline_installer

        config_path = tmp_path / "mcp-connections.json"
        monkeypatch.setattr(pipeline_discovery, "MCP_CONNECTIONS_PATH", config_path)
        monkeypatch.setattr(pipeline_discovery, "discover_pipeline_command", lambda: None)
        monkeypatch.setattr(
            pipeline_installer,
            "install_pipeline",
            lambda: {"action": "missing_toolchain", "missing": ["cargo", "git"]},
        )
        result = pipeline_discovery.ensure_pipeline_connection()
        assert result["action"] == "no_pipeline_found"
        assert not config_path.exists()
