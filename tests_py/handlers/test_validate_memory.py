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
    """_assess_memories: postcondition — staleness correctly classified per threshold."""

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
