# Dead-code inventory — 2026-10-20

Measured on main `df3a447`. Tooling: vulture 2.14 (`--min-confidence 60`),
a repository-wide word search of every tracked file (code, JSON, TOML, YAML,
Markdown), the Understand-Anything knowledge graph of the same commit
(`calls`/`imports` edges) and coverage.py dynamic contexts (which test
executed which line). The sibling repositories (cortex-viz,
Cortex-enterprise, cortex-voice, cortex-vision, harness-comparison) were
searched for imports of every removed name: none imports `mcp_server`;
cortex-viz carries its own copies of `WorkflowGraphASTSource` and the
entity readers.

## Method

1. vulture over `mcp_server scripts tests_py benchmarks plugins`, keeping
   findings located in `mcp_server/` or `scripts/` (296).
2. Each name searched as a whole word in every tracked file, excluding its
   definition line. Classes: no reference anywhere; referenced only in
   Markdown (archived ADR docstrings); referenced only from tests;
   referenced by code.
3. Every candidate definition read with its decorators and enclosing class
   (no Protocol method, Pydantic validator, tool registration or `__all__`
   entry among them), and `mcp_server/` searched for dynamic lookups
   (`getattr` with a built name, `globals()[...]`): none.
4. After each removal, vulture and ruff again until no new finding
   appeared (three waves).

## Removed (this change)

Criterion: no reference in production code **and** none in tests, or
referenced only by code removed in an earlier wave.

| Module | Removed | Wave |
|---|---|---|
| `core/ablation.py` | `neutral_retrieval_strength`, `neutral_ltp_modulation`, `neutral_interference_score`, `neutral_separation_index`, `neutral_hippocampal_dependency` (the other `neutral_*` stay: they are used) | 1 |
| `core/auto_curator.py` | `_cluster_topic_from_entities` | 1 |
| `core/claim_extractor.py` | `_detects_supersedes`; then `_SUPERSEDES_RE` | 1, 3 |
| `core/coupled_neuromodulation.py` | `modulate_retrieval_temperature` | 1 |
| `core/enrichment.py` | `generate_comet_frames`; then `_COMET_TEMPLATES` | 1, 3 |
| `core/entity_reconciliation.py` | `build_count_eligible_sql` (cited only in a design note) | 1 |
| `core/hdc_encoder.py` | `encode_with_position`; then `permute` (docs updated) | 1, 2 |
| `core/sensory_buffer.py` | `SensoryBuffer.peek_important`, `.drain_displaced`, `.drain_all`, `get_global_buffer`, `reset_global_buffer` | 1 |
| `core/streaming/calibrated.py` | `entity_queue_cap`; then `ENTITY_ROW_BYTES` (an unsourced constant in the baseline) | 1, 2 |
| `core/wiki_curation_gaps.py` | `gap_report`, `render_gap_banner` (the file is now under the 300-line cap) | 1 |
| `core/wiki_sync.py` | `should_sync` | 1 |
| `handlers/codebase_analyze.py` | `_store_file` (a test fixture holds an old copy as text) | 1 |
| `handlers/recall_helpers.py` | `build_result`; then `compute_result_boost` | 1, 2 |
| `handlers/remember_prepared.py` | `PreparedEncoding.raise_input_abort`; then the `InputFailure.abort` field and its two `abort=True` call sites (stopping is done by the generators' `return`, and the error surfaces at its position through `checked()` or `raise job.error`; nothing read the flag) | 1, 2 |
| `infrastructure/agent_config.py` | the whole module (`AGENT_REGISTRY` and its four accessors fed the graph builder that moved to cortex-viz) | 1, 2 |
| `infrastructure/memory_config.py` | `SESSION_COHERENCE_BONUS`, `SESSION_COHERENCE_WINDOW_HOURS`, `RECENCY_BOOST_MAX`, `RECENCY_BOOST_HALFLIFE_DAYS`, `RECENCY_BOOST_CUTOFF_DAYS` (read only by the removed `build_result`/`compute_result_boost`: setting `CORTEX_MEMORY_*` for them already changed nothing) | 2, 3 |
| `infrastructure/pg_store_entities.py` | `get_top_entities_for_domain`, `list_memory_entity_edges` | 1 |
| `infrastructure/stream_sources.py` | `ListStreamSource` | 1 |
| `infrastructure/upstream_identity.py` | `release_asset_name` | 1 |
| `infrastructure/workflow_graph_source_ast.py` | `load_ast_edges`, `_load_symbols_async`, `_load_edges_async` | 1 |
| `shared/types_profiles.py` | `DetectionContext`, `SessionLog` | 1 |
| `shared/vader.py` | `vader_scores` | 1 |
| `shared/wiki_ir.py` | `CurationMemo`; then `MemoSubject` | 1, 2 |
| `shared/wiki_layout.py` | `domain_page_path` | 1 |

Result: 25 files under `mcp_server/`, 470 lines removed and 2 changed
(`git diff --stat`), plus `docs/architecture.md` and
`docs/module-inventory.md` (the HDC operations, the removed module).
`.craftsmanship-baseline.json`
regenerated: two entries removed, both fixed by this change, none added.

## Kept: false positives

- `hooks/shell_read_paths.py` `lexer.whitespace_split = True` and
  `infrastructure/pg_store_query_stream.py` `cur.itersize = ...`: attributes
  set on library objects (shlex, psycopg) to change their behaviour.

## Kept: findings that need a decision

1. **`StageProperties.heat_floor` is documented and never applied.**
   `core/cascade_stages.py` gives LATE_LTP a floor of 0.05 and CONSOLIDATED
   0.10 ("won't fully vanish"); the only reader, `get_heat_floor`, has no
   caller and nothing in decay reads the field. Either wire it into decay
   (a retrieval change: benchmark first) or remove it with its claim.
2. **`SqliteMemoryStore(embedding_dim=...)` is ignored.** The constructor
   stores `self._embedding_dim` and nothing reads it, while
   `memory_store.py` threads the setting through. Remove the parameter or
   make it validate the vector width.
3. **Session coherence is disconnected from recall.**
   `core/thermodynamics.compute_session_coherence` is now reached only by
   `tests_py/core/test_thermodynamics.py`; its two settings were read only
   by the removed `build_result`. No document describes it as active.
4. **206 functions and classes in 109 modules are reached only by tests**
   (vulture without `tests_py`, minus the findings above). They include
   ablation configuration, predictive-coding gates, homeostatic plasticity,
   dendritic computation, schema engine, oscillatory phases and
   reconsolidation helpers. Whether each mechanism is meant to run in the
   pipeline (and must be wired, then benchmarked) or is an experiment to
   delete is a scientific decision per mechanism, not a cleanup. Listed
   below.

### Reached only by tests

- `mcp_server/core/ablation.py` (7): `ablation_config_disable`, `ablation_config_disable_all_except`, `ablation_config_enable`, `ablation_config_is_enabled`, `create_ablation_result`, `neutral_encoding_strength`, `neutral_schema_match`
- `mcp_server/core/ablation_report.py` (2): `format_ablation_report`, `plan_full_ablation_study`
- `mcp_server/core/abstention_gate.py` (1): `should_abstain`
- `mcp_server/core/active_forgetting.py` (1): `should_extinguish`
- `mcp_server/core/attentional_control.py` (2): `attention_allocation_as_dict`, `in_focus_contents`
- `mcp_server/core/capture_origin.py` (2): `is_network_origin`, `trust_factor`
- `mcp_server/core/cascade_advancement.py` (1): `trigger_reconsolidation`
- `mcp_server/core/cascade_stages.py` (3): `compute_stage_adjusted_decay`, `get_stage_properties`, `stage_to_dict`
- `mcp_server/core/causal_graph.py` (2): `find_causal_chain`, `find_common_causes`
- `mcp_server/core/codebase_graph.py` (3): `build_call_edges`, `build_resolved_call_edges`, `compute_impact`
- `mcp_server/core/consolidation_engine.py` (3): `find_near_duplicates`, `should_reclassify`, `summarize_action_group`
- `mcp_server/core/context_assembly/budget.py` (1): `assembly_metrics_was_truncated`
- `mcp_server/core/context_assembly/stage_detector.py` (1): `CompositeStageDetector`
- `mcp_server/core/context_generator.py` (1): `generate_short_context`
- `mcp_server/core/coupled_neuromodulation.py` (4): `modulate_ltp_rate`, `modulate_precision_gain`, `modulate_spreading_breadth`, `modulate_write_gate_threshold`
- `mcp_server/core/curation.py` (1): `merge_tags`
- `mcp_server/core/dendritic_clusters.py` (3): `add_memory_to_branch`, `create_branch`, `find_best_branch`
- `mcp_server/core/dendritic_computation.py` (6): `branch_from_dict`, `branch_to_dict`, `compute_branch_statistics`, `compute_cluster_priming`, `compute_dendritic_integration`, `update_branch_plasticity`
- `mcp_server/core/domain_detector.py` (1): `map_project_to_domain`
- `mcp_server/core/dual_process_retrieval.py` (2): `familiarity_score`, `familiarity_signal_as_dict`
- `mcp_server/core/dual_store_cls.py` (1): `auto_weight`
- `mcp_server/core/emergence_metrics.py` (2): `compute_forgetting_curve`, `generate_emergence_report`
- `mcp_server/core/emergence_tracker.py` (4): `compute_phase_locking_benefit`, `compute_schema_acceleration_metric`, `compute_spacing_benefit`, `compute_testing_benefit`
- `mcp_server/core/engram.py` (2): `compute_lateral_inhibition`, `compute_slot_statistics`
- `mcp_server/core/entity_reconciliation.py` (3): `build_reconciliation_sql`, `exceeds_leak_threshold`, `reconcile_leak_ratio`
- `mcp_server/core/extinction.py` (1): `is_extinguished`
- `mcp_server/core/forward_model.py` (1): `forward_model_state_as_dict`
- `mcp_server/core/goal_maintenance.py` (1): `build_goal_from_task`
- `mcp_server/core/homeostatic_health.py` (1): `compute_distribution_health_streaming`
- `mcp_server/core/homeostatic_plasticity.py` (6): `apply_excitability_bounds`, `apply_synaptic_scaling`, `compute_bcm_threshold`, `compute_excitability_adjustment`, `compute_ltp_ltd_modulation`, `compute_scaling_factor`
- `mcp_server/core/hopfield.py` (3): `compute_energy`, `pattern_completion`, `retrieve_sparse`
- `mcp_server/core/interference.py` (3): `compute_domain_interference_pressure`, `compute_retrieval_suppression`, `orthogonalize_pair`
- `mcp_server/core/interference_detection.py` (2): `detect_proactive_interference`, `detect_retroactive_interference`
- `mcp_server/core/knowledge_graph.py` (1): `infer_relationships`
- `mcp_server/core/metacognition.py` (1): `detect_all_gaps`
- `mcp_server/core/metacognition_analysis.py` (3): `compute_coverage`, `manage_context`, `summarize_overflow`
- `mcp_server/core/microglial_pruning.py` (1): `compute_pruning_stats`
- `mcp_server/core/mmr_diversity.py` (1): `mmr_rerank`
- `mcp_server/core/neurogenesis.py` (3): `apply_temporal_weights`, `compute_separation_index`, `compute_temporal_separation_weights`
- `mcp_server/core/oscillatory_phases.py` (5): `can_bind_item`, `classify_theta_phase`, `compute_replay_priority`, `gamma_binding_strength`, `should_generate_swr`
- `mcp_server/core/persona_vector.py` (3): `persona_distance`, `persona_drift`, `steer_context`
- `mcp_server/core/platt_calibration.py` (1): `pairwise_discrimination`
- `mcp_server/core/predictive_coding_gate.py` (7): `calibration_score`, `check_calibration`, `describe_hierarchical_signals`, `hierarchical_gate_decision`, `precision_to_confidence`, `update_precision`, `update_precision_state`
- `mcp_server/core/procedural_memory.py` (1): `reinforce`
- `mcp_server/core/recall_pipeline.py` (1): `spreading_activation_status`
- `mcp_server/core/reconsolidation.py` (4): `compute_extinction_action`, `compute_plasticity_decay`, `merge_content`, `update_stability`
- `mcp_server/core/reranker_calibration.py` (1): `reset_for_tests`
- `mcp_server/core/retrieval_dispatch.py` (1): `dispatch_retrieval`
- `mcp_server/core/schema_engine.py` (5): `accommodate_schema`, `compute_prediction_error`, `compute_schema_free_energy`, `generate_predictions`, `should_revise_schema`
- `mcp_server/core/sensory_buffer.py` (1): `push`
- `mcp_server/core/separation_core.py` (1): `apply_sparsification`
- `mcp_server/core/sleep_compute.py` (1): `run_sleep_compute`
- `mcp_server/core/source_monitoring.py` (1): `source_judgement_as_dict`
- `mcp_server/core/spreading_activation.py` (4): `build_entity_graph`, `map_entity_activation_to_memories`, `resolve_seed_entities`, `spread_activation`
- `mcp_server/core/stress_modulation.py` (2): `assess_session_stress`, `is_impairing`
- `mcp_server/core/tabular_encoding.py` (1): `decode_tabular`
- `mcp_server/core/targeted_reactivation.py` (1): `rerank_replay_set`
- `mcp_server/core/thermodynamics.py` (3): `compute_decay`, `compute_session_coherence`, `compute_surprise`
- `mcp_server/core/titans_memory.py` (1): `compute_surprise`
- `mcp_server/core/tripartite_calcium.py` (3): `compute_heterosynaptic_depression`, `compute_ltp_modulation`, `propagate_calcium_wave`
- `mcp_server/core/value_learning.py` (2): `assign_credit`, `value_update_as_dict`
- `mcp_server/core/wiki_axis_registry.py` (1): `reset_registry`
- `mcp_server/core/wiki_groomer.py` (1): `audit_wiki`
- `mcp_server/core/wiki_identity.py` (1): `page_identity_from_frontmatter`
- `mcp_server/core/wiki_redirect.py` (1): `redirect_is_id_based`
- `mcp_server/core/wiki_templates.py` (1): `template_for`
- `mcp_server/core/write_gate.py` (2): `apply_goal_maintenance`, `apply_habituation`
- `mcp_server/core/write_post_store.py` (1): `invalidate_slot_cache`
- `mcp_server/doctor.py` (1): `ensure_reranker_ready`
- `mcp_server/errors/__init__.py` (2): `AnalysisError`, `StorageError`
- `mcp_server/handlers/admission.py` (2): `current_budget`, `reset_semaphores`
- `mcp_server/handlers/consolidation/change_remediation_pass.py` (1): `remediate_impacted`
- `mcp_server/handlers/consolidation/plasticity.py` (1): `_find_co_accessed_pairs`
- `mcp_server/handlers/latency_class.py` (1): `all_registered_tools`
- `mcp_server/handlers/remember_helpers.py` (1): `compute_similarities`
- `mcp_server/handlers/wiki_memory_sync.py` (1): `sync_memory`
- `mcp_server/infrastructure/abstention_classifier.py` (1): `load_abstention_classifier`
- `mcp_server/infrastructure/ap_bridge.py` (2): `get_context`, `index_codebase`
- `mcp_server/infrastructure/batch_sinks.py` (2): `CopyBatchSink`, `ExecuteManyBatchSink`
- `mcp_server/infrastructure/embedding_engine.py` (1): `model_state`
- `mcp_server/infrastructure/groomer_coordinator.py` (1): `count_cycles_since`
- `mcp_server/infrastructure/mcp_client.py` (1): `server_info`
- `mcp_server/infrastructure/mcp_client_pool.py` (1): `close_client`
- `mcp_server/infrastructure/memory_store.py` (1): `__new__`
- `mcp_server/infrastructure/pg_store_engram.py` (2): `get_engram_slot`, `get_memories_in_slot`
- `mcp_server/infrastructure/pg_store_heat.py` (1): `update_memories_heat_batch`
- `mcp_server/infrastructure/pg_store_memory_meta.py` (3): `get_user_mood_state`, `set_memory_protected`, `update_memory_extinction`
- `mcp_server/infrastructure/pg_store_prospective.py` (1): `deactivate_prospective_memory`
- `mcp_server/infrastructure/pg_store_schema.py` (1): `_reconnect`
- `mcp_server/infrastructure/pg_store_stats.py` (1): `extinguished_count`
- `mcp_server/infrastructure/profile_store.py` (1): `empty_profiles`
- `mcp_server/infrastructure/sqlite_store.py` (3): `set_memory_protected`, `update_memories_heat_batch`, `update_memory_extinction`
- `mcp_server/infrastructure/sqlite_store_auxiliary.py` (3): `deactivate_prospective_memory`, `get_engram_slot`, `get_memories_in_slot`
- `mcp_server/infrastructure/sqlite_store_mood.py` (1): `get_user_mood_state`
- `mcp_server/infrastructure/sqlite_store_stats.py` (1): `extinguished_count`
- `mcp_server/infrastructure/upstream_governor.py` (1): `current_budget`
- `mcp_server/infrastructure/viz_client.py` (1): `fetch_live_graph`
- `mcp_server/infrastructure/wiki_decision_index.py` (1): `quarantine_malformed_decisions`
- `mcp_server/infrastructure/wiki_pages_listing.py` (1): `append_section`
- `mcp_server/infrastructure/workflow_graph_source_ast.py` (2): `iter_ast_edges`, `load_symbols`
- `mcp_server/observability/metrics.py` (1): `set_gauge`
- `mcp_server/shared/linear_algebra.py` (1): `clamp`
- `mcp_server/shared/sparse.py` (6): `dense_to_sparse`, `sparse_add`, `sparse_cosine`, `sparse_scale`, `sparse_to_dense`, `sparse_top_k`
- `mcp_server/shared/temporal.py` (1): `is_temporal_query`
- `mcp_server/shared/text.py` (1): `extract_keywords_array`
- `mcp_server/shared/types_profiles.py` (2): `ProfilesV2`, `SessionLogEntry`
- `mcp_server/shared/wiki_classification.py` (2): `all_known_kinds`, `is_legacy_kind`
- `mcp_server/shared/wiki_layout.py` (2): `file_path_slug`, `parse_page_path`
- `mcp_server/validation/schemas.py` (1): `validate_tool_args`
