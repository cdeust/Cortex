"""Real PostgreSQL contracts for persisted graph, rules and consolidation data.

The shared conftest owns database isolation. SQLite jobs omit this backend;
the unit CI starts a private PostgreSQL cluster and runs every test here.
"""

import pytest

from mcp_server.infrastructure.memory_config import get_memory_settings
from tests_py.conftest import _TEST_DB_URL, _USE_PG

pytestmark = pytest.mark.skipif(not _USE_PG, reason="requires PostgreSQL")
_MOOD_USER = "pg-persistence-contract-user"
_UNSET_MOOD_USER = "pg-persistence-contract-unset"


@pytest.fixture
def store():
    from mcp_server.infrastructure.pg_store import PgMemoryStore

    instance = PgMemoryStore(database_url=_TEST_DB_URL)

    # These auxiliary tables are outside conftest's common table cleanup.
    def clear_auxiliary():
        with instance.acquire_batch() as conn:
            conn.execute("DELETE FROM user_mood WHERE user_id = %s", (_MOOD_USER,))
            conn.execute("DELETE FROM ingest_progress")
            conn.execute("DELETE FROM homeostatic_fold_log")
            conn.execute("DELETE FROM wiki.pages")

    try:
        clear_auxiliary()
        yield instance
    finally:
        try:
            clear_auxiliary()
        finally:
            instance.close()


def _ids(rows):
    return [row["id"] for row in rows]


def test_schema_collision_updates_same_identity_and_recovers_transaction(store):
    original = {"schema_id": "contract", "domain": "old", "label": "before"}
    identity = store.insert_schema(original)
    updated = {
        **original,
        "domain": "new",
        "label": "after's label",
        "entity_signature": {"kind": 2},
        "relationship_types": ["uses"],
        "tag_signature": {"sql": 1},
        "formation_count": 4,
    }
    assert store.insert_schema(updated) == identity
    other = store.insert_schema({"schema_id": "second", "domain": "new"})
    assert store.count_schemas() == 2
    assert store.get_schemas_for_domain("old") == []
    assert _ids(store.get_schemas_for_domain("new")) == [identity, other]
    row = store.get_all_schemas()[0]
    for key in ("label", "entity_signature", "relationship_types", "tag_signature"):
        assert row[key] == updated[key]
    assert store.delete_schema("contract") is True
    assert store.delete_schema("contract") is False
    assert _ids(store.get_all_schemas()) == [other]


def test_rule_updates_bind_values_and_reject_noneditable_columns(store):
    low = store.insert_rule({"condition": "low", "action": "keep"})
    high = store.insert_rule({"condition": "high", "action": "keep", "priority": 3})
    inactive = store.insert_rule(
        {"condition": "hidden", "action": "keep", "is_active": False}
    )
    assert _ids(store.get_rules_for_scope("global")) == [high, low]
    payload = "quoted'; DELETE FROM memory_rules; --"
    store.update_rule(low, {"condition": payload, "priority": 5, "id": inactive})
    store.update_rule(high, {"id": low, "source_memory_id": 999})
    rows = store.get_all_active_rules()
    assert _ids(rows) == [low, high]
    assert rows[0]["condition"] == payload
    assert rows[1]["condition"] == "high"
    store.update_rule(low, {"is_active": False})
    assert _ids(store.get_all_active_rules()) == [high]


def test_entity_bulk_updates_and_links_preserve_graph_identity(store):
    first = store.insert_entity(
        {"name": "First", "type": "concept", "domain": "sql", "origin": "unknown"}
    )
    second = store.insert_entity({"name": "Second", "type": "concept", "domain": "sql"})
    assert store.get_entity_by_id(first)["origin"] == "text_concept"
    assert (
        store.insert_entity(
            {"name": "FIRST", "type": "concept", "origin": "ast_symbol"}
        )
        == first
    )
    assert store.get_entity_by_name("first")["origin"] == "ast_symbol"
    assert store.get_entity_by_id(-1) is None
    assert store.get_entity_by_name("missing") is None
    assert store.update_entities_heat_batch([]) == 0
    assert store.update_entities_heat_batch([(first, 0.2), (second, 0.8)]) == 2
    assert _ids(store.get_top_entities_for_domain("sql", limit=1)) == [second]
    store.update_entities_heat_batch([(first, 0.8)])
    assert _ids(store.get_top_entities_for_domain("sql", limit=2)) == [second, first]
    store.update_entities_heat_batch([(first, 0.2)])
    assert store.count_entities() == 2
    assert set(_ids(store.get_entities_of_type("concept"))) == {first, second}
    assert store.get_domain_entity_counts() == [{"domain": "sql", "count": 2}]
    memory = store.insert_memory({"content": "graph contract"})
    store.insert_memory_entity(memory, first)
    store.insert_memory_entity(memory, first)
    store.insert_memory_entity(memory, second)
    assert store.get_entity_ids_for_memories([]) == {}
    assert store.get_entity_ids_for_memories([memory, -1]) == {memory: {first, second}}
    assert _ids(store.get_entities_for_memory(memory)) == [second, first]
    assert {
        (row["memory_id"], row["entity_id"]) for row in store.list_memory_entity_edges()
    } == {(memory, first), (memory, second)}
    assert store.archive_entities_batch([]) == 0
    assert store.archive_entities_batch([second]) == 1
    assert _ids(store.get_all_entities(min_heat=0.1)) == [first]
    assert set(_ids(store.get_all_entities(min_heat=0, include_archived=True))) == {
        first,
        second,
    }


def test_directional_reinforcement_and_bulk_deletion_do_not_duplicate_edges(store):
    first = store.insert_entity({"name": "alpha", "type": "concept"})
    second = store.insert_entity({"name": "beta", "type": "concept"})
    store.reinforce_or_create_relationship("missing", "beta")
    assert store.count_relationships() == 0
    store.reinforce_or_create_relationship("alpha", "beta", 0.4, "uses")
    store.reinforce_or_create_relationship("alpha", "beta", 0.3, "uses")
    store.reinforce_or_create_relationship("beta", "alpha", 0.2, "uses")
    outgoing = store.get_relationships_for_entity(first, "outgoing")
    incoming = store.get_relationships_for_entity(first, "incoming")
    assert len(outgoing) == len(incoming) == 1
    assert outgoing[0]["weight"] == pytest.approx(0.7)
    assert incoming[0]["weight"] == pytest.approx(0.2)
    assert outgoing[0]["target_name"] == "beta"
    assert incoming[0]["source_name"] == "beta"
    assert store.get_relationship_counts() == {first: 2, second: 2}
    assert store.get_entity_relationship_pairs() == {
        ("alpha", "beta"),
        ("beta", "alpha"),
    }
    edge = outgoing[0]["id"]
    assert store.update_relationships_weight_batch([]) == 0
    assert store.update_relationships_weight_batch([(edge, 1.2)]) == 1
    assert store.get_relationships_for_entity(first, "outgoing")[0][
        "weight"
    ] == pytest.approx(1.2)
    assert store.delete_relationships_batch([]) == 0
    assert store.delete_relationships_batch([edge]) == 1
    assert store.get_relationships_for_entity(first, "outgoing") == []
    assert _ids(store.get_all_relationships()) == [incoming[0]["id"]]


def test_chunked_hot_reads_keep_equal_heat_rows_and_obey_limit(store):
    low = store.insert_memory({"content": "low", "heat": 0.1})
    same_a = store.insert_memory({"content": "same a", "heat": 0.6})
    same_b = store.insert_memory({"content": "same b", "heat": 0.6})
    hot = store.insert_memory({"content": "hot", "heat": 0.9})
    benchmark = store.insert_memory(
        {"content": "benchmark", "heat": 1, "is_benchmark": True}
    )
    chunks = list(
        store.iter_hot_memories_chunked(
            min_heat=0.5, include_benchmarks=False, chunk_size=2
        )
    )
    assert [_ids(chunk) for chunk in chunks] == [[hot, same_b], [same_a]]
    assert [
        _ids(chunk)
        for chunk in store.iter_hot_memories_chunked(chunk_size=2, hard_limit=3)
    ] == [[benchmark, hot], [same_b]]
    assert list(store.iter_hot_memories_chunked(min_heat=2)) == []
    assert low not in _ids([row for chunk in chunks for row in chunk])


def test_decay_cursor_and_pool_kill_switch_both_exclude_stale_rows(store, monkeypatch):
    live = [store.insert_memory({"content": f"live {n}"}) for n in range(3)]
    stale = store.insert_memory({"content": "stale"})
    store.mark_memory_stale(stale)
    chunks = list(store.iter_memories_for_decay(chunk_size=2))
    assert [len(chunk) for chunk in chunks] == [2, 1]
    assert set(_ids([row for chunk in chunks for row in chunk])) == set(live)
    monkeypatch.setattr(get_memory_settings(), "POOL_DISABLED", True)
    fallback = list(store.iter_memories_for_decay(chunk_size=2))
    assert len(fallback) == 1
    assert set(_ids(fallback[0])) == set(live)


def test_hot_page_inclusive_real_threshold_keeps_equal_rows_across_pages(store):
    # source: SQL reproduction: 0.7::real::float8 is 0.699999988079071.
    # These fixture values straddle that inclusive storage-type boundary.
    store.insert_memory({"content": "below", "heat": 0.69})
    first = store.insert_memory({"content": "threshold first", "heat": 0.7})
    second = store.insert_memory({"content": "threshold second", "heat": 0.7})
    high = store.insert_memory({"content": "above", "heat": 0.8})
    chunks = list(store.iter_hot_memories_chunked(min_heat=0.7, chunk_size=2))
    assert [_ids(chunk) for chunk in chunks] == [[high, second], [first]]


def test_consolidation_batch_and_atomic_replay_return_persisted_values(store):
    older = store.insert_memory({"content": "older"})
    newer = store.insert_memory({"content": "newer"})
    store.update_memory_consolidation(older, "cortical", 8, 2, 0.4)
    store.update_memory_consolidation(newer, "cortical", 3, 0, 0.7)
    assert _ids(store.get_memories_by_stage("cortical", limit=1)) == [older]
    assert store.get_stage_counts() == {"cortical": 2}
    assert store.insert_stage_transitions_batch([]) == 0
    assert (
        store.insert_stage_transitions_batch(
            [
                {
                    "memory_id": older,
                    "from_stage": "hippocampal",
                    "to_stage": "cortical",
                    "hours_in_prev": 8,
                }
            ]
        )
        == 1
    )
    row = store._execute(
        "SELECT * FROM stage_transitions WHERE memory_id = %s", (older,)
    ).one()
    assert (row["from_stage"], row["to_stage"], row["trigger"]) == (
        "hippocampal",
        "cortical",
        "cascade",
    )
    replay = store.increment_replay_count(older)
    assert replay["replay_count"] == 3
    assert replay["hippocampal_dependency"] == pytest.approx(0.4)
    assert store.increment_replay_count(-1) is None
    store.update_memory_hippocampal_dependency(older, 0.2)
    assert store.get_memory(older)["hippocampal_dependency"] == pytest.approx(0.2)
    assert store.get_last_consolidation() is None
    assert store.log_consolidation({"memories_updated": 2, "duration_ms": 10}) > 0
    assert store.get_last_consolidation() is not None


def test_metadata_updates_keep_compression_original_and_clamp_extinction(store):
    memory = store.insert_memory({"content": "original"})
    store.update_memory_importance(memory, 0.8)
    store.update_memory_metamemory(memory, 3, 2, 0.7)
    store.update_memory_access(memory)
    store.set_memory_protected(memory)
    store.set_source_attribution(memory, "verified")
    store.update_forgetting_pressure_accum(memory, 0.3)
    store.update_memory_compression(memory, "short", None, 1, "original")
    store.update_memory_compression(memory, "shorter", None, 2)
    store.update_memory_extinction(memory, 5)
    row = store.get_memory(memory)
    assert row["access_count"] == 4
    assert row["useful_count"] == 2
    assert row["is_protected"] is True
    assert row["importance"] == pytest.approx(0.8)
    assert row["source_attribution"] == "verified"
    assert row["forgetting_pressure_accum"] == pytest.approx(0.3)
    assert (row["content"], row["original_content"], row["compression_level"]) == (
        "shorter",
        "original",
        2,
    )
    assert row["extinction_strength"] == 1
    store.update_memory_extinction(memory, -1)
    assert store.get_memory(memory)["extinction_strength"] == 0
    assert store.delete_memory(memory) is True
    assert store.delete_memory(memory) is False


def test_user_mood_upsert_is_user_specific_and_clamps_both_dimensions(store):
    assert store.get_user_mood(_MOOD_USER) is None
    assert store.get_user_mood_state(_MOOD_USER) is None
    store.set_user_mood(3, -4, user_id=_MOOD_USER)
    assert store.get_user_mood(_MOOD_USER) == 1
    assert store.get_user_mood_state(_MOOD_USER) == {"valence": 1, "arousal": -1}
    store.set_user_mood(-0.5, 0.2, user_id=_MOOD_USER)
    assert store.get_user_mood_state(_MOOD_USER) == pytest.approx(
        {"valence": -0.5, "arousal": 0.2}
    )
    assert store.get_user_mood_state(_UNSET_MOOD_USER) is None


def test_heat_bulk_writes_clamp_and_homeostatic_state_is_cohort_specific(store):
    first = store.insert_memory({"content": "first", "domain": "sql"})
    second = store.insert_memory({"content": "second", "domain": "other"})
    assert store.get_memories_by_ids([]) == {}
    assert set(store.get_memories_by_ids([first, first, -1])) == {first}
    store.update_memory_heat(first, 4)
    assert store.get_memory(first)["heat_base"] == 1
    assert store.update_memories_heat_batch([]) == 0
    assert store.update_memories_heat_batch([(first, -1), (second, 0.5)]) == 2
    assert store.get_memory(first)["heat_base"] == 0
    assert store.get_memory(second)["heat_base"] == 0.5
    assert store.get_homeostatic_factor("sql") == 1
    store.set_homeostatic_factor("sql", 0.5)
    assert store.get_homeostatic_factor("sql") == 0.5
    store.set_homeostatic_factor("sql", 0.25)
    assert store.get_homeostatic_factor("sql") == 0.25
    assert store.get_homeostatic_factor("other") == 1
    log_id = store.log_homeostatic_fold("sql", "auto", 0.25, 2)
    row = store._execute(
        "SELECT * FROM homeostatic_fold_log WHERE id = %s", (log_id,)
    ).one()
    assert (row["domain"], row["factor"], row["rows_folded"]) == ("sql", 0.25, 2)


def test_ingest_checkpoints_and_epochs_advance_without_reactivating_old_tasks(store):
    assert store.get_ingest_progress("one") == ("", 0)
    store.set_ingest_progress("one", "a", 3)
    store.set_ingest_progress("two", "z", 1)
    store.set_ingest_progress("one", "b", 5)
    assert store.get_ingest_progress("one") == ("b", 5)
    store.clear_ingest_progress("one")
    assert store.get_ingest_progress("one") == ("", 0)
    assert store.get_ingest_progress("two") == ("z", 1)
    assert store.get_active_checkpoint() is None
    assert store.get_current_epoch() == 0
    old = store.insert_checkpoint({"current_task": "before", "key_decisions": ["keep"]})
    current = store.insert_checkpoint(
        {"current_task": "after", "files_being_edited": ["quoted's.py"]}
    )
    checkpoint = store.get_active_checkpoint()
    assert checkpoint["id"] == current
    assert checkpoint["files_being_edited"] == ["quoted's.py"]
    assert store.increment_epoch() == 1
    assert store.increment_epoch() == 2
    assert store.get_current_epoch() == 2
    assert store.get_active_checkpoint()["id"] == current
    assert (
        store._execute("SELECT is_active FROM checkpoints WHERE id = %s", (old,)).one()[
            "is_active"
        ]
        is False
    )


def test_diagnostics_filter_stale_memories_and_track_grooming_tags(store):
    assert store.get_avg_heat() == 0
    assert store.signature_repeat_stats("") == (0, None)
    assert store.signature_repeat_stats("unknown") == (0, None)
    assert store.extinguished_count() == 0
    assert store.get_grooming_ages() == {
        "wiki": None,
        "distillation": None,
        "promotion": None,
    }
    live = store.insert_memory(
        {
            "content": "live",
            "heat": 0.5,
            "domain": "sql",
            "tags": ["lesson", "distill-of:source"],
        }
    )
    stale = store.insert_memory(
        {"content": "stale", "heat": 0, "domain": "other", "tags": ["promoted:source"]}
    )
    store.mark_memory_stale(stale)
    store.set_memory_protected(live)
    store.update_memory_access(live)
    store.update_memory_extinction(live, 1)
    store.update_memory_extinction(stale, 1)
    assert store.get_avg_heat() == 0.25
    counts = store.count_memories()
    assert {
        key: counts[key]
        for key in ("total", "active", "archived", "stale", "protected")
    } == {"total": 2, "active": 1, "archived": 1, "stale": 1, "protected": 1}
    assert store.extinguished_count() == 1
    assert store.get_domain_counts() == {"sql": 1}
    assert _ids(store.get_recently_accessed_memories()) == [live]
    ages = store.get_grooming_ages()
    assert ages["distillation"] is not None
    assert ages["promotion"] is None


def test_engram_slot_extension_preserves_activation_and_counts_exclusions(store):
    store.init_engram_slots(2)
    store.update_engram_slot(0, 0.75, "2026-01-01T00:00:00+00:00")
    store.init_engram_slots(1)
    store.init_engram_slots(3)
    slots = store.get_all_engram_slots()
    assert [row["slot_index"] for row in slots] == [0, 1, 2]
    assert slots[0]["excitability"] == 0.75
    assert store.get_engram_slot(-1) is None
    assert store.get_engram_slot(2)["excitability"] == 0.5
    first = store.insert_memory({"content": "one"})
    second = store.insert_memory({"content": "two"})
    store.assign_memory_slot(first, 0)
    store.assign_memory_slot(second, 0)
    assert set(_ids(store.get_memories_in_slot(0))) == {first, second}
    assert store.count_memories_in_slot(0) == 2
    assert store.count_memories_in_slot(0, exclude_id=first) == 1
    assert store.get_slot_occupancy() == {0: 2}


def test_oscillation_and_interference_updates_preserve_unspecified_state(store):
    assert store.load_oscillatory_state() is None
    store.save_oscillatory_state('{"phase": 1}')
    assert store.load_oscillatory_state() == '{"phase": 1}'
    store.save_oscillatory_state('{"phase": 2}')
    assert store.load_oscillatory_state() == '{"phase": 2}'
    memory = store.insert_memory(
        {"content": "state", "domain": "sql", "directory_context": "/repo"}
    )
    store.update_memory_interference(memory, 0.4, separation_index=0.25)
    store.update_memory_interference(memory, 0.8)
    row = store.get_memory(memory)
    assert row["interference_score"] == pytest.approx(0.8)
    assert row["separation_index"] == 0.25
    assert _ids(store.get_episodic_memories(domain="sql", directory="/repo")) == [
        memory
    ]
    assert store.get_episodic_memories(domain="other") == []
    store.update_memory_store_type(memory, "semantic")
    assert store.get_episodic_memories() == []
    assert _ids(store.get_semantic_memories(domain="sql")) == [memory]
    assert _ids(store.get_semantic_memories()) == [memory]


def test_domain_backfill_removes_orphan_tag_without_overwriting_assignment(store):
    from mcp_server.infrastructure import pg_store_memory_domain as domains

    pending = store.insert_memory({"content": "pending", "tags": ["keep"]})
    assigned = store.insert_memory({"content": "assigned", "domain": "existing"})
    with store.acquire_batch() as conn:
        assert _ids(domains.list_domainless_memories(conn, 10)) == [pending]
        assert domains.tag_memory_orphan(conn, pending) is True
        assert domains.tag_memory_orphan(conn, pending) is False
        assert domains.tag_memory_orphan(conn, assigned) is False
        assert domains.list_domainless_memories(conn, 10) == []
        assert _ids(
            domains.list_domainless_memories(conn, 10, include_orphans=True)
        ) == [pending]
        assert domains.update_memory_domain(conn, pending, "sql") is True
        assert domains.update_memory_domain(conn, assigned, "wrong") is False
        assert domains.update_memory_domain(conn, -1, "absent") is False
    assert store.get_memory(pending)["domain"] == "sql"
    assert store.get_memory(pending)["tags"] == ["keep"]
    assert store.get_memory(assigned)["domain"] == "existing"
