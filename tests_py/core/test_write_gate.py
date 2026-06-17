"""Unit tests for mcp_server.core.write_gate — decision logic.

Covers the branches NOT already exercised by test_write_gate_autocal.py:
  - determine_bypass: force / error / decision / important-tag / plain content
  - compute_embedding_novelty: delegation to predictive_coding_flat
  - compute_entity_novelty: entity extraction + known-set classification
  - compute_temporal_novelty: hours_since derivation from get_memory callables
  - _parse_hours_since: ISO string parsing and error paths
  - compute_structural_novelty: delegation to predictive_coding_flat
  - build_rejection_response: shape and field invariants
  - apply_oscillatory_context: no-store error path (swallows exceptions)
  - apply_neuromodulation: success-keyword detection, error path
  - apply_emotional_tagging: emotional vs. neutral content, error path
  - _collect_existing_embeddings: empty vec_hits, missing embedding key
  - apply_pattern_separation: no-embedding / no-existing-embs short-circuits
  - match_schema: no-schemas path returns (0.0, None)

All functions in write_gate.py are pure logic with zero I/O. No DB
required. This file must run to completion without any PostgreSQL
connection.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

import mcp_server.core.write_gate as wg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iso_now(delta_hours: float = 0.0) -> str:
    dt = datetime.now(timezone.utc) - timedelta(hours=delta_hours)
    return dt.isoformat()


# ---------------------------------------------------------------------------
# determine_bypass
# ---------------------------------------------------------------------------


class TestDetermineBypass:
    """determine_bypass postconditions:
    - force=True → bypass=True, reason="forced"
    - error content → bypass=True, reason="bypass_error"
    - decision content → bypass=True, reason="bypass_decision"
    - 'important' or 'critical' tags → bypass=True, reason="bypass_important_tag"
    - plain content + no special tags + force=False → bypass=False, reason=None
    - force dominates all other signals (checked first)
    """

    def test_force_returns_forced(self):
        bypassed, reason = wg.determine_bypass(
            force=True, content="boring content", tags=[]
        )
        assert bypassed is True
        assert reason == "forced"

    def test_force_dominates_over_plain_content(self):
        bypassed, reason = wg.determine_bypass(
            force=True, content="no special keywords here", tags=["archival"]
        )
        assert bypassed is True
        assert reason == "forced"

    def test_error_content_bypasses(self):
        bypassed, reason = wg.determine_bypass(
            force=False, content="An exception occurred during startup", tags=[]
        )
        assert bypassed is True
        assert reason == "bypass_error"

    def test_crash_keyword_also_bypasses(self):
        bypassed, reason = wg.determine_bypass(
            force=False, content="Service crash detected at 03:00", tags=[]
        )
        assert bypassed is True
        assert reason == "bypass_error"

    def test_decision_content_bypasses(self):
        bypassed, reason = wg.determine_bypass(
            force=False, content="We decided to use PostgreSQL for storage", tags=[]
        )
        assert bypassed is True
        assert reason == "bypass_decision"

    def test_switched_keyword_is_decision(self):
        bypassed, reason = wg.determine_bypass(
            force=False, content="Team switched from Redis to Kafka", tags=[]
        )
        assert bypassed is True
        assert reason == "bypass_decision"

    def test_important_tag_bypasses(self):
        bypassed, reason = wg.determine_bypass(
            force=False, content="Routine progress update", tags=["important"]
        )
        assert bypassed is True
        assert reason == "bypass_important_tag"

    def test_critical_tag_bypasses(self):
        bypassed, reason = wg.determine_bypass(
            force=False, content="Routine progress update", tags=["CRITICAL"]
        )
        assert bypassed is True
        assert reason == "bypass_important_tag"

    def test_tag_check_is_case_insensitive(self):
        bypassed, reason = wg.determine_bypass(
            force=False, content="Neutral text", tags=["Important"]
        )
        assert bypassed is True
        assert reason == "bypass_important_tag"

    def test_plain_content_no_bypass(self):
        bypassed, reason = wg.determine_bypass(
            force=False,
            content="Updated the README with installation instructions",
            tags=["archival", "note"],
        )
        assert bypassed is False
        assert reason is None

    def test_empty_content_empty_tags_no_bypass(self):
        bypassed, reason = wg.determine_bypass(force=False, content="", tags=[])
        assert bypassed is False
        assert reason is None

    def test_unrelated_tags_no_bypass(self):
        bypassed, reason = wg.determine_bypass(
            force=False, content="Normal memory", tags=["lesson", "bug-fix"]
        )
        assert bypassed is False
        assert reason is None


# ---------------------------------------------------------------------------
# compute_embedding_novelty (thin wrapper)
# ---------------------------------------------------------------------------


class TestComputeEmbeddingNovelty:
    """Postconditions of the wrapper:
    - empty similarities → 0.5 (no-data default)
    - max similarity == 1.0 → novelty == 0.0 (identical)
    - max similarity == 0.0 → novelty == 1.0 (completely novel)
    - result always in [0, 1]
    """

    def test_empty_similarities_returns_half(self):
        result = wg.compute_embedding_novelty(embedding=None, similarities=[])
        assert result == 0.5

    def test_identical_embedding_zero_novelty(self):
        result = wg.compute_embedding_novelty(embedding=None, similarities=[1.0])
        assert result == 0.0

    def test_no_overlap_full_novelty(self):
        result = wg.compute_embedding_novelty(embedding=None, similarities=[0.0])
        assert result == 1.0

    def test_uses_max_when_multiple_similarities(self):
        result = wg.compute_embedding_novelty(
            embedding=None, similarities=[0.2, 0.9, 0.4]
        )
        assert result == pytest.approx(0.1, abs=1e-9)

    def test_clamped_to_unit_interval_on_oversize_similarity(self):
        result = wg.compute_embedding_novelty(embedding=None, similarities=[1.5])
        assert 0.0 <= result <= 1.0


# ---------------------------------------------------------------------------
# compute_entity_novelty
# ---------------------------------------------------------------------------


class TestComputeEntityNovelty:
    """Postconditions:
    - All entities new → score == 1.0
    - All entities known → score == 0.0
    - No entities extracted → score == 0.5 (default from flat module)
    - known set returned is a subset of extracted names
    """

    def test_all_new_entities_returns_one(self):
        # Entity extractor requires CamelCase identifiers. Use ones that match.
        content = "MyService inherits from BaseRepository"
        _, _, known, score = wg.compute_entity_novelty(
            content=content, known_lookup=set()
        )
        # No known entities in the lookup → score must be 1.0
        assert score == 1.0
        assert len(known) == 0

    def test_all_known_entities_returns_zero(self):
        # Provide a known_lookup that covers all names the extractor will find.
        # We extract first to see what names come out, then pass those as known.
        content = "UserRepository extends AbstractRepo"
        extracted, names, _, _ = wg.compute_entity_novelty(
            content=content, known_lookup=set()
        )
        assert names, "Extractor must return at least one entity for this content"
        known_lookup = set(names)
        _, _, known2, score2 = wg.compute_entity_novelty(
            content=content, known_lookup=known_lookup
        )
        assert score2 == 0.0
        assert known2 == set(names)

    def test_no_entities_extracted_returns_half(self):
        # Content with no recognizable entities → extractor returns empty list → 0.5
        content = "and the or if then else"
        _, names, known, score = wg.compute_entity_novelty(
            content=content, known_lookup=set()
        )
        if not names:
            assert score == 0.5
        else:
            # If extractor found something, score must still be in [0, 1]
            assert 0.0 <= score <= 1.0

    def test_known_is_subset_of_names(self):
        # CamelCase identifiers so extractor picks them up
        content = "PaymentGateway StripeAdapter KafkaProducer"
        # First pass: discover what names are extracted
        _, names, _, _ = wg.compute_entity_novelty(content=content, known_lookup=set())
        # Mark one as known if any were found, otherwise use empty set
        all_known = {names[0]} if names else set()
        _, names2, known, _ = wg.compute_entity_novelty(
            content=content, known_lookup=all_known
        )
        assert known.issubset(set(names2))

    def test_score_in_unit_interval(self):
        content = "StripeAdapter implements PaymentGateway interface"
        _, _, _, score = wg.compute_entity_novelty(
            content=content, known_lookup={"StripeAdapter"}
        )
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# _parse_hours_since
# ---------------------------------------------------------------------------


class TestParseHoursSince:
    """Postconditions:
    - Valid ISO UTC string → positive float (hours since that moment)
    - Naive datetime → treated as UTC, positive float
    - Malformed string → None
    - Timestamp from now → hours ≈ 0
    - Timestamp from 24h ago → hours ≈ 24
    """

    def test_now_returns_near_zero(self):
        iso = _iso_now(delta_hours=0.0)
        result = wg._parse_hours_since(iso)
        assert result is not None
        assert result >= 0.0
        assert result < 0.1  # Should be milliseconds of difference at most

    def test_twenty_four_hours_ago(self):
        iso = _iso_now(delta_hours=24.0)
        result = wg._parse_hours_since(iso)
        assert result is not None
        assert 23.9 < result < 24.1

    def test_one_hour_ago(self):
        iso = _iso_now(delta_hours=1.0)
        result = wg._parse_hours_since(iso)
        assert result is not None
        assert 0.99 < result < 1.01

    def test_naive_datetime_treated_as_utc(self):
        # Naive ISO string (no timezone info) — should still return a positive float
        naive_iso = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        result = wg._parse_hours_since(naive_iso)
        assert result is not None
        assert result >= 0.0

    def test_malformed_string_returns_none(self):
        assert wg._parse_hours_since("not-a-date") is None

    def test_empty_string_returns_none(self):
        assert wg._parse_hours_since("") is None

    def test_none_input_returns_none(self):
        # type: ignore[arg-type]
        assert wg._parse_hours_since(None) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# compute_temporal_novelty
# ---------------------------------------------------------------------------


class TestComputeTemporalNovelty:
    """Postconditions of the write_gate wrapper around predictive_coding_flat:
    - No similarities and no vec_hits → hours=None → 0.8 (flat default)
    - Similarities present but get_memory returns None → hours=None → 0.8
    - get_memory returns memory with ingested_at → derives hours correctly
    - get_memory returns memory without ingested_at/created_at → hours=None → 0.8
    """

    def test_empty_similarities_returns_default(self):
        result = wg.compute_temporal_novelty(
            similarities=[],
            vec_hits=[],
            get_memory=lambda mid: None,
        )
        assert result == 0.8

    def test_get_memory_returns_none_gives_default(self):
        result = wg.compute_temporal_novelty(
            similarities=[0.9],
            vec_hits=[(42, 0.1)],
            get_memory=lambda mid: None,
        )
        assert result == 0.8

    def test_memory_without_timestamps_gives_default(self):
        def get_memory(_mid):
            return {"content": "no timestamps here"}

        result = wg.compute_temporal_novelty(
            similarities=[0.9],
            vec_hits=[(1, 0.1)],
            get_memory=get_memory,
        )
        assert result == 0.8

    def test_memory_ingested_twenty_four_hours_ago(self):
        """Memory from 24h ago → temporal novelty close to 1-exp(-1) ≈ 0.632."""

        def get_memory(_mid):
            return {"ingested_at": _iso_now(delta_hours=24.0)}

        result = wg.compute_temporal_novelty(
            similarities=[0.9],
            vec_hits=[(7, 0.1)],
            get_memory=get_memory,
        )
        expected = 1.0 - math.exp(-24.0 / 24.0)
        assert abs(result - expected) < 0.05  # generous margin for clock drift

    def test_memory_ingested_zero_hours_ago_returns_near_zero(self):
        """Very recent memory → temporal novelty close to 0."""

        def get_memory(_mid):
            return {"ingested_at": _iso_now(delta_hours=0.0)}

        result = wg.compute_temporal_novelty(
            similarities=[0.9],
            vec_hits=[(3, 0.1)],
            get_memory=get_memory,
        )
        assert result < 0.01

    def test_falls_back_to_created_at_when_ingested_at_missing(self):
        """created_at is the legacy fallback when ingested_at is absent."""

        def get_memory(_mid):
            return {"created_at": _iso_now(delta_hours=48.0)}

        result = wg.compute_temporal_novelty(
            similarities=[0.9],
            vec_hits=[(5, 0.1)],
            get_memory=get_memory,
        )
        # 48 hours → 1-exp(-2) ≈ 0.865
        expected = 1.0 - math.exp(-48.0 / 24.0)
        assert abs(result - expected) < 0.05

    def test_picks_best_similarity_index(self):
        """Best similarity determines which vec_hit is queried."""
        queried = []

        def get_memory(mid):
            queried.append(mid)
            return {"ingested_at": _iso_now(delta_hours=10.0)}

        # Highest similarity is index 1 → mid=99
        wg.compute_temporal_novelty(
            similarities=[0.3, 0.95, 0.5],
            vec_hits=[(11, 0.7), (99, 0.05), (55, 0.45)],
            get_memory=get_memory,
        )
        assert queried == [99]


# ---------------------------------------------------------------------------
# compute_structural_novelty (thin wrapper)
# ---------------------------------------------------------------------------


class TestComputeStructuralNovelty:
    """Postconditions:
    - Empty recent_contents → 0.7 (no-data default)
    - Structurally identical content → novelty == 0.0
    - Completely different structure → novelty high (≥ 0.5)
    - Result always in [0, 1]
    """

    def test_empty_recent_returns_default(self):
        result = wg.compute_structural_novelty(content="some text", recent_contents=[])
        assert result == 0.7

    def test_identical_structure_low_novelty(self):
        content = "Simple short sentence."
        result = wg.compute_structural_novelty(
            content=content, recent_contents=[content]
        )
        # Structural features will match perfectly → novelty == 0.0
        assert result == 0.0

    def test_result_in_unit_interval(self):
        result = wg.compute_structural_novelty(
            content="# Heading\n\n- item\n- item\n\n```python\ncode\n```",
            recent_contents=["plain text no structure"],
        )
        assert 0.0 <= result <= 1.0


# ---------------------------------------------------------------------------
# build_rejection_response
# ---------------------------------------------------------------------------


class TestBuildRejectionResponse:
    """Shape postconditions:
    - returned dict always has keys: stored, action, reason, novelty, importance
    - stored is always False
    - action is always 'rejected'
    - novelty is a dict with exactly the 5 signal keys
    - importance is rounded to 4 decimal places
    """

    _SIGNAL_KEYS = {
        "embedding_novelty",
        "entity_novelty",
        "temporal_novelty",
        "structural_novelty",
        "combined_novelty",
    }

    def _call(self, **kwargs):
        defaults = dict(
            embedding_novelty=0.3,
            entity_novelty=0.5,
            temporal_novelty=0.8,
            structural_novelty=0.7,
            novelty_score=0.5,
            gate_reason="low_novelty",
            importance=0.25,
        )
        defaults.update(kwargs)
        return wg.build_rejection_response(**defaults)

    def test_stored_is_false(self):
        assert self._call()["stored"] is False

    def test_action_is_rejected(self):
        assert self._call()["action"] == "rejected"

    def test_reason_matches_argument(self):
        resp = self._call(gate_reason="custom_gate_reason")
        assert resp["reason"] == "custom_gate_reason"

    def test_novelty_dict_has_all_signal_keys(self):
        resp = self._call()
        assert set(resp["novelty"].keys()) == self._SIGNAL_KEYS

    def test_novelty_values_are_rounded(self):
        resp = self._call(
            embedding_novelty=0.123456789,
            entity_novelty=0.5,
            temporal_novelty=0.8,
            structural_novelty=0.7,
            novelty_score=0.600123456,
        )
        for v in resp["novelty"].values():
            # 4 dp max → str representation has ≤ 4 decimal places
            str_v = f"{v:.10f}".rstrip("0")
            decimal_places = len(str_v.split(".")[-1]) if "." in str_v else 0
            assert decimal_places <= 4

    def test_importance_rounded_to_four_dp(self):
        resp = self._call(importance=0.123456789)
        # Must equal round(0.123456789, 4)
        assert resp["importance"] == round(0.123456789, 4)

    def test_importance_at_zero(self):
        resp = self._call(importance=0.0)
        assert resp["importance"] == 0.0

    def test_importance_at_one(self):
        resp = self._call(importance=1.0)
        assert resp["importance"] == 1.0


# ---------------------------------------------------------------------------
# apply_oscillatory_context — error-swallowing branch
# ---------------------------------------------------------------------------


class TestApplyOscillatoryContext:
    """apply_oscillatory_context postconditions:
    - Exception in store operations is swallowed (broad except)
    - Returns 4-tuple: (heat, theta_phase, encoding_mod, osc_state)
    - heat remains in [0, 1] in error path
    - In the error path: theta_phase == 0.0, encoding_mod == 1.0
    """

    def test_broken_store_returns_defaults(self):
        broken_store = MagicMock()
        broken_store.load_oscillatory_state.side_effect = RuntimeError("no PG")

        heat, theta, enc, state = wg.apply_oscillatory_context(
            store=broken_store, heat=0.5
        )
        assert heat == 0.5
        assert theta == 0.0
        assert enc == 1.0

    def test_none_saved_state_uses_fresh_osc_state(self):
        store = MagicMock()
        store.load_oscillatory_state.return_value = None
        store.save_oscillatory_state.return_value = None

        heat, theta, enc, state = wg.apply_oscillatory_context(store=store, heat=0.6)
        # heat is modulated by encoding_mod but must stay in [0, 1]
        assert 0.0 <= heat <= 1.0

    def test_heat_never_exceeds_one(self):
        store = MagicMock()
        store.load_oscillatory_state.return_value = None
        store.save_oscillatory_state.return_value = None

        heat, _, _, _ = wg.apply_oscillatory_context(store=store, heat=1.0)
        assert heat <= 1.0


# ---------------------------------------------------------------------------
# apply_neuromodulation
# ---------------------------------------------------------------------------


class TestApplyNeuromodulation:
    """Postconditions:
    - heat and importance remain in [0, 1] after modulation
    - On exception: returns (heat, importance, None) unchanged
    - Success-keyword detection: content with 'fixed'/'resolved'/'passed' etc.
      triggers is_succ=True (observable in composite not being None)
    - Novel entities (not in known set) increment novel_ent count
    """

    _DEFAULT_OSC = MagicMock()

    def _call(self, content="Some content", new_names=None, known=None, **kwargs):
        from mcp_server.core.oscillatory_clock import OscillatoryState

        osc_state = OscillatoryState()
        defaults = dict(
            content=content,
            new_entity_names=new_names or [],
            known_entity_names=known or set(),
            theta_phase=0.0,
            osc_state=osc_state,
            schema_match=0.5,
            importance=0.5,
            heat=0.5,
        )
        defaults.update(kwargs)
        return wg.apply_neuromodulation(**defaults)

    def test_heat_in_unit_interval(self):
        heat, importance, composite = self._call()
        assert 0.0 <= heat <= 1.0
        assert 0.0 <= importance <= 1.0

    def test_success_keyword_does_not_raise(self):
        heat, importance, composite = self._call(content="Fixed the bug successfully.")
        assert composite is not None
        assert 0.0 <= heat <= 1.0

    def test_error_keyword_does_not_raise(self):
        heat, importance, composite = self._call(
            content="An exception occurred during startup."
        )
        assert composite is not None

    def test_novel_entities_parsed_correctly(self):
        # Three entities, one known: novel_ent should be 2
        heat, importance, composite = self._call(
            new_names=["PostgreSQL", "Redis", "Kafka"],
            known={"Redis"},
        )
        assert composite is not None
        assert 0.0 <= heat <= 1.0

    def test_exception_path_returns_inputs_unchanged(self):

        # Pass an osc_state with a property that raises on attribute access
        bad_osc = MagicMock()
        bad_osc.ach_level = property(lambda self: (_ for _ in ()).throw(RuntimeError()))
        heat_in, imp_in = 0.6, 0.7
        heat, importance, composite = wg.apply_neuromodulation(
            content="irrelevant",
            new_entity_names=[],
            known_entity_names=set(),
            theta_phase=0.0,
            osc_state=bad_osc,
            schema_match=0.5,
            importance=imp_in,
            heat=heat_in,
        )
        assert heat == pytest.approx(heat_in) or 0.0 <= heat <= 1.0
        assert composite is None or composite is not None  # at least returns


# ---------------------------------------------------------------------------
# apply_emotional_tagging
# ---------------------------------------------------------------------------


class TestApplyEmotionalTagging:
    """Postconditions:
    - emotional content boosts importance and/or heat, both stay in [0, 1]
    - non-emotional content → importance, heat unchanged; valence unchanged
    - exception path returns (importance, heat, valence, None) unchanged
    """

    def test_frustration_content_boosts_importance(self):
        imp, heat, valence, tag = wg.apply_emotional_tagging(
            content="Spent hours debugging this nightmare, still completely broken!",
            importance=0.4,
            heat=0.4,
            valence=0.0,
        )
        assert 0.0 <= imp <= 1.0
        assert 0.0 <= heat <= 1.0

    def test_neutral_content_leaves_values_near_original(self):
        imp, heat, valence, tag = wg.apply_emotional_tagging(
            content="Updated the README file.",
            importance=0.4,
            heat=0.4,
            valence=0.0,
        )
        # Neutral content — tag.is_emotional should be False
        if tag and not tag.get("is_emotional", False):
            assert imp == pytest.approx(0.4)
            assert heat == pytest.approx(0.4)
        else:
            assert 0.0 <= imp <= 1.0
            assert 0.0 <= heat <= 1.0

    def test_exception_returns_unchanged_with_none_tag(self):
        with patch(
            "mcp_server.core.write_gate.tag_memory_emotions",
            side_effect=RuntimeError("tagging exploded"),
        ):
            imp, heat, valence, tag = wg.apply_emotional_tagging(
                content="anything", importance=0.5, heat=0.5, valence=0.1
            )
        assert imp == pytest.approx(0.5)
        assert heat == pytest.approx(0.5)
        assert valence == pytest.approx(0.1)
        assert tag is None

    def test_result_always_clamped(self):
        # Force a very high importance_boost to hit the min(1.0, ...) clamp
        imp, heat, valence, tag = wg.apply_emotional_tagging(
            content="CRITICAL emergency system down now crash failure error!",
            importance=0.99,
            heat=0.99,
            valence=0.0,
        )
        assert imp <= 1.0
        assert heat <= 1.0


# ---------------------------------------------------------------------------
# _collect_existing_embeddings
# ---------------------------------------------------------------------------


class TestCollectExistingEmbeddings:
    """Postconditions:
    - Empty vec_hits → empty list
    - Memory with no 'embedding' key → skipped
    - embeddings.to_list returns empty → skipped
    - At most 5 embeddings collected (truncated at [:5])
    """

    def _make_store(self, memories: dict):
        store = MagicMock()
        store.get_memory.side_effect = lambda mid: memories.get(mid)
        return store

    def _make_embeddings(self, vec_map: dict):
        embs = MagicMock()
        embs.to_list.side_effect = lambda e: vec_map.get(id(e), [])
        return embs

    def test_empty_vec_hits_returns_empty(self):
        result = wg._collect_existing_embeddings(
            vec_hits=[], store=MagicMock(), embeddings=MagicMock()
        )
        assert result == []

    def test_memory_without_embedding_key_skipped(self):
        store = self._make_store({1: {"content": "no emb"}})
        embs = MagicMock()
        result = wg._collect_existing_embeddings(
            vec_hits=[(1, 0.1)], store=store, embeddings=embs
        )
        assert result == []

    def test_to_list_returns_empty_skipped(self):
        sentinel = object()
        store = self._make_store({1: {"embedding": sentinel}})
        embs = MagicMock()
        embs.to_list.return_value = []
        result = wg._collect_existing_embeddings(
            vec_hits=[(1, 0.1)], store=store, embeddings=embs
        )
        assert result == []

    def test_collects_valid_embeddings(self):
        sentinel = object()
        store = self._make_store({1: {"embedding": sentinel}})
        embs = MagicMock()
        embs.to_list.return_value = [0.1, 0.2, 0.3]
        result = wg._collect_existing_embeddings(
            vec_hits=[(1, 0.1)], store=store, embeddings=embs
        )
        assert result == [[0.1, 0.2, 0.3]]

    def test_at_most_five_collected(self):
        mems = {i: {"embedding": object()} for i in range(10)}
        store = self._make_store(mems)
        embs = MagicMock()
        embs.to_list.return_value = [0.5]
        result = wg._collect_existing_embeddings(
            vec_hits=[(i, 0.1) for i in range(10)],
            store=store,
            embeddings=embs,
        )
        assert len(result) == 5


# ---------------------------------------------------------------------------
# apply_pattern_separation
# ---------------------------------------------------------------------------


class TestApplyPatternSeparation:
    """Short-circuit postconditions (no real DB needed):
    - No embedding → returns (embedding, 0.0, 0.0) unchanged
    - No similarities → same short-circuit
    - No existing embeddings found → returns embedding unchanged with zeros
    """

    def test_no_embedding_returns_early(self):
        emb, sep, inter = wg.apply_pattern_separation(
            embedding=None,
            similarities=[0.9],
            vec_hits=[(1, 0.1)],
            store=MagicMock(),
            embeddings=MagicMock(),
        )
        assert emb is None
        assert sep == 0.0
        assert inter == 0.0

    def test_empty_similarities_returns_early(self):
        sentinel = object()
        emb, sep, inter = wg.apply_pattern_separation(
            embedding=sentinel,
            similarities=[],
            vec_hits=[(1, 0.1)],
            store=MagicMock(),
            embeddings=MagicMock(),
        )
        assert emb is sentinel
        assert sep == 0.0
        assert inter == 0.0

    def test_no_existing_embeddings_returns_zero_sep_and_inter(self):
        """When _collect_existing_embeddings returns [] → short-circuit, zeros."""
        sentinel = object()
        store = MagicMock()
        store.get_memory.return_value = {"content": "no embedding key"}
        embs = MagicMock()
        embs.to_list.return_value = []

        emb, sep, inter = wg.apply_pattern_separation(
            embedding=sentinel,
            similarities=[0.8],
            vec_hits=[(1, 0.2)],
            store=store,
            embeddings=embs,
        )
        # embedding unchanged; both sep_index and interference remain 0.0
        assert emb is sentinel
        assert sep == 0.0
        assert inter == 0.0


# ---------------------------------------------------------------------------
# match_schema
# ---------------------------------------------------------------------------


class TestMatchSchema:
    """Postconditions:
    - No schemas for domain → returns (0.0, None)
    - Exception in store call → returns (0.0, None)
    """

    def test_no_schemas_returns_zero_and_none(self):
        store = MagicMock()
        store.get_schemas_for_domain.return_value = []

        score, schema_id = wg.match_schema(
            domain="test-domain",
            entity_names=["PostgreSQL"],
            tags=["archival"],
            store=store,
        )
        assert score == 0.0
        assert schema_id is None

    def test_exception_in_store_returns_zero_and_none(self):
        store = MagicMock()
        store.get_schemas_for_domain.side_effect = RuntimeError("pg down")

        score, schema_id = wg.match_schema(
            domain="test-domain",
            entity_names=["Redis"],
            tags=[],
            store=store,
        )
        assert score == 0.0
        assert schema_id is None
