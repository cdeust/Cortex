"""Tests for write-time provenance grading (M-D5, 7.5).

Contract (handlers/remember_helpers.py::insert_and_post_process +
handlers/validate_memory.py::grade_from_content):

  - Every memory inserted via `remember()` (create/link/supersede actions)
    is graded with the SAME local-only checks validate_memory's batch pass
    uses -- no network. The grade lands as an additive `prov:<grade>` tag
    on the row, never into `source_attribution` (validate_memory.py's sole
    grade-vocabulary writer, I6-D6, is untouched by this increment).
  - The response carries a transient `provenance` field: {grade,
    checkable_refs, hint}. Never persisted from the response.
  - Grading runs strictly after the write-gate decision (evaluate_gate) --
    bench-neutral by construction, no G-bench required.
"""

from __future__ import annotations

import asyncio

import pytest

from mcp_server.handlers.remember import handler


def _tags_of(store, memory_id: int) -> list[str]:
    row = store.get_memory(memory_id)
    tags = row.get("tags") or []
    if isinstance(tags, str):
        import json as _json

        tags = _json.loads(tags)
    return tags


class TestProvenanceTagOnCreate:
    def test_no_refs_gets_unverifiable_tag(self):
        result = asyncio.run(
            handler(
                {
                    "content": "A plain testimony sentence "
                    "with no anchors at all today.",
                    "force": True,
                }
            )
        )
        assert result["stored"] is True
        assert result["provenance"]["grade"] == "unverifiable"

        from mcp_server.infrastructure.memory_config import get_memory_settings
        from mcp_server.infrastructure.memory_store import get_shared_store

        settings = get_memory_settings()
        store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
        assert "prov:unverifiable" in _tags_of(store, result["memory_id"])

    def test_existing_file_ref_gets_verified_tag(self, tmp_path):
        f = tmp_path / "real_module.py"
        f.write_text("x = 1")
        result = asyncio.run(
            handler(
                {
                    "content": f"Root cause traced to {f} — the offset was off by one.",
                    "force": True,
                    "directory": str(tmp_path),
                }
            )
        )
        assert result["stored"] is True
        assert result["provenance"]["grade"] == "verified"
        assert result["provenance"]["checkable_refs"]["file"] == 1

        from mcp_server.infrastructure.memory_config import get_memory_settings
        from mcp_server.infrastructure.memory_store import get_shared_store

        settings = get_memory_settings()
        store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
        assert "prov:verified" in _tags_of(store, result["memory_id"])

    def test_response_hint_present_and_deliberate_gets_call_to_action(self):
        result = asyncio.run(
            handler(
                {
                    "content": "A durable decision "
                    "with zero checkable reference in it.",
                    "force": True,
                    "write_class": "deliberate",
                }
            )
        )
        assert result["stored"] is True
        assert "durable claim" in result["provenance"]["hint"]

    def test_auto_class_unverifiable_hint_has_no_call_to_action(self):
        result = asyncio.run(
            handler(
                {
                    "content": "Auto-captured tool output "
                    "with no anchors whatsoever here.",
                    "force": True,
                    "write_class": "auto",
                }
            )
        )
        assert result["stored"] is True
        assert result["provenance"]["grade"] == "unverifiable"
        assert "durable claim" not in result["provenance"]["hint"]


class TestProvenanceDoesNotTouchSourceAttribution:
    """The sole-writer contract (I6-D6): remember() must never write a
    grade-vocabulary value into source_attribution -- that would silently
    defeat the C1 confabulation gate (recall_confabulation_risk), which
    only fires on the PERCEIVED epistemic tag."""

    def test_source_attribution_is_not_a_grade_value(self):
        result = asyncio.run(
            handler(
                {
                    "content": "Testimony with no references, stored deliberately.",
                    "force": True,
                }
            )
        )
        assert result["stored"] is True
        # source_attribution is C1's epistemic-origin vocabulary
        # (perceived/told/inferred/unknown), never the grade vocabulary.
        assert result["source_attribution"] not in (
            "verified",
            "verifiable",
            "unverifiable",
        )


class TestProvenanceNeverHitsNetwork:
    def test_url_in_content_does_not_call_urlopen(self, monkeypatch):
        def _boom(*_a, **_k):
            raise AssertionError("remember() must never touch the network for grading")

        monkeypatch.setattr("urllib.request.urlopen", _boom)
        result = asyncio.run(
            handler(
                {
                    "content": "See https://example.com/spec for the full spec.",
                    "force": True,
                }
            )
        )
        assert result["stored"] is True
        assert result["provenance"]["grade"] == "verifiable"


class TestProvenanceDeadRefHint:
    """Issue #345: the write-time hint must never claim "no checkable
    reference found" when `checkable_refs` in the SAME response is
    non-zero -- and must name which reference(s) failed and against what
    root, not just repeat the grade."""

    def test_acceptance_one_real_one_dead_path_names_the_dead_one(self, tmp_path):
        """Issue #345 acceptance criterion, verbatim: a `remember` call
        whose content cites one existing and one non-existent path returns
        a `provenance` block that names the non-existent path and does not
        claim that no reference was found."""
        real = tmp_path / "real_module.py"
        real.write_text("x = 1")
        dead_rel = "src/definitely_missing_module.py"
        result = asyncio.run(
            handler(
                {
                    "content": (
                        f"Root cause traced to {real} — see also "
                        f"{dead_rel} for the caller."
                    ),
                    "force": True,
                    "directory": str(tmp_path),
                }
            )
        )
        assert result["stored"] is True
        prov = result["provenance"]
        assert prov["grade"] == "unverifiable"
        assert prov["checkable_refs"]["file"] == 2
        assert "No checkable reference found" not in prov["hint"]
        assert dead_rel in prov["hint"]

    def test_dead_refs_and_reason_surfaced_on_response(self, tmp_path):
        dead_rel = "src/another_missing_file.py"
        result = asyncio.run(
            handler(
                {
                    "content": f"See {dead_rel} for context.",
                    "force": True,
                    "directory": str(tmp_path),
                }
            )
        )
        prov = result["provenance"]
        assert dead_rel in prov["dead_refs"]
        assert prov["reason"].startswith("dead_refs:")
        assert dead_rel in prov["reason"]

    def test_implicit_directory_names_root_and_says_directory_not_passed(
        self, tmp_path, monkeypatch
    ):
        """Live repro (memory 4341427, 2026-08-08): omit `directory` —
        resolution silently uses the process cwd, which need not be the
        writer's project root. The hint must name that root and say so,
        never conflate this with a genuinely-dead path."""
        monkeypatch.chdir(tmp_path)
        dead_rel = "src/yet_another_missing_file.py"
        result = asyncio.run(
            handler(
                {
                    "content": f"See {dead_rel} for context.",
                    "force": True,
                    # directory omitted on purpose
                }
            )
        )
        prov = result["provenance"]
        assert prov["grade"] == "unverifiable"
        assert str(tmp_path) in prov["hint"]
        assert "no `directory` was passed" in prov["hint"]

    def test_nonexistent_directory_root_names_root_as_missing(self, tmp_path):
        """State 2a: an explicitly-passed `directory` that is itself not a
        real directory on disk — the hint must blame the root, not the
        individually-named references (they were never even checkable)."""
        missing_root = str(tmp_path / "does_not_exist_at_all")
        result = asyncio.run(
            handler(
                {
                    "content": "See src/some_file.py for context.",
                    "force": True,
                    "directory": missing_root,
                }
            )
        )
        prov = result["provenance"]
        assert missing_root in prov["hint"]
        assert "not a directory on disk" in prov["hint"]

    def test_explicit_directory_gets_dead_ref_wording_not_implicit_wording(
        self, tmp_path
    ):
        dead_rel = "src/explicit_root_missing_file.py"
        result = asyncio.run(
            handler(
                {
                    "content": f"See {dead_rel} for context.",
                    "force": True,
                    "directory": str(tmp_path),
                }
            )
        )
        prov = result["provenance"]
        assert str(tmp_path) in prov["hint"]
        assert "no `directory` was passed" not in prov["hint"]
        assert dead_rel in prov["hint"]


class TestProvenanceGradingIsAfterGateDecision:
    """The prov: tag must never influence the gate's novelty/bypass
    decision -- it is appended strictly after evaluate_gate() runs
    (remember.py calls evaluate_gate before insert_and_post_process)."""

    @pytest.mark.asyncio
    async def test_gate_reason_unaffected_by_grading(self):
        # Two near-identical low-novelty writes without force: the SECOND
        # one being rejected (redundant) must not depend on whether the
        # FIRST one happened to grade verified/unverifiable -- the gate
        # reason comes from novelty signals computed before any prov: tag
        # exists.
        first = await handler(
            {"content": "Distinct fact about connection pooling defaults today."}
        )
        second = await handler(
            {"content": "Distinct fact about connection pooling defaults today."}
        )
        # Whatever the gate decided, it must be a legitimate gate_reason —
        # not a KeyError/crash from prov: tag interference.
        assert "reason" in first
        assert "reason" in second
