# Testing Guide

## Overview

The test suite validates all layers of the Clean Architecture, from pure shared utilities through core domain logic, infrastructure I/O, handler composition, server protocol handling, and session lifecycle hooks.

**Framework:** pytest 8.0+ with pytest-cov for coverage reporting and pytest-asyncio for async tests

**Test count:** 1387 tests passing

## Running Tests

```bash
# Full suite
pytest

# With coverage
pytest --cov=mcp_server --cov-report=term-missing

# HTML coverage report
pytest --cov=mcp_server --cov-report=html
open htmlcov/index.html

# Specific layer
pytest tests_py/shared/          # Pure utilities
pytest tests_py/core/            # Domain logic
pytest tests_py/infrastructure/  # I/O layer
pytest tests_py/handlers/        # Composition roots
pytest tests_py/server/          # MCP protocol
pytest tests_py/transport/       # stdio framing
pytest tests_py/hooks/           # Lifecycle hooks

# Single file
pytest tests_py/core/test_sparse_dictionary.py -v

# Run with keyword filter
pytest -k "test_cosine" -v
```

## Test Structure

```
tests_py/
  __init__.py
  test_main.py                          # Entry point tests
  shared/
    test_text.py                        # Keyword extraction
    test_hash.py                        # DJB2 hashing
    test_yaml_parser.py                 # YAML frontmatter parsing
    test_similarity.py                  # Jaccard similarity
    test_categorizer.py                 # Work classification
    test_project_ids.py                 # Path/ID conversions
    test_linear_algebra.py              # numpy vector math
    test_sparse.py                      # Sparse vector operations
    test_types.py                       # Pydantic model validation
    test_memory_types.py                # Memory type validation
  core/
    test_domain_detector.py             # Domain classification
    test_context_generator.py           # Profile text generation
    test_pattern_extractor.py           # Clustering and extraction
    test_style_classifier.py            # Felder-Silverman classification
    test_bridge_finder.py               # Cross-domain connections
    test_blindspot_detector.py          # Gap analysis
    test_profile_builder.py             # Profile orchestration
    test_graph_builder.py               # Graph construction
    test_sparse_dictionary.py           # Dictionary learning
    test_persona_vector.py              # Persona vectors
    test_behavioral_crosscoder.py       # Persistent features
    test_attribution_tracer.py          # Attribution tracing
    test_thermodynamics.py              # Heat/decay computation
    test_hierarchical_predictive_coding.py  # 3-level Friston free energy gate
    test_coupled_neuromodulation.py     # DA/NE/ACh/5-HT coupled cascade
    test_oscillatory_clock.py           # Theta/gamma/SWR phase gating
    test_cascade.py                     # Consolidation stage pipeline
    test_pattern_separation.py          # DG orthogonalization
    test_schema_engine.py               # Cortical knowledge structures
    test_tripartite_synapse.py          # Astrocyte calcium dynamics
    test_interference.py                # Interference management
    test_homeostatic_plasticity.py      # Synaptic scaling + BCM
    test_dendritic_clusters.py          # Branch nonlinear integration
    test_two_stage_model.py             # Hippocampal-cortical transfer
    test_emergence_tracker.py           # System-level metrics
    test_ablation.py                    # Lesion study framework
    test_curation.py                    # Active curation logic
    test_engram.py                      # Memory traces
    test_decay_cycle.py                 # Thermodynamic cooling
    test_compression.py                 # Text compression pipeline
    test_staleness.py                   # File-reference staleness
    test_consolidation_engine.py        # Consolidation orchestration
    test_dual_store_cls.py              # CLS consolidation
    test_causal_graph.py                # PC Algorithm
    test_reconsolidation.py             # Memory updating
    test_replay.py                      # Hippocampal replay
    test_sleep_compute.py               # Dream replay + summarization
    test_query_router.py                # Intent classification + WRRF
    test_hdc_encoder.py                 # Hyperdimensional computing
    test_cognitive_map.py               # Successor Representation
    test_hopfield.py                    # Hopfield network
    test_fractal.py                     # Hierarchical clustering
    test_enrichment.py                  # Doc2Query + synonyms
    test_sensory_buffer.py              # Working memory buffer
    test_knowledge_graph.py             # Entity extraction
    test_prospective.py                 # Trigger-based recall
    test_memory_rules.py                # Neuro-symbolic rules
    test_narrative.py                   # Story generation
    test_metacognition.py               # Self-reflection
    test_session_critique.py            # Session analysis
    test_session_extractor.py           # Memory extraction
  errors/
    test_errors.py                      # Error hierarchy
  validation/
    test_schemas.py                     # Input validation
  infrastructure/
    test_config.py                      # Path constants
    test_file_io.py                     # File operations
    test_profile_store.py               # Profile persistence
    test_session_store.py               # Session log persistence
    test_brain_index_store.py           # Brain index reader
    test_scanner.py                     # Data ingestion
    test_mcp_client.py                  # Async MCP client
    test_mcp_client_pool.py             # Connection pool
    test_memory_store.py                # SQLite + FTS5 persistence
    test_memory_config.py               # Runtime configuration
    test_embedding_engine.py            # Vector embeddings
  handlers/
    test_detect_domain.py               # Domain detection handler
    test_query_methodology.py           # Query handler
    test_list_domains.py                # List handler
    test_rebuild_profiles.py            # Rebuild handler
    test_record_session_end.py          # Session end handler
    test_get_methodology_graph.py       # Graph handler
    test_open_visualization.py          # Visualization handler
    test_explore_features.py            # Features handler
    test_run_pipeline.py                # Pipeline handler
    test_remember.py                    # Remember handler
    test_recall.py                      # Recall handler
    test_consolidate.py                 # Consolidate handler
    test_checkpoint.py                  # Checkpoint handler
    test_narrative.py                   # Narrative handler
    test_memory_stats.py                # Stats handler
    test_import_sessions.py             # Import handler
    test_forget.py                      # Forget handler
    test_validate_memory.py             # Validate handler
    test_rate_memory.py                 # Rate handler
    test_seed_project.py                # Seed handler
    test_anchor.py                      # Anchor handler
    test_backfill_memories.py           # Backfill handler
    test_recall_hierarchical.py         # Hierarchical recall handler
    test_drill_down.py                  # Drill down handler
    test_navigate_memory.py             # Navigate handler
    test_get_causal_chain.py            # Causal chain handler
    test_detect_gaps.py                 # Gap detection handler
    test_sync_instructions.py           # Sync instructions handler
    test_create_trigger.py              # Trigger handler
    test_add_rule.py                    # Rule handler
    test_get_rules.py                   # Rules list handler
    test_get_project_story.py           # Project story handler
    test_assess_coverage.py             # Coverage handler
    test_registry.py                    # Tool registry
  server/
    test_mcp_router.py                  # JSON-RPC routing
    test_http_server.py                 # HTTP visualization server
  transport/
    test_stdio.py                       # stdio transport
  hooks/
    test_session_lifecycle.py           # SessionEnd hook
    test_session_start.py               # SessionStart hook
    test_post_tool_capture.py           # PostToolUse hook
    test_compaction_checkpoint.py       # Compaction checkpoint hook
```

## Testing Patterns

### Pure Function Tests (shared/, core/)

Shared and core modules are pure functions with no I/O dependencies, making them the easiest to test:

```python
class TestJaccardSimilarity:
    def test_identical_sets(self):
        assert jaccard({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint_sets(self):
        assert jaccard({"a"}, {"b"}) == 0.0
```

### Deterministic Fixtures (core/)

Core tests use factory functions to create deterministic test data:

```python
def _make_sessions(count=5, domain="test"):
    """Create deterministic session records for testing."""
    return [
        {
            "project": f"-Users-dev-{domain}",
            "messages": [{"role": "human", "content": f"session {i}"}],
            "toolCounts": {"Read": 3, "Edit": 1},
            "duration": 1000 * (i + 1),
            "turnCount": 5 + i,
        }
        for i in range(count)
    ]
```

### Float Comparison (core/)

Numerical tests use `pytest.approx()` for floating-point comparison:

```python
def test_cosine_similarity_unit_vectors(self):
    a = np.array([1.0, 0.0])
    b = np.array([0.0, 1.0])
    assert cosine_similarity(a, b) == pytest.approx(0.0, abs=1e-10)
```

### Infrastructure Mocking

Infrastructure tests mock filesystem operations using `unittest.mock.patch` and pytest's `tmp_path` fixture:

```python
class TestProfileStore:
    @patch("mcp_server.infrastructure.profile_store.read_json")
    def test_load_profiles_returns_data(self, mock_read):
        mock_read.return_value = {"version": 2, "domains": {}}
        result = load_profiles()
        assert result["version"] == 2
```

### Async Test Pattern

Async functions are tested via `asyncio.get_event_loop().run_until_complete()`:

```python
def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)

class TestMcpRouter:
    def test_returns_server_info(self):
        router = create_router(mock_registry)
        response = _run(router({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}))
        parsed = json.loads(response)
        assert parsed["result"]["serverInfo"]["name"] == "methodology-agent"
```

### Handler Tests

Handler tests mock both infrastructure (I/O) and core (logic) dependencies:

```python
class TestDetectDomainHandler:
    @patch("mcp_server.handlers.detect_domain.detect_domain")
    @patch("mcp_server.handlers.detect_domain.load_profiles")
    def test_returns_domain_and_confidence(self, mock_lp, mock_dd):
        mock_lp.return_value = {"domains": {"test": {...}}}
        mock_dd.return_value = {"domain": "test", "confidence": 0.9}
        result = _run(handler({"cwd": "/tmp/test"}))
        assert result["domain"] == "test"
```

## Coverage Targets

| Layer | Target | Rationale |
|---|---|---|
| `shared/` | 95%+ | Pure functions with no dependencies — exhaustive testing is straightforward |
| `core/` | 90%+ | Deterministic logic; edge cases in clustering and classification need coverage |
| `errors/` | 100% | Trivial exception classes |
| `validation/` | 95%+ | All schema edge cases and type mismatches must be exercised |
| `infrastructure/` | 85%+ | Requires filesystem mocking; focus on happy path + error recovery |
| `handlers/` | 85%+ | Integration-style tests; complex wiring needs comprehensive scenarios |
| `server/transport/` | 80%+ | Protocol boundaries and async I/O framing |
| `hooks/` | 90%+ | Critical automation that runs unattended |

## Adding New Tests

When adding a new module:

1. Create a test file mirroring the source path: `mcp_server/foo/bar.py` → `tests_py/foo/test_bar.py`
2. Ensure `__init__.py` exists in the test subdirectory
3. Follow the naming convention: `class TestClassName` with `def test_specific_behavior`
4. For async code, use the `_run()` wrapper pattern instead of `@pytest.mark.asyncio`
5. Run `pytest --cov=mcp_server.foo.bar --cov-report=term-missing tests_py/foo/test_bar.py` to verify coverage

## Continuous Integration

The test suite is designed to run in CI with:

```bash
pytest --cov=mcp_server --cov-report=xml --cov-fail-under=80
```

This enforces the minimum 80% overall coverage threshold.
