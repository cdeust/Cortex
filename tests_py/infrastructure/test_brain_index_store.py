"""Tests for mcp_server.infrastructure.brain_index_store."""

from mcp_server.infrastructure.brain_index_store import load_brain_index


class TestLoadBrainIndex:
    def test_returns_valid_structure(self):
        bi = load_brain_index()
        assert bi is not None
        assert isinstance(bi.get("memories"), dict)
        assert isinstance(bi.get("conversations"), dict)
