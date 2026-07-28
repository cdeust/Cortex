"""Tests for mcp_server.handlers.validate_memory — contract tests.

Contract (from handler docstring and schema):
  - Scans memories for file references that no longer exist on disk.
  - Updates is_stale flag in-place. Does NOT delete.
  - Accepts scope: memory_id | domain | directory | (all).
  - dry_run=True assesses without writing is_stale.
  - staleness_threshold controls the score cutoff [0, 1].
  - Always returns: validated, stale_found, stale_updated, reports.
  - reports is a per-memory list with: memory_id, total_refs, missing_refs,
    changed_refs, staleness_score, is_stale, reason.
  - Empty scope → validated=0, stale_found=0, stale_updated=0, reports=[].
"""

import pytest

from mcp_server.handlers.validate_memory import (
    _assess_memories,
    _path_exists,
    _resolve_existing_paths,
    grade_from_content,
    handler,
)
from mcp_server.handlers.remember import handler as remember_handler


# ── Pure-function unit tests (no store, no I/O constraints) ──────────────────


class TestPathExistsResolution:
    """_path_exists: postcondition — returns True iff at least one resolution
    strategy locates the file on the filesystem."""

    def test_absolute_existing_path_returns_true(self, tmp_path):
        f = tmp_path / "real.py"
        f.write_text("x")
        from pathlib import Path

        assert _path_exists(str(f), Path(tmp_path)) is True

    def test_absolute_missing_path_returns_false(self, tmp_path):
        from pathlib import Path

        assert _path_exists(str(tmp_path / "ghost.py"), Path(tmp_path)) is False

    def test_relative_path_resolved_against_base(self, tmp_path):
        sub = tmp_path / "src"
        sub.mkdir()
        (sub / "module.py").write_text("x")
        from pathlib import Path

        assert _path_exists("src/module.py", Path(tmp_path)) is True

    def test_relative_path_missing_returns_false(self, tmp_path):
        from pathlib import Path

        assert _path_exists("src/missing.py", Path(tmp_path)) is False


class TestResolveExistingPaths:
    """_resolve_existing_paths: postcondition — returns only refs that exist."""

    def test_returns_only_existing_refs(self, tmp_path):
        f = tmp_path / "found.py"
        f.write_text("x")
        refs = [str(f), str(tmp_path / "missing.py")]
        result = _resolve_existing_paths(refs, str(tmp_path))
        assert str(f) in result
        assert str(tmp_path / "missing.py") not in result

    def test_empty_refs_returns_empty_set(self, tmp_path):
        result = _resolve_existing_paths([], str(tmp_path))
        assert result == set()

    def test_all_missing_returns_empty_set(self, tmp_path):
        result = _resolve_existing_paths(
            [str(tmp_path / "a.py"), str(tmp_path / "b.py")], str(tmp_path)
        )
        assert result == set()


class TestAssessMemories:
    """_assess_memories: postcondition — staleness correctly classified per
    threshold."""

    def _make_mem(self, memory_id: int, content: str) -> dict:
        return {"id": memory_id, "content": content}

    def test_no_refs_in_content_not_stale(self):
        mems = [self._make_mem(1, "No file references here, just text.")]
        reports, stale_ids = _assess_memories(mems, existing_paths=set(), threshold=0.5)
        assert len(reports) == 1
        assert reports[0]["is_stale"] is False
        assert reports[0]["total_refs"] == 0
        assert 1 not in stale_ids

    def test_all_refs_missing_marks_stale_at_default_threshold(self, tmp_path):
        content = f"See {tmp_path}/missing_a.py and {tmp_path}/missing_b.py"
        mems = [self._make_mem(42, content)]
        # existing_paths is empty — all refs are missing
        reports, stale_ids = _assess_memories(mems, existing_paths=set(), threshold=0.5)
        assert reports[0]["is_stale"] is True
        assert 42 in stale_ids
        assert reports[0]["staleness_score"] > 0.0

    def test_all_refs_present_not_stale(self, tmp_path):
        f = tmp_path / "exists.py"
        f.write_text("x")
        content = f"Using {f}"
        mems = [self._make_mem(7, content)]
        reports, stale_ids = _assess_memories(
            mems, existing_paths={str(f)}, threshold=0.5
        )
        assert reports[0]["is_stale"] is False
        assert 7 not in stale_ids

    def test_threshold_one_requires_all_refs_missing(self, tmp_path):
        f = tmp_path / "exists.py"
        f.write_text("x")
        missing = str(tmp_path / "gone.py")
        # Content has both a real and a fake path — score will be 0.5 (1/2 missing)
        content = f"See {f} and {missing}"
        mems = [self._make_mem(3, content)]
        # threshold=1.0 means only mark stale if ALL refs are missing
        reports, stale_ids = _assess_memories(
            mems, existing_paths={str(f)}, threshold=1.0
        )
        assert reports[0]["is_stale"] is False, (
            "threshold=1.0 should not flag memory when only 50% of refs are missing"
        )

    def test_report_keys_present(self, tmp_path):
        mems = [self._make_mem(99, "No refs here")]
        reports, _ = _assess_memories(mems, existing_paths=set(), threshold=0.5)
        expected_keys = {
            "memory_id",
            "total_refs",
            "missing_refs",
            "changed_refs",
            "staleness_score",
            "is_stale",
            "reason",
        }
        assert expected_keys <= set(reports[0].keys()), (
            "Report dict must contain all documented output keys"
        )


# ── Handler integration tests (use store, SQLite or PG) ─────────────────────


class TestValidateMemoryHandlerEmptyStore:
    """Handler postcondition: empty store → validated=0, stale_found=0,
    stale_updated=0, reports=[]."""

    @pytest.mark.asyncio
    async def test_empty_store_all_scope(self):
        result = await handler({})
        assert result["validated"] == 0
        assert result["stale_found"] == 0
        assert result["stale_updated"] == 0
        assert result["reports"] == []

    @pytest.mark.asyncio
    async def test_empty_store_memory_id_scope(self):
        result = await handler({"memory_id": 9999})
        assert result["validated"] == 0
        assert result["stale_found"] == 0
        assert result["stale_updated"] == 0

    @pytest.mark.asyncio
    async def test_empty_store_domain_scope(self):
        result = await handler({"domain": "nonexistent-domain"})
        assert result["validated"] == 0
        assert result["reports"] == []

    @pytest.mark.asyncio
    async def test_none_args_treated_as_empty_dict(self):
        result = await handler(None)
        assert result["validated"] == 0
        assert "reports" in result


class TestValidateMemoryOutputShape:
    """Handler postcondition: output always contains validated, stale_found,
    stale_updated, dry_run, reports when memories are present."""

    @pytest.mark.asyncio
    async def test_output_keys_present_with_memory(self, tmp_path):
        # Store a memory that has NO real file refs → will not be stale
        store_result = await remember_handler(
            {
                "content": "Remembered: clean documentation with no paths.",
                "force": True,
                "tags": ["test"],
            }
        )
        assert store_result["stored"] is True

        result = await handler({"base_dir": str(tmp_path), "dry_run": False})
        assert "validated" in result
        assert "stale_found" in result
        assert "stale_updated" in result
        assert "dry_run" in result
        assert "reports" in result
        assert isinstance(result["reports"], list)
        assert result["validated"] >= 1

    @pytest.mark.asyncio
    async def test_dry_run_flag_reflected_in_output(self, tmp_path):
        await remember_handler(
            {
                "content": "Test memory with no file refs.",
                "force": True,
            }
        )
        result = await handler({"dry_run": True, "base_dir": str(tmp_path)})
        assert result["dry_run"] is True

    @pytest.mark.asyncio
    async def test_dry_run_false_flag_reflected_in_output(self, tmp_path):
        await remember_handler(
            {
                "content": "Test memory plain text only.",
                "force": True,
            }
        )
        result = await handler({"dry_run": False, "base_dir": str(tmp_path)})
        assert result["dry_run"] is False


class TestValidateMemoryStaleDetection:
    """Handler postcondition: memories referencing missing files are marked
    stale; stale_found and stale_updated reflect actual counts."""

    @pytest.mark.asyncio
    async def test_memory_with_missing_file_ref_is_stale(self, tmp_path):
        # Use a subdirectory under tmp_path so the path segment structure
        # is guaranteed extractable by the regex (requires >=1 dir segment
        # before the filename).
        subdir = tmp_path / "proj" / "src"
        subdir.mkdir(parents=True)
        missing = subdir / "deleted_module.py"
        # Do NOT create missing — it must not exist.
        content = f"This memory references {missing} which no longer exists"
        store_result = await remember_handler({"content": content, "force": True})
        assert store_result["stored"] is True

        result = await handler(
            {
                "base_dir": str(tmp_path),
                "staleness_threshold": 0.0,  # flag anything with one missing ref
                "dry_run": False,
            }
        )
        assert result["stale_found"] >= 1, (
            "Memory with a missing file reference should be marked stale"
        )
        # stale_updated must equal stale_found when dry_run=False
        assert result["stale_updated"] == result["stale_found"]

    @pytest.mark.asyncio
    async def test_memory_with_existing_file_ref_not_stale(self, tmp_path):
        subdir = tmp_path / "proj" / "src"
        subdir.mkdir(parents=True)
        real_file = subdir / "real_module.py"
        real_file.write_text("# exists")
        content = f"This memory references {real_file} which exists on disk"
        store_result = await remember_handler({"content": content, "force": True})
        assert store_result["stored"] is True

        result = await handler(
            {
                "base_dir": str(tmp_path),
                "staleness_threshold": 0.5,
                "dry_run": False,
            }
        )
        # All refs exist → stale_found should be 0
        assert result["stale_found"] == 0
        assert result["stale_updated"] == 0

    @pytest.mark.asyncio
    async def test_dry_run_does_not_write_stale_flag(self, tmp_path):
        subdir = tmp_path / "proj" / "src"
        subdir.mkdir(parents=True)
        missing = subdir / "ghost_file.py"
        # Do NOT create missing — it must not exist.
        content = f"References missing file {missing} (deleted)"
        store_result = await remember_handler({"content": content, "force": True})
        assert store_result["stored"] is True

        result = await handler(
            {
                "base_dir": str(tmp_path),
                "staleness_threshold": 0.0,
                "dry_run": True,
            }
        )
        # dry_run=True: stale_found counts detected stale memories
        assert result["stale_found"] >= 1, "dry_run should still report stale_found"
        # But stale_updated must be 0 — no DB writes occurred
        assert result["stale_updated"] == 0, (
            "dry_run=True must not write is_stale to the database"
        )

    @pytest.mark.asyncio
    async def test_reports_list_per_memory_breakdown(self, tmp_path):
        content = "Plain prose with no file paths whatsoever."
        await remember_handler({"content": content, "force": True})

        result = await handler({"base_dir": str(tmp_path)})
        assert len(result["reports"]) == result["validated"]
        if result["reports"]:
            report = result["reports"][0]
            for key in (
                "memory_id",
                "total_refs",
                "missing_refs",
                "changed_refs",
                "staleness_score",
                "is_stale",
                "reason",
            ):
                assert key in report, f"report missing key: {key}"


class TestValidateMemoryDoesNotDelete:
    """Contract invariant: validate_memory NEVER deletes memories.
    stale_updated counts is_stale flag writes, not row deletions."""

    @pytest.mark.asyncio
    async def test_memory_count_unchanged_after_validation(self, tmp_path):
        subdir = tmp_path / "proj" / "src"
        subdir.mkdir(parents=True)
        missing = subdir / "vanished.py"
        # Do NOT create missing — it must not exist.
        content = f"Ref to {missing} which is gone"
        store_result = await remember_handler({"content": content, "force": True})
        assert store_result["stored"] is True
        memory_id = store_result["memory_id"]

        # Validate with dry_run=False — marks the memory as stale
        result = await handler(
            {
                "base_dir": str(tmp_path),
                "staleness_threshold": 0.0,
                "dry_run": False,
            }
        )
        assert result["stale_updated"] >= 0

        # The memory row must still exist in the store (not deleted).
        # get_memory fetches by PK regardless of is_stale flag.
        from mcp_server.handlers.validate_memory import _get_store

        store = _get_store()
        mem = store.get_memory(memory_id)
        assert mem is not None, (
            "validate_memory must not delete memories — the row should still "
            "exist with is_stale=True after validation"
        )


class TestValidateMemorySchema:
    """Schema postcondition: schema dict has required MCP keys."""

    def test_schema_has_required_keys(self):
        from mcp_server.handlers.validate_memory import schema

        assert "description" in schema
        assert "inputSchema" in schema
        assert "title" in schema

    def test_schema_input_schema_properties(self):
        from mcp_server.handlers.validate_memory import schema

        props = schema["inputSchema"]["properties"]
        for expected_prop in (
            "memory_id",
            "domain",
            "directory",
            "base_dir",
            "staleness_threshold",
            "dry_run",
        ):
            assert expected_prop in props, f"schema missing property: {expected_prop}"


class TestValidateMemorySingleton:
    def test_get_store_returns_store(self):
        from mcp_server.handlers.validate_memory import _get_store

        store = _get_store()
        assert store is not None


# ── I6-D6: graded provenance verifier ─────────────────────────────────────


class TestProvenanceGradeWiring:
    """Handler postcondition: every report carries a provenance_grade in
    {verified, verifiable, unverifiable}, persisted to source_attribution
    unless dry_run."""

    @pytest.mark.asyncio
    async def test_report_carries_provenance_grade(self, tmp_path):
        store_result = await remember_handler(
            {"content": "Plain testimony, no references at all.", "force": True}
        )
        assert store_result["stored"] is True

        result = await handler({"memory_id": store_result["memory_id"]})
        assert result["reports"][0]["provenance_grade"] in (
            "verified",
            "verifiable",
            "unverifiable",
        )
        # No extractable reference -> unverifiable (I6-D6 grading contract).
        assert result["reports"][0]["provenance_grade"] == "unverifiable"

    @pytest.mark.asyncio
    async def test_grade_persisted_to_source_attribution(self, tmp_path):
        subdir = tmp_path / "proj" / "src"
        subdir.mkdir(parents=True)
        real_file = subdir / "real_module.py"
        real_file.write_text("# exists")
        content = f"Grounded in {real_file}"
        store_result = await remember_handler({"content": content, "force": True})
        mid = store_result["memory_id"]

        result = await handler(
            {"memory_id": mid, "base_dir": str(tmp_path), "dry_run": False}
        )
        assert result["graded"] == 1
        assert result["reports"][0]["provenance_grade"] == "verified"

        from mcp_server.handlers.validate_memory import _get_store

        store = _get_store()
        mem = store.get_memory(mid)
        assert mem["source_attribution"] == "verified"

    @pytest.mark.asyncio
    async def test_dry_run_does_not_write_source_attribution(self, tmp_path):
        store_result = await remember_handler(
            {"content": "No refs at all here.", "force": True}
        )
        mid = store_result["memory_id"]

        from mcp_server.handlers.validate_memory import _get_store

        store = _get_store()
        before = store.get_memory(mid)["source_attribution"]

        result = await handler({"memory_id": mid, "dry_run": True})
        assert result["graded"] == 0
        after = store.get_memory(mid)["source_attribution"]
        assert after == before, "dry_run must not write source_attribution"

    @pytest.mark.asyncio
    async def test_verifier_is_sole_writer_overwrites_epistemic_tag(self, tmp_path):
        """I6-D6 arbitrage (Q3): whatever C1 source-monitoring wrote at
        remember() time (perceived/told/inferred/unknown) is overwritten
        by the verifier's grade the next time validate_memory runs."""
        store_result = await remember_handler(
            {
                "content": "I think this is probably true, no grounding at all.",
                "force": True,
            }
        )
        mid = store_result["memory_id"]

        from mcp_server.handlers.validate_memory import _get_store

        store = _get_store()
        pre_grade_value = store.get_memory(mid)["source_attribution"]
        # C1 classifies ungrounded "I think ... probably" content as inferred.
        assert pre_grade_value in ("inferred", "unknown", "perceived", "told")

        result = await handler({"memory_id": mid, "dry_run": False})
        post_grade_value = store.get_memory(mid)["source_attribution"]
        assert post_grade_value == result["reports"][0]["provenance_grade"]
        assert post_grade_value in ("verified", "verifiable", "unverifiable")


class TestProvenanceDeStale:
    """Handler postcondition (I6-D6): a stale memory whose file refs all
    resolve again is rehabilitated — is_stale flips back to false."""

    @pytest.mark.asyncio
    async def test_memory_rehabilitated_when_refs_resolve(self, tmp_path):
        subdir = tmp_path / "proj" / "src"
        subdir.mkdir(parents=True)
        target = subdir / "module.py"
        # First pass: file does NOT exist -> memory goes stale.
        content = f"References {target} for the implementation"
        store_result = await remember_handler({"content": content, "force": True})
        mid = store_result["memory_id"]

        first = await handler(
            {
                "memory_id": mid,
                "base_dir": str(tmp_path),
                "staleness_threshold": 0.0,
                "dry_run": False,
            }
        )
        assert first["stale_updated"] == 1

        from mcp_server.handlers.validate_memory import _get_store

        store = _get_store()
        assert store.get_memory(mid)["is_stale"] in (True, 1)

        # File now created -> re-verification must rehabilitate.
        target.write_text("# now exists")
        second = await handler(
            {
                "memory_id": mid,
                "base_dir": str(tmp_path),
                "staleness_threshold": 0.0,
                "dry_run": False,
            }
        )
        assert second["destaled"] == 1
        assert store.get_memory(mid)["is_stale"] in (False, 0)

    @pytest.mark.asyncio
    async def test_still_missing_ref_not_destaled(self, tmp_path):
        subdir = tmp_path / "proj" / "src"
        subdir.mkdir(parents=True)
        target = subdir / "gone_forever.py"
        content = f"References {target}"
        store_result = await remember_handler({"content": content, "force": True})
        mid = store_result["memory_id"]

        await handler(
            {
                "memory_id": mid,
                "base_dir": str(tmp_path),
                "staleness_threshold": 0.0,
                "dry_run": False,
            }
        )
        second = await handler(
            {
                "memory_id": mid,
                "base_dir": str(tmp_path),
                "staleness_threshold": 0.0,
                "dry_run": False,
            }
        )
        assert second["destaled"] == 0
        assert second["stale_updated"] == 0  # already stale, no new mark


class TestProvenanceIdempotence:
    """Re-running the verifier on an unchanged memory must be a no-op on
    the grade: same content, same filesystem state -> same grade."""

    @pytest.mark.asyncio
    async def test_repeat_verification_same_grade(self, tmp_path):
        subdir = tmp_path / "proj" / "src"
        subdir.mkdir(parents=True)
        real_file = subdir / "stable.py"
        real_file.write_text("# stable")
        content = f"Grounded reference to {real_file}"
        store_result = await remember_handler({"content": content, "force": True})
        mid = store_result["memory_id"]

        first = await handler({"memory_id": mid, "base_dir": str(tmp_path)})
        second = await handler({"memory_id": mid, "base_dir": str(tmp_path)})
        third = await handler({"memory_id": mid, "base_dir": str(tmp_path)})

        grades = {r["reports"][0]["provenance_grade"] for r in (first, second, third)}
        assert grades == {"verified"}
        # Nothing gets re-marked stale/destaled on repeat verified passes.
        assert second["stale_updated"] == 0
        assert second["destaled"] == 0
        assert third["stale_updated"] == 0
        assert third["destaled"] == 0


class TestProvenancePagination:
    """Handler postcondition (I6-D6): all-scope calls are cursor-paginated
    via after_id; next_after_id lets a caller continue a sweep."""

    @pytest.mark.asyncio
    async def test_next_after_id_present_for_all_scope(self, tmp_path):
        await remember_handler(
            {"content": "Pagination probe memory, no refs.", "force": True}
        )
        result = await handler({"base_dir": str(tmp_path)})
        assert result["validated"] >= 1
        assert result["next_after_id"] is not None
        assert isinstance(result["next_after_id"], int)

    @pytest.mark.asyncio
    async def test_next_after_id_none_for_memory_id_scope(self, tmp_path):
        store_result = await remember_handler(
            {"content": "Single-scope probe, no refs.", "force": True}
        )
        result = await handler(
            {"memory_id": store_result["memory_id"], "base_dir": str(tmp_path)}
        )
        assert result["next_after_id"] is None

    @pytest.mark.asyncio
    async def test_after_id_excludes_earlier_ids(self, tmp_path):
        store_result = await remember_handler(
            {"content": "Cursor probe memory, no refs.", "force": True}
        )
        mid = store_result["memory_id"]

        # Cursor set past this memory's id -> it must not be revalidated.
        result = await handler({"base_dir": str(tmp_path), "after_id": mid})
        ids_seen = {r["memory_id"] for r in result["reports"]}
        assert mid not in ids_seen


class TestUrlAndCommitRefsGrading:
    """Handler postcondition: URL refs never feed is_stale, but do feed
    provenance_grade; commit refs never grade dead memories unverifiable
    on their own."""

    @pytest.mark.asyncio
    async def test_url_ref_does_not_affect_staleness_score(self, tmp_path):
        content = "See https://this-domain-should-not-resolve.invalid/x for docs"
        store_result = await remember_handler({"content": content, "force": True})
        mid = store_result["memory_id"]

        result = await handler(
            {
                "memory_id": mid,
                "base_dir": str(tmp_path),
                "url_check_limit": 0,  # bound network entirely for this test
            }
        )
        report = result["reports"][0]
        # URL refs are not file refs -> staleness score stays 0 regardless
        # of URL reachability.
        assert report["total_refs"] == 0
        assert report["is_stale"] is False

    @pytest.mark.asyncio
    async def test_unresolvable_commit_grades_verifiable_not_unverifiable(
        self, tmp_path
    ):
        content = "Fixed in commit deadbeefcafebabe1234567890abcdef12345678"
        store_result = await remember_handler({"content": content, "force": True})
        mid = store_result["memory_id"]

        result = await handler({"memory_id": mid, "base_dir": str(tmp_path)})
        report = result["reports"][0]
        assert report["provenance_grade"] in ("verifiable",)


# ── grade_from_content (M-D5, 7.5 — write-path grading, no memory_id yet) ────


class TestGradeFromContentPure:
    """grade_from_content: same grading logic as the batch pass, applied to
    content that has not been inserted yet. LOCAL-ONLY -- no network."""

    def test_no_refs_is_unverifiable(self, tmp_path):
        report = grade_from_content(
            "just a plain testimony sentence", base_dir=str(tmp_path)
        )
        assert report.grade == "unverifiable"
        assert report.reason == "no_extractable_reference"

    def test_existing_file_ref_grades_verified(self, tmp_path):
        f = tmp_path / "a.py"
        f.write_text("x = 1")
        report = grade_from_content(f"see {f}", base_dir=str(tmp_path))
        assert report.grade == "verified"

    def test_missing_file_ref_grades_unverifiable(self, tmp_path):
        report = grade_from_content(
            f"see {tmp_path}/does-not-exist.py", base_dir=str(tmp_path)
        )
        assert report.grade == "unverifiable"
        assert report.dead_refs

    def test_url_ref_never_sampled_grades_verifiable_ceiling(self, tmp_path):
        # No network call is ever made from the write path -- a URL ref
        # always lands as "not sampled this pass" (verifiable ceiling),
        # exactly like validate_memory's url_check_limit=0 case.
        report = grade_from_content(
            "see https://example.com/docs for details", base_dir=str(tmp_path)
        )
        assert report.grade == "verifiable"
        assert report.uncheckable_refs == ["https://example.com/docs"]

    def test_never_hits_network(self, tmp_path, monkeypatch):
        def _boom(*_a, **_k):
            raise AssertionError("grade_from_content must never touch the network")

        monkeypatch.setattr("urllib.request.urlopen", _boom)
        report = grade_from_content(
            "see https://example.com/docs and https://other.example/y",
            base_dir=str(tmp_path),
        )
        assert report.grade == "verifiable"  # proves it returned, never raised

    def test_memory_id_placeholder_is_zero(self, tmp_path):
        report = grade_from_content("no refs here", base_dir=str(tmp_path))
        assert report.memory_id == 0

    def test_unresolvable_commit_grades_verifiable(self, tmp_path):
        report = grade_from_content(
            "fixed in deadbeefcafebabe1234567890abcdef12345678",
            directory_context=str(tmp_path),  # not a git repo
            base_dir=str(tmp_path),
        )
        assert report.grade == "verifiable"

    def test_empty_base_dir_defaults_to_cwd(self):
        # postcondition: base_dir="" falls back to os.getcwd(), matching
        # _handler_impl's own default -- must not raise.
        report = grade_from_content("no refs", base_dir="")
        assert report.grade == "unverifiable"
