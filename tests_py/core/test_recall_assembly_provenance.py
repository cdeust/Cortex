"""Real stage assembly over a deterministic retrieval/store boundary.

source: ADR-0217
Adjacent context serves domain-scoped supersession heads.
Only initial search is replaced; graph traversal, filtering and rendering run.
"""

from mcp_server.core import pg_recall
from mcp_server.core.pg_recall_assembly import assemble_context
from mcp_server.core.context_assembly.stage_detector import ExplicitStageDetector


class _GraphStore:
    def __init__(self):
        self.rows = {
            1: {
                "id": 1,
                "content": "Storage owns current writes",
                "plan_id": "current",
                "domain": "cortex",
            },
            2: {
                "id": 2,
                "content": "Storage connects Queue with verified provenance",
                "plan_id": "previous",
                "domain": "cortex",
            },
            3: {
                "id": 3,
                "content": "Queue PRIVATE other domain",
                "plan_id": "previous",
                "domain": "other",
            },
        }
        self.graph_reads = []
        self.mentions = []

    def get_all_entities(self):
        self.graph_reads.append("entities")
        return [
            {"id": 10, "name": "Storage"},
            {"id": 20, "name": "Queue"},
            {"id": 30, "name": ""},
        ]

    def get_all_relationships(self):
        self.graph_reads.append("relationships")
        return [
            {"source_entity_id": 10, "target_entity_id": 20, "strength": 1.0},
            {"source_entity_id": 20, "target_entity_id": 30, "strength": 1.0},
        ]

    def get_memories_by_ids(self, ids):
        return {mid: self.rows[mid] for mid in ids if mid in self.rows}

    def get_memories_mentioning_entity(self, name, *, limit, heads_only):
        self.mentions.append((name, limit, heads_only))
        assert heads_only, "context must never serve superseded memory bodies"
        # Both linked entities return the same head: output must deduplicate it.
        return [*self.rows.values(), {"content": "invalid row without identity"}]


def test_adjacent_context_is_deduplicated_domain_scoped_and_from_heads(monkeypatch):
    store = _GraphStore()
    candidates = [
        {"memory_id": 999, "content": "deleted row", "score": 1.0},
        {"memory_id": 2, "content": store.rows[2]["content"], "score": 0.9},
        {"memory_id": 1, "content": store.rows[1]["content"], "score": 0.8},
    ]
    calls = []

    def retrieve(**kwargs):
        calls.append(kwargs)
        return candidates

    monkeypatch.setattr(pg_recall, "recall", retrieve)
    result = assemble_context(
        "Storage writes",
        store,
        None,
        current_stage="current",
        domain="cortex",
        max_chunks_per_phase=2,
    )
    assert [
        (item["memory_id"], item["phase"]) for item in result["selected_memories"]
    ] == [(1, 1), (2, 2)]
    assert result["own_stage_context"] == store.rows[1]["content"]
    assert result["adjacent_stage_context"] == store.rows[2]["content"]
    assert "PRIVATE" not in result["assembled_context"]
    assert "deleted row" not in result["assembled_context"]
    assert result["metadata"]["adjacent_stages"] == ["previous"]
    assert store.graph_reads == ["entities", "relationships"]
    assert {name for name, _, _ in store.mentions} == {"Storage", "Queue"}
    assert all(heads for _, _, heads in store.mentions)
    assert len(calls) == 1
    assert calls[0]["domain"] == "cortex"
    assert calls[0]["include_globals"] is False
    assert all("entity_ids" not in candidate for candidate in candidates)


def test_custom_stage_detector_keeps_unknown_stage_summary_empty(monkeypatch):
    class Detector(ExplicitStageDetector):
        def all_stages(self, corpus):
            return ["current", "unobserved"]

    store = _GraphStore()
    monkeypatch.setattr(
        pg_recall,
        "recall",
        lambda **kwargs: [
            {"memory_id": 1, "content": store.rows[1]["content"], "score": 1.0}
        ],
    )
    result = assemble_context(
        "Storage",
        store,
        None,
        current_stage="current",
        domain="cortex",
        stage_detector=Detector(),
        token_budget=200,
    )
    assert result["stage_summaries"] == ""
    assert result["metadata"]["summary_stages"] == []
    assert "unobserved" not in result["assembled_context"]
    assert {item["memory_id"] for item in result["selected_memories"]} == {1, 2}
