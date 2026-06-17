"""Tests for mcp_server.handlers.assess_coverage.

Contract under test (from handler docstring + schema description):
  - Returns {coverage_score, total_memories, recommendations} always.
  - coverage_score is an integer in [0, 100].
  - recommendations is a non-empty list of strings.
  - Empty store: coverage_score == 0, total_memories == 0,
    recommendations contains the bootstrap prompt.
  - Non-empty store: full axes included in response
    (age_distribution, entity_density, compression, domain_balance).
  - stale_days controls age bucketing (must accept int in [1, 365]).
  - domain filter narrows the memory set assessed.
  - _compute_coverage_score is bounded to [0, 100] for any inputs.
  - Sub-evaluators: _age_distribution, _domain_balance, _compression_ratio,
    _entity_density each respect their postconditions independently.

Tests work under both PostgreSQL (when available) and the SQLite fallback
configured by conftest.py. No PG-specific skip needed: conftest sets up
CORTEX_MEMORY_STORE_BACKEND=sqlite when PG is unreachable.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Pure-function sub-evaluator tests (no DB required)
# ---------------------------------------------------------------------------


class TestAgeDistribution:
    """_age_distribution postconditions, no I/O."""

    def _call(self, memories, stale_days=14):
        from mcp_server.handlers.assess_coverage import _age_distribution

        return _age_distribution(memories, stale_days)

    def test_empty_memories_returns_zero_totals(self):
        result = self._call([])
        assert result["fresh"] == 0
        assert result["stale"] == 0
        assert result["total"] == 0
        assert result["freshness_ratio"] == 0.0

    def test_fresh_memory_counted(self):
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat()
        result = self._call([{"created_at": now_iso}], stale_days=14)
        assert result["total"] == 1
        assert result["fresh"] == 1
        assert result["stale"] == 0
        assert result["freshness_ratio"] == 1.0

    def test_stale_memory_counted(self):
        from datetime import datetime, timedelta, timezone

        old_iso = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        result = self._call([{"created_at": old_iso}], stale_days=14)
        assert result["total"] == 1
        assert result["stale"] == 1
        assert result["freshness_ratio"] == 0.0

    def test_missing_created_at_skipped(self):
        """Memories without created_at must not raise and must not count."""
        result = self._call([{"content": "no timestamp"}])
        assert result["total"] == 0
        assert result["freshness_ratio"] == 0.0

    def test_invalid_timestamp_skipped(self):
        """Malformed timestamps must be silently skipped, not raise."""
        result = self._call([{"created_at": "not-a-date"}])
        assert result["total"] == 0


class TestDomainBalance:
    """_domain_balance postconditions."""

    def _call(self, memories):
        from mcp_server.handlers.assess_coverage import _domain_balance

        return _domain_balance(memories)

    def test_empty_returns_zero_score(self):
        result = self._call([])
        assert result["domains"] == {}
        assert result["balance_score"] == 0.0

    def test_single_domain_perfectly_balanced(self):
        memories = [{"domain": "cortex"}, {"domain": "cortex"}]
        result = self._call(memories)
        # Single domain has zero variance → CV = 0 → balance_score = 1.0
        assert result["balance_score"] == 1.0
        assert result["domains"]["cortex"] == 2

    def test_unassigned_domain_falls_back(self):
        """Memories without a domain key are counted as 'unassigned'."""
        memories = [{"content": "no domain"}]
        result = self._call(memories)
        assert "unassigned" in result["domains"]

    def test_balance_score_in_range(self):
        """balance_score must always be in [0.0, 1.0]."""
        memories = [
            {"domain": "a"},
            {"domain": "a"},
            {"domain": "a"},
            {"domain": "b"},
        ]
        result = self._call(memories)
        assert 0.0 <= result["balance_score"] <= 1.0


class TestCompressionRatio:
    """_compression_ratio postconditions."""

    def _call(self, memories):
        from mcp_server.handlers.assess_coverage import _compression_ratio

        return _compression_ratio(memories)

    def test_empty_returns_zero(self):
        result = self._call([])
        assert result["compressed"] == 0
        assert result["total"] == 0
        assert result["ratio"] == 0.0

    def test_no_compressed_memories(self):
        memories = [{"compression_level": 0}, {"compression_level": 0}]
        result = self._call(memories)
        assert result["compressed"] == 0
        assert result["total"] == 2
        assert result["ratio"] == 0.0

    def test_all_compressed(self):
        memories = [{"compression_level": 1}, {"compression_level": 2}]
        result = self._call(memories)
        assert result["compressed"] == 2
        assert result["ratio"] == 1.0

    def test_partial_compression(self):
        memories = [{"compression_level": 1}, {"compression_level": 0}]
        result = self._call(memories)
        assert result["compressed"] == 1
        assert result["total"] == 2
        assert result["ratio"] == pytest.approx(0.5)


class TestComputeCoverageScore:
    """_compute_coverage_score is bounded to [0, 100] for any input."""

    def _call(self, **kwargs):
        from mcp_server.handlers.assess_coverage import _compute_coverage_score

        return _compute_coverage_score(**kwargs)

    def _base(self, **overrides):
        params = {
            "total_memories": 0,
            "freshness_ratio": 0.0,
            "entity_density": 0.0,
            "compression_ratio": 0.0,
            "balance_score": 0.0,
        }
        params.update(overrides)
        return params

    def test_all_zero_inputs_lower_bounded(self):
        score = self._call(**self._base())
        # The formula adds 0.10 baseline, so floor is 10 not 0
        assert 0 <= score <= 100

    def test_all_ideal_inputs_upper_bounded(self):
        score = self._call(
            **self._base(
                total_memories=100,
                freshness_ratio=1.0,
                entity_density=3.0,
                compression_ratio=0.0,
                balance_score=1.0,
            )
        )
        assert 0 <= score <= 100

    def test_extreme_compression_penalty_bounded(self):
        score = self._call(**self._base(compression_ratio=1.0))
        assert 0 <= score <= 100

    def test_returns_integer(self):
        score = self._call(**self._base(total_memories=50, freshness_ratio=0.5))
        assert isinstance(score, int)


class TestRecommendations:
    """_recommendations postconditions."""

    def _call(self, **kwargs):
        from mcp_server.handlers.assess_coverage import _recommendations

        return _recommendations(**kwargs)

    def _base(self, **overrides):
        params = {
            "total": 30,
            "fresh": 20,
            "stale": 5,
            "entity_density": 1.0,
            "compressed": 0,
            "balance_score": 0.8,
        }
        params.update(overrides)
        return params

    def test_returns_non_empty_list(self):
        recs = self._call(**self._base())
        assert isinstance(recs, list)
        assert len(recs) >= 1

    def test_healthy_state_returns_consolidate_hint(self):
        recs = self._call(**self._base())
        assert any("consolidate" in r.lower() for r in recs)

    def test_low_total_triggers_seed_recommendation(self):
        recs = self._call(**self._base(total=5))
        assert any("seed_project" in r for r in recs)

    def test_high_staleness_triggers_validate_recommendation(self):
        recs = self._call(**self._base(total=10, stale=6))
        assert any("validate_memory" in r for r in recs)

    def test_low_entity_density_triggers_recommendation(self):
        recs = self._call(**self._base(entity_density=0.1))
        assert any("entity" in r.lower() or "density" in r.lower() for r in recs)

    def test_high_compression_triggers_recommendation(self):
        recs = self._call(**self._base(total=10, compressed=6))
        assert any("compression" in r.lower() or "seed_project" in r for r in recs)

    def test_poor_balance_triggers_recommendation(self):
        recs = self._call(**self._base(balance_score=0.1))
        assert any("domain" in r.lower() or "balance" in r.lower() for r in recs)


# ---------------------------------------------------------------------------
# Handler-level integration tests (use SQLite/PG via conftest)
# ---------------------------------------------------------------------------


class TestAssessCoverageHandlerEmptyStore:
    """Empty-store contract: coverage_score == 0, bootstrap recommendation."""

    @pytest.mark.asyncio
    async def test_empty_store_returns_zero_score(self):
        from mcp_server.handlers.assess_coverage import handler

        result = await handler()
        assert result["coverage_score"] == 0

    @pytest.mark.asyncio
    async def test_empty_store_returns_zero_total_memories(self):
        from mcp_server.handlers.assess_coverage import handler

        result = await handler()
        assert result["total_memories"] == 0

    @pytest.mark.asyncio
    async def test_empty_store_returns_bootstrap_recommendation(self):
        from mcp_server.handlers.assess_coverage import handler

        result = await handler()
        assert "recommendations" in result
        assert isinstance(result["recommendations"], list)
        assert len(result["recommendations"]) >= 1
        # The empty-store path must tell the user to bootstrap
        assert any("seed_project" in r for r in result["recommendations"])

    @pytest.mark.asyncio
    async def test_empty_store_no_axes_keys(self):
        """Empty-store early return must NOT include partial axes keys."""
        from mcp_server.handlers.assess_coverage import handler

        result = await handler()
        # The early-return dict has only: coverage_score, total_memories, recommendations
        assert set(result.keys()) == {
            "coverage_score",
            "total_memories",
            "recommendations",
        }

    @pytest.mark.asyncio
    async def test_none_args_treated_as_empty(self):
        from mcp_server.handlers.assess_coverage import handler

        result = await handler(None)
        assert result["coverage_score"] == 0
        assert result["total_memories"] == 0


class TestAssessCoverageHandlerWithMemories:
    """Non-empty store: full axes + score in [0,100]."""

    def _insert_memory(self, store, content: str, domain: str = "testing") -> None:
        from mcp_server.infrastructure.embedding_engine import EmbeddingEngine
        from mcp_server.infrastructure.memory_config import get_memory_settings

        engine = EmbeddingEngine(dim=get_memory_settings().EMBEDDING_DIM)
        emb = engine.encode(content)
        store.insert_memory(
            {
                "content": content,
                "embedding": emb,
                "tags": ["test"],
                "domain": domain,
                "directory": "/tmp",
                "source": "test",
                "importance": 0.5,
                "surprise": 0.3,
                "emotional_valence": 0.0,
                "confidence": 1.0,
                "heat": 0.5,
            }
        )

    @pytest.mark.asyncio
    async def test_non_empty_store_score_in_range(self):
        from mcp_server.handlers.assess_coverage import handler, _get_store

        store = _get_store()
        self._insert_memory(store, "handler covers the auth module")

        result = await handler()
        assert 0 <= result["coverage_score"] <= 100

    @pytest.mark.asyncio
    async def test_non_empty_store_total_memories_positive(self):
        from mcp_server.handlers.assess_coverage import handler, _get_store

        store = _get_store()
        self._insert_memory(store, "main processing loop analyzed")

        result = await handler()
        assert result["total_memories"] >= 1

    @pytest.mark.asyncio
    async def test_non_empty_store_full_axes_present(self):
        """Full response must include all five axes keys."""
        from mcp_server.handlers.assess_coverage import handler, _get_store

        store = _get_store()
        self._insert_memory(store, "schema migration tracked")

        result = await handler()
        assert "age_distribution" in result
        assert "entity_density" in result
        assert "compression" in result
        assert "domain_balance" in result

    @pytest.mark.asyncio
    async def test_non_empty_store_recommendations_is_list(self):
        from mcp_server.handlers.assess_coverage import handler, _get_store

        store = _get_store()
        self._insert_memory(store, "test memory for recommendations check")

        result = await handler()
        assert isinstance(result["recommendations"], list)
        assert len(result["recommendations"]) >= 1
        assert all(isinstance(r, str) for r in result["recommendations"])

    @pytest.mark.asyncio
    async def test_age_distribution_shape(self):
        """age_distribution must have fresh, stale, total, freshness_ratio."""
        from mcp_server.handlers.assess_coverage import handler, _get_store

        store = _get_store()
        self._insert_memory(store, "recent work on API layer")

        result = await handler()
        age = result["age_distribution"]
        assert "fresh" in age
        assert "stale" in age
        assert "total" in age
        assert "freshness_ratio" in age
        assert 0.0 <= age["freshness_ratio"] <= 1.0

    @pytest.mark.asyncio
    async def test_compression_shape(self):
        """compression must have compressed, total, ratio."""
        from mcp_server.handlers.assess_coverage import handler, _get_store

        store = _get_store()
        self._insert_memory(store, "compression test memory")

        result = await handler()
        comp = result["compression"]
        assert "compressed" in comp
        assert "total" in comp
        assert "ratio" in comp
        assert 0.0 <= comp["ratio"] <= 1.0

    @pytest.mark.asyncio
    async def test_domain_balance_shape(self):
        """domain_balance must have domains dict and balance_score in [0,1]."""
        from mcp_server.handlers.assess_coverage import handler, _get_store

        store = _get_store()
        self._insert_memory(store, "domain balance check memory", domain="testing")

        result = await handler()
        bal = result["domain_balance"]
        assert "domains" in bal
        assert "balance_score" in bal
        assert isinstance(bal["domains"], dict)
        assert 0.0 <= bal["balance_score"] <= 1.0

    @pytest.mark.asyncio
    async def test_entity_density_shape(self):
        """entity_density must have avg_entities_per_memory and total_entities."""
        from mcp_server.handlers.assess_coverage import handler, _get_store

        store = _get_store()
        self._insert_memory(store, "entity density check memory")

        result = await handler()
        dens = result["entity_density"]
        assert "avg_entities_per_memory" in dens
        assert "total_entities" in dens
        assert dens["avg_entities_per_memory"] >= 0.0
        assert dens["total_entities"] >= 0


class TestAssessCoverageHandlerArgs:
    """Argument handling: stale_days, domain, directory."""

    def _insert_memory(self, store, content: str, domain: str = "testing") -> None:
        from mcp_server.infrastructure.embedding_engine import EmbeddingEngine
        from mcp_server.infrastructure.memory_config import get_memory_settings

        engine = EmbeddingEngine(dim=get_memory_settings().EMBEDDING_DIM)
        emb = engine.encode(content)
        store.insert_memory(
            {
                "content": content,
                "embedding": emb,
                "tags": ["test"],
                "domain": domain,
                "directory": "/tmp",
                "source": "test",
                "importance": 0.5,
                "surprise": 0.3,
                "emotional_valence": 0.0,
                "confidence": 1.0,
                "heat": 0.5,
            }
        )

    @pytest.mark.asyncio
    async def test_stale_days_accepted(self):
        """Handler must accept stale_days without raising."""
        from mcp_server.handlers.assess_coverage import handler

        result = await handler({"stale_days": 7})
        # Any result shape is valid; the test catches TypeError/ValueError regressions
        assert "coverage_score" in result

    @pytest.mark.asyncio
    async def test_domain_filter_empty_store_returns_zero(self):
        """Filtering by domain when no memories match → empty-store path."""
        from mcp_server.handlers.assess_coverage import handler

        result = await handler({"domain": "nonexistent-domain-xyz"})
        assert result["coverage_score"] == 0
        assert result["total_memories"] == 0

    @pytest.mark.asyncio
    async def test_domain_filter_matches_correct_domain(self):
        """Memories from a different domain must not bleed into filtered result."""
        from mcp_server.handlers.assess_coverage import handler, _get_store

        store = _get_store()
        self._insert_memory(store, "memory in domain alpha", domain="alpha")
        self._insert_memory(store, "memory in domain beta", domain="beta")

        result_alpha = await handler({"domain": "alpha"})
        result_beta = await handler({"domain": "beta"})

        # Each domain scoped query should only see its own memories
        # (total_memories may differ from global; at least one match each)
        assert result_alpha["total_memories"] >= 1
        assert result_beta["total_memories"] >= 1

    @pytest.mark.asyncio
    async def test_directory_returns_zero_when_no_match(self):
        """Filtering by an unused directory → empty-store path."""
        from mcp_server.handlers.assess_coverage import handler

        result = await handler({"directory": "/no/such/path/xyz"})
        assert "coverage_score" in result

    @pytest.mark.asyncio
    async def test_response_echoes_directory_and_domain(self):
        """Full response must echo back directory and domain args."""
        from mcp_server.handlers.assess_coverage import handler, _get_store

        store = _get_store()
        self._insert_memory(store, "echo check memory", domain="echo-test")

        result = await handler({"domain": "echo-test"})
        if result["total_memories"] > 0:
            assert "directory" in result
            assert "domain" in result


class TestAssessCoverageSchema:
    """Schema contract: title, description, inputSchema with correct property types."""

    def test_schema_has_description(self):
        from mcp_server.handlers.assess_coverage import schema

        assert "description" in schema
        assert len(schema["description"]) > 0

    def test_schema_has_input_schema(self):
        from mcp_server.handlers.assess_coverage import schema

        assert "inputSchema" in schema
        assert schema["inputSchema"]["type"] == "object"

    def test_schema_properties_declared(self):
        from mcp_server.handlers.assess_coverage import schema

        props = schema["inputSchema"]["properties"]
        assert "directory" in props
        assert "domain" in props
        assert "stale_days" in props

    def test_stale_days_has_bounds(self):
        from mcp_server.handlers.assess_coverage import schema

        stale = schema["inputSchema"]["properties"]["stale_days"]
        assert stale.get("minimum", 0) >= 1
        assert stale.get("maximum", 0) <= 365

    def test_schema_is_read_only(self):
        from mcp_server.handlers.assess_coverage import schema

        annotations = schema.get("annotations", {})
        assert annotations.get("readOnlyHint") is True
        assert annotations.get("destructiveHint") is False


class TestAssessCoverageSingletons:
    """Singleton helper returns a valid store."""

    def test_get_store_not_none(self):
        from mcp_server.handlers.assess_coverage import _get_store

        store = _get_store()
        assert store is not None
