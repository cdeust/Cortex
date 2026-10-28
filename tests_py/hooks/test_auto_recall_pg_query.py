"""Keep PostgreSQL lexical discovery bounded while reranking the full prompt."""

from mcp_server.hooks import auto_recall


def test_long_prompt_keeps_lexical_prefix_and_full_semantic_query(monkeypatch):
    query = "espresso beans ".ljust(200) + "unrelated appended deployment instructions"
    statements = []
    semantic_queries = []

    class Connection:
        def execute(self, statement, params):
            statements.append((statement, params))
            return self

        def fetchall(self):
            return []

    def rank(full_query, lexical, hot_pool):
        semantic_queries.append(full_query)
        return lexical

    monkeypatch.setattr(auto_recall, "rank_memories", rank)
    assert auto_recall._recall_memories(Connection(), query, "/repo") == []
    # source: pre-fix hook's 200-character lexical query bound, PR #826 review.
    assert statements[0][1][0] == query[:200]
    assert semantic_queries == [query]
