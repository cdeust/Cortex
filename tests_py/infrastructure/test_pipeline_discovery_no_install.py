"""Issue #705: discovery used by hooks must never install another product."""

import pytest

from mcp_server.infrastructure import pipeline_discovery, pipeline_installer


@pytest.mark.parametrize("stale_entry", [False, True])
def test_discovery_never_installs_missing_pipeline(tmp_path, monkeypatch, stale_entry):
    config = tmp_path / "connections.json"
    if stale_entry:
        config.write_text('{"servers":{"codebase":{"command":"/missing/pipeline"}}}')
    monkeypatch.setattr(pipeline_discovery, "MCP_CONNECTIONS_PATH", config)
    monkeypatch.setattr(pipeline_discovery, "discover_pipeline_command", lambda _: None)

    def forbidden_install():
        pytest.fail("hook discovery attempted to install the pipeline")

    monkeypatch.setattr(pipeline_installer, "install_pipeline", forbidden_install)
    assert pipeline_discovery.ensure_pipeline_connection(str(tmp_path))["action"] == (
        "no_pipeline_found"
    )
