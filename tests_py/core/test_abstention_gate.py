"""Tests for abstention gate (uses cortex-beam-abstain model)."""

from mcp_server.core.abstention_gate import filter_by_abstention, should_abstain


class TestAbstentionGate:
    def test_empty_candidates(self):
        result, scores = filter_by_abstention("query", [])
        assert result == []
        assert scores == []

    def test_no_op_when_model_unavailable(self, monkeypatch):
        """When model fails to load, return all candidates unchanged."""
        from mcp_server.core import abstention_gate

        monkeypatch.setattr(abstention_gate, "_classifier", None)
        monkeypatch.setattr(abstention_gate, "_load_attempted", True)

        candidates = [
            {"memory_id": 1, "content": "test"},
            {"memory_id": 2, "content": "another"},
        ]
        result, scores = filter_by_abstention("query", candidates)
        assert len(result) == 2
        assert scores == [1.0, 1.0]

    def test_keep_at_least_returns_top_n(self, monkeypatch):
        """When threshold filters everything, keep_at_least falls back to top-N."""
        from mcp_server.core import abstention_gate

        # Mock classifier that returns low scores for everything
        class MockClf:
            def predict_batch(self, pairs):
                return [0.1] * len(pairs)

        monkeypatch.setattr(abstention_gate, "_classifier", MockClf())
        monkeypatch.setattr(abstention_gate, "_load_attempted", True)

        candidates = [
            {"memory_id": 1, "content": "first"},
            {"memory_id": 2, "content": "second"},
            {"memory_id": 3, "content": "third"},
        ]
        result, scores = filter_by_abstention(
            "query", candidates, threshold=0.5, keep_at_least=1
        )
        assert len(result) == 1
        assert all(s == 0.1 for s in scores)

    def test_should_abstain_when_all_low(self, monkeypatch):
        from mcp_server.core import abstention_gate

        class MockClf:
            def predict_batch(self, pairs):
                return [0.1, 0.2, 0.3]

        monkeypatch.setattr(abstention_gate, "_classifier", MockClf())
        monkeypatch.setattr(abstention_gate, "_load_attempted", True)

        candidates = [{"memory_id": i, "content": f"c{i}"} for i in range(3)]
        assert should_abstain("query", candidates, threshold=0.5) is True

    def test_should_not_abstain_when_some_high(self, monkeypatch):
        from mcp_server.core import abstention_gate

        class MockClf:
            def predict_batch(self, pairs):
                return [0.1, 0.8, 0.3]

        monkeypatch.setattr(abstention_gate, "_classifier", MockClf())
        monkeypatch.setattr(abstention_gate, "_load_attempted", True)

        candidates = [{"memory_id": i, "content": f"c{i}"} for i in range(3)]
        assert should_abstain("query", candidates, threshold=0.5) is False
