"""Tests for mcp_server.handlers.lesson_promotion (M-D6, 7.6).

Read-only report — never writes a rule, a trigger, a page, or a tag
(mirrors tests_py/handlers/test_curate_wiki_uncited.py's contract shape).
"""

from __future__ import annotations

import asyncio

from mcp_server.handlers import lesson_promotion
from tests_py._store_call import FakeConnStore, mark_test_operation


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _FakeStore(FakeConnStore):
    """PostgreSQL-shaped store; the listing operation is monkeypatched."""


def test_returns_jobs_built_from_candidates(monkeypatch) -> None:
    rows = [
        {
            "id": 7,
            "content_preview": "boost lessons in the recall pipeline",
            "tags": ["lesson"],
            "useful_count": 2,
            "access_count": 5,
            "domain": "cortex",
        }
    ]
    monkeypatch.setattr(lesson_promotion, "get_shared_store", lambda: _FakeStore())
    monkeypatch.setattr(
        lesson_promotion,
        "list_lesson_promotion_candidates",
        mark_test_operation(lambda conn, limit: rows),
    )

    result = _run(lesson_promotion.handler({"limit": 5}))

    assert result["candidate_count"] == 1
    assert result["returned"] == 1
    assert len(result["jobs"]) == 1
    job = result["jobs"][0]
    assert job["memory_id"] == 7
    assert job["suggested_kind"] == "rule"
    assert "instructions" in result
    assert "add_rule" not in "".join(job.keys())  # job never carries a call, only data


def test_degrades_to_empty_on_db_failure(monkeypatch) -> None:
    def _boom():
        raise RuntimeError("PG unreachable")

    monkeypatch.setattr(lesson_promotion, "get_shared_store", _boom)

    result = _run(lesson_promotion.handler({}))

    assert result["jobs"] == []
    assert result["candidate_count"] == 0
    assert result["returned"] == 0


def test_default_limit_is_ten(monkeypatch) -> None:
    captured = {}

    @mark_test_operation
    def _fake_list(conn, limit):
        captured["limit"] = limit
        return []

    monkeypatch.setattr(lesson_promotion, "get_shared_store", lambda: _FakeStore())
    monkeypatch.setattr(
        lesson_promotion, "list_lesson_promotion_candidates", _fake_list
    )

    _run(lesson_promotion.handler({}))

    assert captured["limit"] == 10


def test_never_calls_add_rule_create_trigger_or_wiki_write(monkeypatch) -> None:
    """Read-only guarantee: the handler module must not import any of the
    promotion-action handlers, so it cannot invoke them even accidentally."""
    import inspect

    source = inspect.getsource(lesson_promotion)
    for forbidden in (
        "add_rule.handler",
        "create_trigger.handler",
        "wiki_write.handler",
    ):
        assert forbidden not in source


class TestSchema:
    def test_schema_exists(self):
        assert "description" in lesson_promotion.schema
        assert "inputSchema" in lesson_promotion.schema

    def test_limit_has_bounds(self):
        props = lesson_promotion.schema["inputSchema"]["properties"]
        assert props["limit"]["minimum"] == 1
        assert props["limit"]["maximum"] == 100


class TestFullPromotionRoundTrip:
    """Real-DB proof of the M-D6 acceptance criterion: 1 lesson -> job ->
    add_rule -> get_rules shows it (source_memory_id) -> apply_rules
    (recall's actual rule engine) with/without the rule differs ->
    remember(supersedes_id=...) closes the loop -> the lesson drops out
    of future job batches."""

    def test_lesson_to_rule_round_trip(self):
        import time

        from mcp_server.core.memory_rules import apply_rules
        from mcp_server.handlers.add_rule import handler as add_rule_handler
        from mcp_server.handlers.get_rules import handler as get_rules_handler
        from mcp_server.handlers.rate_memory import handler as rate_memory_handler
        from mcp_server.handlers.remember import handler as remember_handler

        marker = f"m-d6-roundtrip-{int(time.time() * 1000)}"

        # 1. A lesson is captured (e.g. by self-critique persistence, 7.6 part A).
        remembered = _run(
            remember_handler(
                {
                    "content": (
                        f"[{marker}] boost lessons in the recall pipeline "
                        "when they carry verified provenance."
                    ),
                    "tags": ["lesson", marker],
                    "source": "self-critique",
                    "write_class": "deliberate",
                }
            )
        )
        assert remembered["stored"] is True
        lesson_id = remembered["memory_id"]

        # 2. It demonstrates usage evidence (rate_memory sets useful_count>0,
        #    the structural boundary list_lesson_promotion_candidates filters on).
        rated = _run(rate_memory_handler({"memory_id": lesson_id, "useful": True}))
        assert rated["rated"] is True

        # 3. lesson_promotion proposes it as a job, suggested_kind="rule".
        promo = _run(lesson_promotion.handler({"limit": 1000}))
        job = next((j for j in promo["jobs"] if j["memory_id"] == lesson_id), None)
        assert job is not None, "lesson with usage evidence must appear as a job"
        assert job["suggested_kind"] == "rule"

        # 4. The LLM promotes it: add_rule with source_memory_id traceability.
        rule_result = _run(
            add_rule_handler(
                {
                    "condition": f"tag contains {marker}",
                    "action": "penalty:0.5",
                    "rule_type": "soft",
                    "source_memory_id": lesson_id,
                }
            )
        )
        assert rule_result["created"] is True
        rule_id = rule_result["rule_id"]

        # 5. get_rules shows the pointer both ways.
        rules_listing = _run(get_rules_handler({}))
        persisted_rule = next(r for r in rules_listing["rules"] if r["id"] == rule_id)
        assert persisted_rule["source_memory_id"] == lesson_id

        # 6. apply_rules (the exact function recall's rule engine calls) —
        #    with vs without the rule differs, proving the rule is live.
        candidate = {"id": lesson_id, "tags": ["lesson", marker], "score": 1.0}
        without_rule = apply_rules([dict(candidate)], [])
        with_rule = apply_rules([dict(candidate)], rules_listing["rules"])
        assert without_rule[0]["score"] == 1.0
        assert with_rule[0]["score"] == 0.5  # penalty:0.5 applied

        # 7. Close the loop: append-only supersession tags the lesson
        #    'promoted:rule'. The original row is never mutated in place.
        # force=True per promotion_instructions()'s documented pattern:
        # the promoted content is near-identical to its source lesson by
        # construction, so it would otherwise fail the gate's own novelty
        # check on ITS OWN content — remember_schema.py documents
        # supersedes_id + force=True as exactly this "sovereign human
        # correction" combination (gate bypassed, supersession edge
        # still posted, try_curation already skipped on the supersede
        # path regardless of force).
        closed = _run(
            remember_handler(
                {
                    "content": (
                        f"[{marker}] PROMOTED: boost lessons in the recall "
                        "pipeline when they carry verified provenance "
                        f"(rule_id={rule_id})."
                    ),
                    "tags": ["lesson", marker, "promoted:rule"],
                    "source": "self-critique",
                    "write_class": "deliberate",
                    "supersedes_id": lesson_id,
                    "force": True,
                }
            )
        )
        assert closed["stored"] is True

        # 8. The lesson (now superseded, head carries promoted:rule) drops
        #    out of future promotion batches — no re-promotion of the same
        #    lesson (M-D6: single promotion path, no competing state).
        promo_after = _run(lesson_promotion.handler({"limit": 1000}))
        assert all(j["memory_id"] != lesson_id for j in promo_after["jobs"])
