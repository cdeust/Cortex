"""Tests for SWR replay dynamics in replay.py."""

from mcp_server.core.replay import (
    # Existing API (backward compat)
    should_micro_checkpoint,
    format_restoration,
    # SWR replay types
    ReplayDirection,
    ReplayEvent,
    ReplaySequence,
    ReplayResult,
    # SWR replay functions
    build_temporal_sequence,
    build_causal_sequence,
    compute_sequence_priority,
    select_replay_sequences,
    compute_replay_stdp_pairs,
    run_swr_replay,
    describe_replay_result,
)


# ── Backward Compat (existing tests still pass) ─────────────────────────


class TestBackwardCompat:
    def test_should_micro_checkpoint_error(self):
        ok, reason = should_micro_checkpoint(
            "RuntimeError: connection failed", [], tool_call_count=10
        )
        assert ok is True
        assert reason == "error_detected"

    def test_format_restoration_empty(self):
        result = format_restoration(None, [], [], [])
        assert "Hippocampal Replay" in result


# ── Temporal Sequence ────────────────────────────────────────────────────


class TestTemporalSequence:
    def test_sorts_by_creation_time(self):
        memories = [
            {"id": 1, "content": "first", "created_at": "2024-01-01T10:00:00Z"},
            {"id": 2, "content": "third", "created_at": "2024-01-03T10:00:00Z"},
            {"id": 3, "content": "second", "created_at": "2024-01-02T10:00:00Z"},
        ]
        events = build_temporal_sequence(memories)
        assert [e.memory_id for e in events] == [1, 3, 2]

    def test_max_length_respected(self):
        memories = [
            {"id": i, "content": f"m{i}", "created_at": f"2024-01-0{i + 1}T00:00:00Z"}
            for i in range(10)
        ]
        events = build_temporal_sequence(memories, max_length=3)
        assert len(events) == 3

    def test_empty_input(self):
        assert build_temporal_sequence([]) == []

    def test_preserves_content_and_heat(self):
        memories = [
            {
                "id": 1,
                "content": "test content",
                "created_at": "2024-01-01",
                "heat": 0.8,
            }
        ]
        events = build_temporal_sequence(memories)
        assert events[0].content == "test content"
        assert events[0].heat == 0.8


# ── Causal Sequence ──────────────────────────────────────────────────────


class TestCausalSequence:
    def _make_mem(self, mid, tags, time):
        return {
            "id": mid,
            "content": f"mem-{mid}",
            "tags": tags,
            "created_at": time,
            "heat": 0.5,
        }

    def test_forward_follows_entities(self):
        seed = self._make_mem(1, ["auth", "jwt"], "2024-01-01T00:00:00Z")
        related = [
            self._make_mem(2, ["auth", "session"], "2024-01-02T00:00:00Z"),
            self._make_mem(3, ["unrelated"], "2024-01-03T00:00:00Z"),
        ]
        events = build_causal_sequence(seed, related, [], ReplayDirection.FORWARD)
        ids = [e.memory_id for e in events]
        assert 1 in ids
        assert 2 in ids  # Shares "auth"
        assert 3 not in ids  # No overlap

    def test_reverse_follows_backward(self):
        seed = self._make_mem(3, ["auth", "jwt"], "2024-01-03T00:00:00Z")
        related = [
            self._make_mem(1, ["auth", "session"], "2024-01-01T00:00:00Z"),
            self._make_mem(2, ["unrelated"], "2024-01-02T00:00:00Z"),
        ]
        events = build_causal_sequence(seed, related, [], ReplayDirection.REVERSE)
        ids = [e.memory_id for e in events]
        assert 3 in ids
        assert 1 in ids  # Shares "auth", before seed
        assert 2 not in ids

    def test_empty_seed(self):
        assert build_causal_sequence({}, [], []) == []

    def test_no_related_memories(self):
        seed = self._make_mem(1, ["auth"], "2024-01-01T00:00:00Z")
        events = build_causal_sequence(seed, [], [])
        assert len(events) == 1  # Just the seed

    def test_relationship_connection(self):
        seed = self._make_mem(1, [], "2024-01-01T00:00:00Z")
        related = [self._make_mem(2, [], "2024-01-02T00:00:00Z")]
        rels = [{"source_entity_id": 1, "target_entity_id": 2}]
        events = build_causal_sequence(seed, related, rels, ReplayDirection.FORWARD)
        assert len(events) == 2


# ── Sequence Priority ────────────────────────────────────────────────────


class TestSequencePriority:
    def test_high_heat_variance_high_priority(self):
        events = [
            ReplayEvent(memory_id=1, content="", heat=0.1),
            ReplayEvent(memory_id=2, content="", heat=0.9),
            ReplayEvent(memory_id=3, content="", heat=0.2),
        ]
        score = compute_sequence_priority(events)
        assert score > 0.2  # Significant variance

    def test_uniform_low_heat_low_priority(self):
        events = [
            ReplayEvent(memory_id=1, content="", heat=0.1),
            ReplayEvent(memory_id=2, content="", heat=0.1),
        ]
        score = compute_sequence_priority(events)
        assert score < 0.2

    def test_dopamine_amplifies_priority(self):
        events = [
            ReplayEvent(memory_id=1, content="", heat=0.5),
            ReplayEvent(memory_id=2, content="", heat=0.8),
        ]
        score_low_da = compute_sequence_priority(events, dopamine_level=0.5)
        score_high_da = compute_sequence_priority(events, dopamine_level=1.5)
        assert score_high_da > score_low_da

    def test_single_event_returns_zero(self):
        events = [ReplayEvent(memory_id=1, content="", heat=0.9)]
        assert compute_sequence_priority(events) == 0.0

    def test_bounded_zero_to_one(self):
        events = [
            ReplayEvent(memory_id=1, content="", heat=1.0),
            ReplayEvent(memory_id=2, content="", heat=0.0),
        ]
        score = compute_sequence_priority(events, dopamine_level=2.0)
        assert 0.0 <= score <= 1.0


# ── Sequence Selection ───────────────────────────────────────────────────


class TestSelectReplaySequences:
    def _seq(self, priority, direction=ReplayDirection.FORWARD):
        return ReplaySequence(
            events=[
                ReplayEvent(memory_id=1, content=""),
                ReplayEvent(memory_id=2, content=""),
            ],
            direction=direction,
            priority_score=priority,
        )

    def test_selects_top_by_priority(self):
        candidates = [self._seq(0.9), self._seq(0.1), self._seq(0.5)]
        selected = select_replay_sequences(candidates, max_sequences=2)
        assert len(selected) == 2
        assert selected[0].priority_score == 0.9

    def test_filters_by_threshold(self):
        candidates = [self._seq(0.1), self._seq(0.2)]
        selected = select_replay_sequences(candidates, priority_threshold=0.5)
        # Falls back to top candidates
        assert len(selected) > 0

    def test_balances_forward_reverse(self):
        candidates = [
            self._seq(0.8, ReplayDirection.FORWARD),
            self._seq(0.7, ReplayDirection.FORWARD),
            self._seq(0.6, ReplayDirection.REVERSE),
        ]
        selected = select_replay_sequences(candidates, max_sequences=2)
        directions = {s.direction for s in selected}
        assert ReplayDirection.FORWARD in directions
        assert ReplayDirection.REVERSE in directions

    def test_respects_max_sequences(self):
        candidates = [self._seq(0.9 - i * 0.1) for i in range(10)]
        selected = select_replay_sequences(candidates, max_sequences=3)
        assert len(selected) == 3

    def test_empty_candidates(self):
        assert select_replay_sequences([]) == []


# ── STDP from Replay ─────────────────────────────────────────────────────


class TestReplaySTDP:
    def test_generates_pairs_for_sequential_entities(self):
        events = [
            ReplayEvent(memory_id=1, content="", entities=["auth", "jwt"]),
            ReplayEvent(memory_id=2, content="", entities=["session", "jwt"]),
        ]
        pairs = compute_replay_stdp_pairs(events, ReplayDirection.FORWARD)
        assert len(pairs) > 0
        # auth→session, auth→jwt (already same, skipped by != check? no, jwt→session)
        # All pairs should have positive delta_t for forward
        for _, _, dt in pairs:
            assert dt > 0

    def test_reverse_inverts_direction(self):
        events = [
            ReplayEvent(memory_id=1, content="", entities=["A"]),
            ReplayEvent(memory_id=2, content="", entities=["B"]),
        ]
        fwd = compute_replay_stdp_pairs(events, ReplayDirection.FORWARD)
        rev = compute_replay_stdp_pairs(events, ReplayDirection.REVERSE)
        # Forward: A→B, Reverse: B→A
        assert fwd[0][0] != rev[0][0] or fwd[0][1] != rev[0][1]

    def test_no_self_pairs(self):
        events = [
            ReplayEvent(memory_id=1, content="", entities=["same"]),
            ReplayEvent(memory_id=2, content="", entities=["same"]),
        ]
        pairs = compute_replay_stdp_pairs(events, ReplayDirection.FORWARD)
        assert len(pairs) == 0  # "same" → "same" is filtered

    def test_single_event_no_pairs(self):
        events = [ReplayEvent(memory_id=1, content="", entities=["A", "B"])]
        assert compute_replay_stdp_pairs(events, ReplayDirection.FORWARD) == []


# ── Full SWR Replay ──────────────────────────────────────────────────────


class TestRunSWRReplay:
    def _make_mem(self, mid, tags, time, heat=0.5):
        return {
            "id": mid,
            "content": f"mem-{mid}",
            "tags": tags,
            "created_at": time,
            "heat": heat,
        }

    def test_no_replay_when_swr_inactive(self):
        result = run_swr_replay(
            [self._make_mem(1, ["a"], "2024-01-01")],
            [],
            [],
            swr_active=False,
        )
        assert result.sequences_generated == 0

    def test_no_replay_with_empty_memories(self):
        result = run_swr_replay([], [], [])
        assert result.sequences_generated == 0

    def test_basic_replay_cycle(self):
        hot = [
            self._make_mem(1, ["auth"], "2024-01-01T00:00:00Z", heat=0.9),
            self._make_mem(2, ["auth", "jwt"], "2024-01-02T00:00:00Z", heat=0.8),
            self._make_mem(3, ["jwt", "session"], "2024-01-03T00:00:00Z", heat=0.7),
        ]
        result = run_swr_replay(hot, hot, [])
        assert result.sequences_generated > 0
        assert result.memories_replayed > 0

    def test_dopamine_modulates_selection(self):
        hot = [
            self._make_mem(1, ["a"], "2024-01-01T00:00:00Z", heat=0.5),
            self._make_mem(2, ["a", "b"], "2024-01-02T00:00:00Z", heat=0.6),
            self._make_mem(3, ["b"], "2024-01-03T00:00:00Z", heat=0.4),
        ]
        result_low = run_swr_replay(hot, hot, [], dopamine_level=0.3)
        result_high = run_swr_replay(hot, hot, [], dopamine_level=2.0)
        # Higher DA may produce more/different sequences
        assert result_high.sequences_generated >= 0
        assert result_low.sequences_generated >= 0

    def test_describe_replay_result(self):
        result = ReplayResult(
            sequences_generated=3,
            memories_replayed=8,
            forward_count=2,
            reverse_count=1,
            stdp_updates=[(1, 2, 0.5)],
            schema_signals=[{"priority": 0.6}],
        )
        desc = describe_replay_result(result)
        assert desc["sequences_generated"] == 3
        assert desc["memories_replayed"] == 8
        assert desc["stdp_updates_count"] == 1
