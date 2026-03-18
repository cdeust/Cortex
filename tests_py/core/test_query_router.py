"""Tests for mcp_server.core.query_router — intent classification and retrieval routing."""

from mcp_server.core.query_intent import (
    QueryIntent,
    classify_query_intent,
    compute_retrieval_weights,
)
from mcp_server.core.query_decomposition import (
    route_query,
    extract_query_entities,
    decompose_query,
)


# ── classify_query_intent ────────────────────────────────────────────────


class TestClassifyQueryIntent:
    def test_temporal_query(self):
        result = classify_query_intent("when did the deployment happen?")
        assert result["intent"] == QueryIntent.TEMPORAL

    def test_causal_query(self):
        result = classify_query_intent("why did the build fail?")
        assert result["intent"] == QueryIntent.CAUSAL

    def test_semantic_query(self):
        result = classify_query_intent("find something related to authentication")
        assert result["intent"] == QueryIntent.SEMANTIC

    def test_entity_query(self):
        result = classify_query_intent("what is the UserService?")
        assert result["intent"] == QueryIntent.ENTITY

    def test_general_query(self):
        result = classify_query_intent("hello")
        assert result["intent"] == QueryIntent.GENERAL

    def test_returns_scores(self):
        result = classify_query_intent("why did this happen recently?")
        assert "scores" in result
        assert QueryIntent.CAUSAL in result["scores"]
        assert QueryIntent.TEMPORAL in result["scores"]

    def test_returns_weights(self):
        result = classify_query_intent("test query")
        assert "weights" in result

    def test_question_why_boosts_causal(self):
        result = classify_query_intent("why is it broken?")
        assert result["scores"][QueryIntent.CAUSAL] >= 1.0

    def test_question_when_boosts_temporal(self):
        result = classify_query_intent("when was it deployed?")
        assert result["scores"][QueryIntent.TEMPORAL] >= 1.0

    def test_question_what_boosts_entity(self):
        result = classify_query_intent("what does this do?")
        assert result["scores"][QueryIntent.ENTITY] > 0

    def test_question_how_boosts_causal(self):
        result = classify_query_intent("how did this break?")
        assert result["scores"][QueryIntent.CAUSAL] > 0

    def test_multiple_signals_highest_wins(self):
        result = classify_query_intent(
            "why did this happen yesterday and what caused it?"
        )
        assert result["intent"] == QueryIntent.CAUSAL


# ── compute_retrieval_weights ────────────────────────────────────────────


class TestComputeRetrievalWeights:
    def test_temporal_weights(self):
        w = compute_retrieval_weights(QueryIntent.TEMPORAL, {})
        assert w["temporal"] == 1.0
        assert w["vector"] < 1.0

    def test_causal_weights(self):
        w = compute_retrieval_weights(QueryIntent.CAUSAL, {})
        assert w["causal"] == 1.0
        assert w["entity"] > 0.5

    def test_semantic_weights(self):
        w = compute_retrieval_weights(QueryIntent.SEMANTIC, {})
        assert w["vector"] == 1.0
        assert w["fts"] > 0.5

    def test_entity_weights(self):
        w = compute_retrieval_weights(QueryIntent.ENTITY, {})
        assert w["entity"] == 1.0
        assert w["fts"] > 0.5

    def test_general_uses_base_weights(self):
        w = compute_retrieval_weights(QueryIntent.GENERAL, {})
        assert w["vector"] == 1.0
        assert w["fts"] == 0.5

    def test_all_weight_keys_present(self):
        w = compute_retrieval_weights(QueryIntent.GENERAL, {})
        for key in ["vector", "fts", "heat", "temporal", "causal", "entity"]:
            assert key in w

    def test_weights_are_rounded(self):
        w = compute_retrieval_weights(QueryIntent.TEMPORAL, {})
        for v in w.values():
            assert v == round(v, 3)


# ── route_query ──────────────────────────────────────────────────────────


class TestRouteQuery:
    def test_returns_intent(self):
        result = route_query("why did this fail?")
        assert result["intent"] == QueryIntent.CAUSAL

    def test_returns_ordered_signals(self):
        result = route_query("test query")
        signals = result["signals"]
        assert len(signals) > 0
        # Should be sorted by weight descending
        weights = [s[1] for s in signals]
        assert weights == sorted(weights, reverse=True)

    def test_filters_available_signals(self):
        result = route_query("test", available_signals=["vector", "fts"])
        signal_names = [s[0] for s in result["signals"]]
        assert all(s in ["vector", "fts"] for s in signal_names)

    def test_causal_special_handler(self):
        result = route_query("why did the error happen?")
        assert "causal_chain_search" in result["special_handlers"]

    def test_temporal_special_handler(self):
        result = route_query("when did the deployment happen?")
        assert "time_window_search" in result["special_handlers"]

    def test_entity_special_handler(self):
        result = route_query("what is the UserService?")
        assert "entity_graph_traversal" in result["special_handlers"]

    def test_general_no_special_handlers(self):
        result = route_query("hello")
        assert result["special_handlers"] == []

    def test_includes_classification(self):
        result = route_query("test")
        assert "classification" in result


# ── extract_query_entities ───────────────────────────────────────────────


class TestExtractQueryEntities:
    def test_camel_case(self):
        entities = extract_query_entities("Check the UserService class")
        assert "UserService" in entities

    def test_file_path(self):
        entities = extract_query_entities("look at src/main.py")
        assert "src/main.py" in entities

    def test_backtick_quoted(self):
        entities = extract_query_entities("run the `deploy` command")
        assert "deploy" in entities

    def test_no_entities(self):
        entities = extract_query_entities("hello world")
        assert entities == []

    def test_single_char_filtered(self):
        entities = extract_query_entities("use `x` variable")
        # Single char should be filtered (len > 1)
        assert "x" not in entities

    def test_multiple_entities(self):
        entities = extract_query_entities("UserService calls DataStore via api.json")
        assert len(entities) >= 2


# ── decompose_query ──────────────────────────────────────────────────────


class TestDecomposeQuery:
    def test_returns_routing(self):
        result = decompose_query("why did UserService fail?")
        assert "routing" in result
        assert result["routing"]["intent"] == QueryIntent.CAUSAL

    def test_returns_entities(self):
        result = decompose_query("check UserService")
        assert "entities" in result
        assert "UserService" in result["entities"]

    def test_returns_keywords(self):
        result = decompose_query("authentication service failed")
        assert "keywords" in result
        assert "authentication" in result["keywords"]

    def test_filters_stopwords(self):
        result = decompose_query("what is the status of the build")
        kw = result["keywords"]
        assert "the" not in kw
        assert "is" not in kw

    def test_returns_time_hints(self):
        result = decompose_query("what happened yesterday?")
        assert "time_hints" in result
        assert "yesterday" in result["time_hints"]

    def test_no_time_hints(self):
        result = decompose_query("check code quality")
        assert result["time_hints"] == []

    def test_short_words_filtered(self):
        result = decompose_query("do it on go")
        # Words with len <= 2 filtered
        for kw in result["keywords"]:
            assert len(kw) > 2
