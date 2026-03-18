"""Tests for mcp_server.handlers.run_pipeline — schema, helpers, stages, and handler."""

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

from mcp_server.handlers.run_pipeline import schema, handler
from mcp_server.handlers.pipeline.helpers import (
    extract_text as _extract_text,
    finding_to_prd_type as _finding_to_prd_type,
    get_cognitive_context as _get_cognitive_context,
    log as _log,
    trunc as _trunc,
    try_parse_json as _try_parse_json,
)
from mcp_server.handlers.pipeline.audit import (
    apply_yaml_rules as _apply_yaml_rules,
    parse_yaml_rules_naive as _parse_yaml_rules_naive,
    stage_audit as _stage_audit,
)
from mcp_server.handlers.pipeline.discovery import stage_discovery as _stage_discovery
from mcp_server.handlers.pipeline.implementation import (
    stage_implementation as _stage_implementation,
)
from mcp_server.handlers.pipeline.prd import stage_prd as _stage_prd
from mcp_server.handlers.pipeline.push import stage_push_and_pr as _stage_push_and_pr
from mcp_server.handlers.pipeline.stages import (
    stage_hor as _stage_hor,
    stage_impact as _stage_impact,
    stage_init as _stage_init,
    stage_interview as _stage_interview,
    stage_strategy as _stage_strategy,
)
from mcp_server.handlers.pipeline.verification import (
    stage_verification as _stage_verification,
)
from mcp_server.errors import AnalysisError


loop = asyncio.new_event_loop()


def run(coro):
    return loop.run_until_complete(coro)


def _mock_client(**overrides):
    """Create a mock MCP client with sensible defaults."""
    client = AsyncMock()
    client.tool_calls = 0
    client.call = AsyncMock(return_value={})
    for k, v in overrides.items():
        setattr(client, k, v)
    return client


# ── Schema ─────────────────────────────────────────────────────────────────


class TestRunPipelineSchema:
    def test_requires_codebase_and_task_path(self):
        assert "codebase_path" in schema["inputSchema"]["required"]
        assert "task_path" in schema["inputSchema"]["required"]

    def test_has_description(self):
        assert len(schema["description"]) > 0

    def test_optional_fields(self):
        props = schema["inputSchema"]["properties"]
        assert "context_path" in props
        assert "github_repo" in props
        assert "server" in props
        assert "max_findings" in props


# ── Helpers ────────────────────────────────────────────────────────────────


class TestTrunc:
    def test_truncates_long_string(self):
        assert _trunc("hello world", 5) == "hello"

    def test_none_returns_empty(self):
        assert _trunc(None, 5) == ""

    def test_empty_string(self):
        assert _trunc("", 10) == ""

    def test_short_string_unchanged(self):
        assert _trunc("hi", 10) == "hi"


class TestExtractText:
    def test_string_input(self):
        assert _extract_text("hello") == "hello"

    def test_dict_enhanced(self):
        assert _extract_text({"enhanced": "e", "original": "o"}) == "e"

    def test_dict_original(self):
        assert _extract_text({"original": "o"}) == "o"

    def test_dict_content(self):
        assert _extract_text({"content": "c"}) == "c"

    def test_dict_empty(self):
        assert _extract_text({}) == ""

    def test_none_input(self):
        assert _extract_text(None) == ""

    def test_int_input(self):
        assert _extract_text(42) == ""

    def test_list_input(self):
        assert _extract_text([1, 2]) == ""

    def test_dict_priority_order(self):
        # enhanced takes priority over original
        assert _extract_text({"enhanced": "e", "original": "o", "content": "c"}) == "e"
        # original takes priority over content
        assert _extract_text({"original": "o", "content": "c"}) == "o"


class TestTryParseJson:
    def test_valid_json(self):
        assert _try_parse_json("[1,2,3]") == [1, 2, 3]

    def test_json_with_code_fence(self):
        assert _try_parse_json("```json\n[1,2,3]\n```") == [1, 2, 3]

    def test_json_with_bare_fence(self):
        assert _try_parse_json('```\n{"a":1}\n```') == {"a": 1}

    def test_invalid_json(self):
        assert _try_parse_json("not json at all") is None

    def test_non_string(self):
        assert _try_parse_json([1, 2]) == [1, 2]

    def test_dict_passthrough(self):
        d = {"key": "val"}
        assert _try_parse_json(d) is d

    def test_none_passthrough(self):
        assert _try_parse_json(None) is None


class TestFindingToPrdType:
    def test_feature_default(self):
        assert _finding_to_prd_type({"domain": "enhancement"}) == "feature"

    def test_bug_from_label(self):
        assert _finding_to_prd_type({"relevance_category_label": "bug fix"}) == "bug"

    def test_bug_from_defect(self):
        assert _finding_to_prd_type({"domain": "defect"}) == "bug"

    def test_proposal_from_rfc(self):
        assert _finding_to_prd_type({"domain": "rfc discussion"}) == "proposal"

    def test_proposal_from_proposal(self):
        assert _finding_to_prd_type({"domain": "proposal"}) == "proposal"

    def test_proposal_from_idea(self):
        assert _finding_to_prd_type({"domain": "idea board"}) == "proposal"

    def test_empty_dict(self):
        assert _finding_to_prd_type({}) == "feature"

    def test_none_values(self):
        assert (
            _finding_to_prd_type({"relevance_category_label": None, "domain": None})
            == "feature"
        )


class TestGetCognitiveContext:
    @patch(
        "mcp_server.handlers.pipeline.helpers.generate_context",
        return_value="profile text",
    )
    @patch(
        "mcp_server.handlers.pipeline.helpers.detect_domain",
        return_value={"domain": "test-domain", "coldStart": False},
    )
    @patch(
        "mcp_server.handlers.pipeline.helpers.load_profiles",
        return_value={"domains": {"test-domain": {"style": {}}}},
    )
    def test_returns_context_when_profile_exists(
        self, mock_load, mock_detect, mock_gen
    ):
        result = _get_cognitive_context("/some/path")
        assert result == "profile text"
        mock_load.assert_called_once()
        mock_detect.assert_called_once()
        mock_gen.assert_called_once_with("test-domain", {"style": {}})

    @patch(
        "mcp_server.handlers.pipeline.helpers.detect_domain",
        return_value={"domain": None, "coldStart": True},
    )
    @patch(
        "mcp_server.handlers.pipeline.helpers.load_profiles",
        return_value={"domains": {}},
    )
    def test_returns_empty_on_cold_start(self, mock_load, mock_detect):
        assert _get_cognitive_context("/path") == ""

    @patch(
        "mcp_server.handlers.pipeline.helpers.detect_domain",
        return_value={"domain": "x", "coldStart": False},
    )
    @patch(
        "mcp_server.handlers.pipeline.helpers.load_profiles",
        return_value={"domains": {}},
    )
    def test_returns_empty_when_no_profile(self, mock_load, mock_detect):
        assert _get_cognitive_context("/path") == ""

    @patch(
        "mcp_server.handlers.pipeline.helpers.load_profiles",
        side_effect=Exception("disk error"),
    )
    def test_returns_empty_on_exception(self, mock_load):
        assert _get_cognitive_context("/path") == ""


# ── YAML Rules ─────────────────────────────────────────────────────────────


class TestYamlRulesNaive:
    def test_parses_rules(self):
        yaml = """
- id: RULE-001
  mode: presence
  patterns:
    - pattern: authentication
    - pattern: security

- id: RULE-002
  mode: absence
  patterns:
    - pattern: error.handling
"""
        rules = _parse_yaml_rules_naive(yaml)
        assert len(rules) == 2
        assert rules[0]["id"] == "RULE-001"
        assert rules[0]["mode"] == "presence"
        assert "authentication" in rules[0]["patterns"]
        assert "security" in rules[0]["patterns"]
        assert rules[1]["id"] == "RULE-002"
        assert rules[1]["mode"] == "absence"

    def test_empty_input(self):
        assert _parse_yaml_rules_naive("") == []

    def test_single_rule_no_trailing_newline(self):
        yaml = "- id: R1\n  mode: presence\n  pattern: foo"
        rules = _parse_yaml_rules_naive(yaml)
        assert len(rules) == 1
        assert rules[0]["id"] == "R1"
        assert "foo" in rules[0]["patterns"]

    def test_suppress_parsing(self):
        yaml = "- id: R1\n  - pattern: auth\n  - suppress: internal\n  - suppress: test"
        rules = _parse_yaml_rules_naive(yaml)
        assert len(rules) == 1
        assert "internal" in rules[0]["suppress"]
        assert "test" in rules[0]["suppress"]

    def test_default_mode_is_presence(self):
        yaml = "- id: R1\n  - pattern: foo"
        rules = _parse_yaml_rules_naive(yaml)
        assert rules[0]["mode"] == "presence"

    def test_quoted_mode_stripped(self):
        yaml = "- id: R1\n  mode: 'absence'"
        rules = _parse_yaml_rules_naive(yaml)
        assert rules[0]["mode"] == "absence"

    def test_multiple_rules_appended(self):
        yaml = (
            "- id: A\n  - pattern: x\n- id: B\n  - pattern: y\n- id: C\n  - pattern: z"
        )
        rules = _parse_yaml_rules_naive(yaml)
        assert len(rules) == 3
        assert [r["id"] for r in rules] == ["A", "B", "C"]


class TestApplyYamlRules:
    def test_presence_rule_match(self):
        rules = [{"id": "R1", "patterns": ["auth"], "suppress": [], "mode": "presence"}]
        assert _apply_yaml_rules(rules, "authentication needed") == ["R1"]

    def test_presence_rule_no_match(self):
        rules = [{"id": "R1", "patterns": ["auth"], "suppress": [], "mode": "presence"}]
        assert _apply_yaml_rules(rules, "no match here") == []

    def test_absence_rule_flagged_when_missing(self):
        rules = [{"id": "R2", "patterns": ["error"], "suppress": [], "mode": "absence"}]
        assert _apply_yaml_rules(rules, "no match here") == ["R2"]

    def test_absence_rule_not_flagged_when_present(self):
        rules = [{"id": "R2", "patterns": ["error"], "suppress": [], "mode": "absence"}]
        assert _apply_yaml_rules(rules, "error handling") == []

    def test_suppress_blocks_flag(self):
        rules = [
            {
                "id": "R3",
                "patterns": ["auth"],
                "suppress": ["internal"],
                "mode": "presence",
            }
        ]
        assert _apply_yaml_rules(rules, "authentication needed") == ["R3"]
        assert _apply_yaml_rules(rules, "internal authentication") == []

    def test_invalid_regex_falls_back_to_substring(self):
        rules = [
            {"id": "R4", "patterns": ["[invalid"], "suppress": [], "mode": "presence"}
        ]
        assert _apply_yaml_rules(rules, "contains [invalid pattern") == ["R4"]
        assert _apply_yaml_rules(rules, "no match") == []

    def test_invalid_regex_in_suppress(self):
        rules = [
            {"id": "R5", "patterns": ["auth"], "suppress": ["[bad"], "mode": "presence"}
        ]
        assert _apply_yaml_rules(rules, "auth [bad case") == []

    def test_multiple_patterns_any_matches(self):
        rules = [
            {"id": "R6", "patterns": ["foo", "bar"], "suppress": [], "mode": "presence"}
        ]
        assert _apply_yaml_rules(rules, "bar baz") == ["R6"]

    def test_multiple_rules_independent(self):
        rules = [
            {"id": "A", "patterns": ["x"], "suppress": [], "mode": "presence"},
            {"id": "B", "patterns": ["y"], "suppress": [], "mode": "presence"},
        ]
        assert _apply_yaml_rules(rules, "x y") == ["A", "B"]
        assert _apply_yaml_rules(rules, "x zzz") == ["A"]

    def test_empty_rules(self):
        assert _apply_yaml_rules([], "anything") == []

    def test_suppress_invalid_regex_fallback_no_match(self):
        rules = [
            {
                "id": "R7",
                "patterns": ["auth"],
                "suppress": ["[nope"],
                "mode": "presence",
            }
        ]
        assert _apply_yaml_rules(rules, "auth here") == ["R7"]


# ── Stage: Init ────────────────────────────────────────────────────────────


class TestStageInit:
    def test_init_success(self):
        client = _mock_client()
        client.call.return_value = {"status": "ok", "target_repo": "/repo"}
        ctx = {"codebasePath": "/repo", "githubRepo": "owner/repo", "stages": {}}
        run(_stage_init(client, ctx))
        assert ctx["stages"][0]["status"] == "ok"
        assert ctx["stages"][0]["target"] == "/repo"

    def test_init_error_status(self):
        client = _mock_client()
        client.call.return_value = {"status": "error", "message": "blocked"}
        ctx = {"codebasePath": "/repo", "stages": {}}
        try:
            run(_stage_init(client, ctx))
            assert False, "Should have raised AnalysisError"
        except AnalysisError as e:
            assert "blocked" in str(e)

    def test_init_non_dict_result(self):
        client = _mock_client()
        client.call.return_value = "some string"
        ctx = {"codebasePath": "/repo", "stages": {}}
        run(_stage_init(client, ctx))
        assert ctx["stages"][0]["status"] == "ok"
        assert ctx["stages"][0]["target"] is None


# ── Stage: Discovery ───────────────────────────────────────────────────────


class TestStageDiscovery:
    def _make_task_file(self, tmpdir, findings):
        task_file = tmpdir / "task.json"
        task_file.write_text(json.dumps({"findings": findings}), encoding="utf-8")
        return str(task_file)

    def _make_context_file(self, tmpdir, content="context doc"):
        ctx_file = tmpdir / "context.md"
        ctx_file.write_text(content, encoding="utf-8")
        return str(ctx_file)

    def _make_context_dir(self, tmpdir):
        ctx_dir = tmpdir / "ctx_dir"
        ctx_dir.mkdir()
        (ctx_dir / "a.md").write_text("doc A", encoding="utf-8")
        (ctx_dir / "b.json").write_text('{"x":1}', encoding="utf-8")
        (ctx_dir / "c.txt").write_text("ignored", encoding="utf-8")
        return str(ctx_dir)

    def test_discovery_with_findings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            findings = [
                {
                    "id": "F1",
                    "title": "Add authentication module",
                    "description": "Implement OAuth support",
                    "relevance_score": 0.8,
                    "importance": 8,
                },
            ]
            task_path = self._make_task_file(tmpdir, findings)

            client = _mock_client()

            async def mock_call(tool, args):
                if tool == "ai_architect_fs_list":
                    return {"files": ["src", "tests"]}
                if tool == "ai_architect_fs_read":
                    # Return project doc with keywords matching the finding
                    path = args.get("path", "")
                    if path in ("CLAUDE.md", "README.md"):
                        return "# Authentication\nThis project implements authentication module with OAuth support for users."
                    return "def hello(): pass"
                if tool == "ai_architect_compound_score":
                    return {"compound_score": 0.8}
                return {}

            client.call = AsyncMock(side_effect=mock_call)

            ctx = {
                "codebasePath": str(tmpdir),
                "taskPath": task_path,
                "contextPath": None,
                "maxFindings": 5,
                "stages": {},
            }
            run(_stage_discovery(client, ctx))
            assert ctx["stages"][1]["status"] == "ok"
            assert len(ctx["topFindings"]) >= 1

    def test_discovery_no_relevant_findings_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            findings = [
                {
                    "id": "F1",
                    "title": "zzz yyy xxx",
                    "description": "completely unrelated",
                    "relevance_score": 0.0,
                    "importance": 1,
                },
            ]
            task_path = self._make_task_file(tmpdir, findings)

            client = _mock_client()
            client.call.return_value = {"files": []}

            ctx = {
                "codebasePath": str(tmpdir),
                "taskPath": task_path,
                "contextPath": None,
                "maxFindings": 5,
                "stages": {},
            }
            try:
                run(_stage_discovery(client, ctx))
                assert False, "Should have raised"
            except AnalysisError as e:
                assert "Jaccard" in str(e) or "relevance" in str(e)

    def _doc_reader(self, path, **kwargs):
        """Mock ai_architect_fs_read that returns auth-related project doc for README."""
        if path in ("CLAUDE.md", "README.md"):
            return "# Authentication\nThis project implements authentication module with OAuth support for users."
        return ""

    def test_discovery_with_context_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            findings = [
                {
                    "id": "F1",
                    "title": "auth module",
                    "description": "authentication",
                    "relevance_score": 0.9,
                    "importance": 9,
                }
            ]
            task_path = self._make_task_file(tmpdir, findings)
            context_path = self._make_context_file(tmpdir)

            client = _mock_client()

            async def mock_call(tool, args):
                if tool == "ai_architect_fs_list":
                    return {"files": []}
                if tool == "ai_architect_fs_read":
                    return self._doc_reader(args.get("path", ""))
                if tool == "ai_architect_compound_score":
                    return {"compound_score": 0.9}
                return {}

            client.call = AsyncMock(side_effect=mock_call)

            ctx = {
                "codebasePath": str(tmpdir),
                "taskPath": task_path,
                "contextPath": context_path,
                "maxFindings": 5,
                "stages": {},
            }
            run(_stage_discovery(client, ctx))
            assert ctx.get("contextDoc") is not None

    def test_discovery_with_context_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            findings = [
                {
                    "id": "F1",
                    "title": "auth module",
                    "description": "authentication",
                    "relevance_score": 0.9,
                    "importance": 9,
                }
            ]
            task_path = self._make_task_file(tmpdir, findings)
            context_path = self._make_context_dir(tmpdir)

            client = _mock_client()

            async def mock_call(tool, args):
                if tool == "ai_architect_fs_list":
                    return {"files": []}
                if tool == "ai_architect_fs_read":
                    return self._doc_reader(args.get("path", ""))
                if tool == "ai_architect_compound_score":
                    return {"compound_score": 0.9}
                return {}

            client.call = AsyncMock(side_effect=mock_call)

            ctx = {
                "codebasePath": str(tmpdir),
                "taskPath": task_path,
                "contextPath": context_path,
                "maxFindings": 5,
                "stages": {},
            }
            run(_stage_discovery(client, ctx))
            assert "doc A" in ctx.get("contextDoc", "")

    def test_discovery_low_compound_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            findings = [
                {
                    "id": "F1",
                    "title": "auth module",
                    "description": "authentication module",
                    "relevance_score": 0.5,
                    "importance": 5,
                }
            ]
            task_path = self._make_task_file(tmpdir, findings)

            client = _mock_client()

            async def mock_call(tool, args):
                if tool == "ai_architect_fs_list":
                    return {"files": []}
                if tool == "ai_architect_fs_read":
                    return self._doc_reader(args.get("path", ""))
                if tool == "ai_architect_compound_score":
                    return {"compound_score": 0.1}
                return {}

            client.call = AsyncMock(side_effect=mock_call)

            ctx = {
                "codebasePath": str(tmpdir),
                "taskPath": task_path,
                "contextPath": None,
                "maxFindings": 5,
                "stages": {},
            }
            try:
                os.environ["PIPELINE_COMPOUND_THRESHOLD"] = "0.4"
                run(_stage_discovery(client, ctx))
                assert False, "Should have raised AnalysisError"
            except AnalysisError as e:
                assert "below threshold" in str(e)
            finally:
                os.environ.pop("PIPELINE_COMPOUND_THRESHOLD", None)


# ── Stage: Impact ──────────────────────────────────────────────────────────


class TestStageImpact:
    def _base_ctx(self):
        return {
            "codebasePath": "/repo",
            "topFindings": [
                {"id": "F1", "title": "Test", "description": "desc", "compound": 0.8}
            ],
            "projectDoc": "# Project",
            "codebaseCtx": {
                "patterns": ["Foo"],
                "dependencies": ["import bar"],
                "files": [],
                "architecture": "",
            },
            "sourceDirs": [{"dir": "src", "count": 5, "files": []}],
            "contextDoc": "",
            "findingId": "TV-test",
            "stages": {},
        }

    @patch("mcp_server.handlers.pipeline.stages.get_cognitive_context", return_value="")
    def test_impact_success(self, mock_ctx):
        client = _mock_client()

        async def mock_call(tool, args):
            if tool == "ai_architect_enhance_prompt":
                return {"enhanced": "A" * 100}
            if tool == "ai_architect_trace_propagation":
                return {"affected": ["src"]}
            return {}

        client.call = AsyncMock(side_effect=mock_call)
        ctx = self._base_ctx()
        run(_stage_impact(client, ctx))
        assert ctx["stages"][2]["status"] == "ok"
        assert len(ctx["impactText"]) >= 50

    @patch("mcp_server.handlers.pipeline.stages.get_cognitive_context", return_value="")
    def test_impact_too_short_raises(self, mock_ctx):
        client = _mock_client()

        async def mock_call(tool, args):
            if tool == "ai_architect_enhance_prompt":
                return {"enhanced": "short"}
            return {}

        client.call = AsyncMock(side_effect=mock_call)
        ctx = self._base_ctx()
        try:
            run(_stage_impact(client, ctx))
            assert False, "Should have raised"
        except AnalysisError as e:
            assert "trivial" in str(e) or "empty" in str(e)


# ── Stage: Strategy ────────────────────────────────────────────────────────


class TestStageStrategy:
    def test_strategy_success(self):
        client = _mock_client()
        client.call.return_value = {"selected": {"name": "incremental"}}
        ctx = {"stages": {}}
        run(_stage_strategy(client, ctx))
        assert ctx["stages"][3]["status"] == "ok"
        assert ctx["stratName"] == "incremental"

    def test_strategy_empty_raises(self):
        client = _mock_client()
        client.call.return_value = {"selected": {"name": ""}}
        ctx = {"stages": {}}
        try:
            run(_stage_strategy(client, ctx))
            assert False, "Should have raised"
        except AnalysisError as e:
            assert "no strategy" in str(e).lower()

    def test_strategy_non_dict(self):
        client = _mock_client()
        client.call.return_value = "not a dict"
        ctx = {"stages": {}}
        try:
            run(_stage_strategy(client, ctx))
            assert False, "Should have raised"
        except AnalysisError:
            pass


# ── Stage: PRD ─────────────────────────────────────────────────────────────


class TestStagePrd:
    def _base_ctx(self):
        return {
            "codebasePath": "/repo",
            "topFindings": [
                {
                    "id": "F1",
                    "title": "Add Auth",
                    "description": "desc",
                    "compound": 0.8,
                }
            ],
            "codebaseCtx": {
                "architecture": "arch",
                "patterns": ["Foo"],
                "dependencies": ["import x"],
            },
            "sourceDirs": [{"dir": "src", "count": 3, "files": []}],
            "impactText": "impact " * 50,
            "stratName": "incremental",
            "findingId": "TV-test",
            "stages": {},
        }

    @patch("mcp_server.handlers.pipeline.prd.get_cognitive_context", return_value="")
    def test_prd_success(self, mock_ctx):
        client = _mock_client()

        async def mock_call(tool, args):
            if tool == "ai_architect_enhance_prompt":
                prompt = args.get("prompt", "")
                # The manifest extraction call has "Extract the ordered file change manifest"
                if "extract the ordered file change manifest" in prompt.lower():
                    return {
                        "enhanced": json.dumps(
                            [
                                {
                                    "path": "src/auth.py",
                                    "changeType": "create",
                                    "description": "auth module",
                                    "acRefs": ["AC-1"],
                                }
                            ]
                        )
                    }
                # All section generation calls return >= 100 chars
                return {"enhanced": "X" * 200}
            return {}

        client.call = AsyncMock(side_effect=mock_call)
        ctx = self._base_ctx()
        run(_stage_prd(client, ctx))
        assert ctx["stages"][4]["status"] == "ok"
        assert len(ctx["prdFiles"]) == 9
        assert len(ctx["fileManifest"]) >= 1

    @patch("mcp_server.handlers.pipeline.prd.get_cognitive_context", return_value="")
    def test_prd_section_too_short_raises(self, mock_ctx):
        client = _mock_client()
        call_count = [0]

        async def mock_call(tool, args):
            if tool == "ai_architect_enhance_prompt":
                call_count[0] += 1
                if call_count[0] == 1:
                    return {"enhanced": "short"}  # First section fails
                return {"enhanced": "X" * 200}
            return {}

        client.call = AsyncMock(side_effect=mock_call)
        ctx = self._base_ctx()
        try:
            run(_stage_prd(client, ctx))
            assert False, "Should have raised"
        except AnalysisError as e:
            assert "section" in str(e).lower() or "PRD" in str(e)

    @patch("mcp_server.handlers.pipeline.prd.get_cognitive_context", return_value="")
    def test_prd_empty_manifest_raises(self, mock_ctx):
        client = _mock_client()

        async def mock_call(tool, args):
            if tool == "ai_architect_enhance_prompt":
                prompt = args.get("prompt", "")
                # Only the manifest extraction call returns invalid data
                if "extract the ordered file change manifest" in prompt.lower():
                    return {"enhanced": "not valid json"}
                return {"enhanced": "X" * 200}
            return {}

        client.call = AsyncMock(side_effect=mock_call)
        ctx = self._base_ctx()
        try:
            run(_stage_prd(client, ctx))
            assert False, "Should have raised"
        except AnalysisError as e:
            assert "manifest" in str(e).lower()


# ── Stage: Interview ───────────────────────────────────────────────────────


class TestStageInterview:
    def _base_ctx(self):
        return {
            "prdFiles": {
                "overview": {"content": "overview text"},
                "requirements": {"content": "req text"},
            },
            "findingId": "TV-test",
            "fileManifest": [{"path": "x.py"}],
            "stages": {},
        }

    def test_interview_pass(self):
        client = _mock_client()
        client.call.return_value = {"gate": "pass", "reason": "ok"}
        ctx = self._base_ctx()
        run(_stage_interview(client, ctx))
        assert ctx["stages"]["4.5"]["status"] == "ok"

    def test_interview_reject(self):
        client = _mock_client()
        client.call.return_value = {"gate": "reject", "reason": "low quality"}
        ctx = self._base_ctx()
        try:
            run(_stage_interview(client, ctx))
            assert False, "Should have raised"
        except AnalysisError as e:
            assert "reject" in str(e).lower()

    def test_interview_status_rejected(self):
        client = _mock_client()
        client.call.return_value = {"status": "rejected", "reason": "bad"}
        ctx = self._base_ctx()
        try:
            run(_stage_interview(client, ctx))
            assert False, "Should have raised"
        except AnalysisError as e:
            assert "reject" in str(e).lower()

    def test_interview_non_dict_passes(self):
        client = _mock_client()
        client.call.return_value = "some string"
        ctx = self._base_ctx()
        run(_stage_interview(client, ctx))
        assert ctx["stages"]["4.5"]["status"] == "ok"


# ── Stage: Verification ───────────────────────────────────────────────────


class TestStageVerification:
    def _base_ctx(self):
        return {
            "topFindings": [
                {
                    "id": "F1",
                    "title": "Test",
                    "description": "desc",
                    "compound": 0.8,
                    "source_url": "http://test.com",
                    "actor": "bot",
                }
            ],
            "findingId": "TV-test",
            "stages": {},
        }

    def test_verification_success(self):
        client = _mock_client()
        results = {
            "ai_architect_decompose_claim": {
                "claim_count": 2,
                "claims": [{"text": "a"}, {"text": "b"}],
            },
            "ai_architect_verify_claim": {
                "verdict": "pass",
                "score": 0.85,
                "confidence": 0.9,
            },
            "ai_architect_debate_claim": {"overall_score": 0.8},
            "ai_architect_consensus": {"result": 0.82},
            "ai_architect_fuse_confidence": {"fused": 0.83},
            "ai_architect_save_context": {},
        }

        async def mock_call(tool, args):
            return results.get(tool, {})

        client.call = AsyncMock(side_effect=mock_call)
        ctx = self._base_ctx()
        run(_stage_verification(client, ctx))
        assert ctx["stages"][5]["status"] == "ok"
        assert ctx["stages"][5]["verdict"] == "pass"

    def test_verification_fail_verdict(self):
        client = _mock_client()
        results = {
            "ai_architect_decompose_claim": {"claim_count": 1},
            "ai_architect_verify_claim": {
                "verdict": "fail",
                "score": 0.3,
                "confidence": 0.9,
            },
            "ai_architect_debate_claim": {"overall_score": 0.7},
            "ai_architect_consensus": {},
            "ai_architect_fuse_confidence": {},
            "ai_architect_save_context": {},
        }

        async def mock_call(tool, args):
            return results.get(tool, {})

        client.call = AsyncMock(side_effect=mock_call)
        ctx = self._base_ctx()
        try:
            run(_stage_verification(client, ctx))
            assert False, "Should have raised"
        except AnalysisError as e:
            assert "reject" in str(e).lower() or "fail" in str(e).lower()

    def test_verification_low_scores(self):
        client = _mock_client()
        results = {
            "ai_architect_decompose_claim": {"claim_count": 1},
            "ai_architect_verify_claim": {
                "verdict": "uncertain",
                "score": 0.2,
                "confidence": 0.5,
            },
            "ai_architect_debate_claim": {"overall_score": 0.2},
            "ai_architect_consensus": {},
            "ai_architect_fuse_confidence": {},
            "ai_architect_save_context": {},
        }

        async def mock_call(tool, args):
            return results.get(tool, {})

        client.call = AsyncMock(side_effect=mock_call)
        ctx = self._base_ctx()
        try:
            run(_stage_verification(client, ctx))
            assert False, "Should have raised"
        except AnalysisError as e:
            assert "too low" in str(e).lower()

    def test_verification_non_dict_results(self):
        client = _mock_client()

        async def mock_call(tool, args):
            if tool == "ai_architect_verify_claim":
                return "not a dict"
            if tool == "ai_architect_debate_claim":
                return "not a dict"
            if tool == "ai_architect_decompose_claim":
                return "not a dict"
            return {}

        client.call = AsyncMock(side_effect=mock_call)
        ctx = self._base_ctx()
        # With non-dict results, defaults are used: v_score=0.75, d_score=0.7, avg=0.725 > 0.5
        # verdict is None (not "fail"/"reject"), so it should pass
        run(_stage_verification(client, ctx))
        assert ctx["stages"][5]["status"] == "ok"


# ── Stage: Implementation ─────────────────────────────────────────────────


class TestStageImplementation:
    def _base_ctx(self):
        return {
            "codebasePath": "/repo",
            "taskPath": "/task.json",
            "topFindings": [
                {
                    "id": "F1",
                    "title": "Test",
                    "description": "desc",
                    "compound": 0.8,
                    "actor": "bot",
                    "relevance_category_label": "feature",
                    "domain": "dev",
                }
            ],
            "findingId": "TV-test",
            "fileManifest": [
                {
                    "path": "src/auth.py",
                    "changeType": "create",
                    "description": "auth",
                    "acRefs": ["AC-1"],
                }
            ],
            "prdSections": [{"key": "overview", "file": "PRD-test-overview.md"}],
            "prdFiles": {
                "overview": {
                    "filename": "PRD-test-overview.md",
                    "content": "Overview text",
                },
                "technical": {"content": "tech spec"},
            },
            "codebaseCtx": {
                "patterns": ["Foo"],
                "dependencies": [],
                "architecture": "",
            },
            "sourceDirs": [{"dir": "src", "count": 3}],
            "impactText": "impact text",
            "stratName": "incremental",
            "rootFiles": ["src"],
            "findings": [{"id": "F1"}],
            "scored": [{"id": "F1", "compound": 0.8}],
            "prdType": "feature",
            "prdName": "test",
            "codebaseContextStr": "context",
            "verify": {"verdict": "pass", "score": 0.85},
            "stages": {},
        }

    def test_implementation_success(self):
        client = _mock_client()
        client.tool_calls = 10

        async def mock_call(tool, args):
            if tool == "ai_architect_git_worktree_add":
                return {"worktree_path": "/tmp/wt"}
            if tool == "ai_architect_enhance_prompt":
                return {"enhanced": "def auth():\n    pass\n" + "# code " * 20}
            if tool == "ai_architect_fs_read":
                return ""
            return {}

        client.call = AsyncMock(side_effect=mock_call)
        ctx = self._base_ctx()
        run(_stage_implementation(client, ctx))
        assert ctx["stages"][6]["status"] == "ok"
        assert len(ctx["implementedFiles"]) >= 1

    def test_implementation_worktree_fallback_to_branch(self):
        client = _mock_client()
        client.tool_calls = 5

        async def mock_call(tool, args):
            if tool == "ai_architect_git_worktree_add":
                raise Exception("worktree failed")
            if tool == "ai_architect_enhance_prompt":
                return {"enhanced": "code content " * 10}
            return {}

        client.call = AsyncMock(side_effect=mock_call)
        ctx = self._base_ctx()
        run(_stage_implementation(client, ctx))
        assert ctx["stages"][6]["status"] == "ok"
        assert ctx["worktreePath"] is None

    def test_implementation_no_files_raises(self):
        client = _mock_client()
        client.tool_calls = 0

        async def mock_call(tool, args):
            if tool == "ai_architect_git_worktree_add":
                return {"worktree_path": "/tmp/wt"}
            if tool == "ai_architect_enhance_prompt":
                return {
                    "enhanced": "short"
                }  # < 10 chars won't trigger, but we need < 10
            return {}

        client.call = AsyncMock(side_effect=mock_call)
        ctx = self._base_ctx()

        # Make generated code too short to be written
        async def mock_call_short(tool, args):
            if tool == "ai_architect_git_worktree_add":
                return {"worktree_path": "/tmp/wt"}
            if tool == "ai_architect_enhance_prompt":
                return {"enhanced": "x"}  # 1 char < 10
            return {}

        client.call = AsyncMock(side_effect=mock_call_short)
        try:
            run(_stage_implementation(client, ctx))
            assert False, "Should have raised"
        except AnalysisError as e:
            assert "0 source files" in str(e)

    def test_implementation_modify_reads_existing(self):
        client = _mock_client()
        client.tool_calls = 5

        ctx = self._base_ctx()
        ctx["fileManifest"] = [
            {
                "path": "src/existing.py",
                "changeType": "modify",
                "description": "modify",
                "acRefs": ["AC-1"],
            }
        ]

        read_calls = []

        async def mock_call(tool, args):
            if tool == "ai_architect_git_worktree_add":
                return {"worktree_path": "/tmp/wt"}
            if tool == "ai_architect_fs_read":
                read_calls.append(args)
                return "existing content"
            if tool == "ai_architect_enhance_prompt":
                return {"enhanced": "modified content " * 10}
            return {}

        client.call = AsyncMock(side_effect=mock_call)
        run(_stage_implementation(client, ctx))
        assert len(read_calls) >= 1
        assert ctx["stages"][6]["status"] == "ok"


# ── Stage: HOR ─────────────────────────────────────────────────────────────


class TestStageHor:
    def _base_ctx(self):
        return {
            "topFindings": [
                {
                    "id": "F1",
                    "title": "Test",
                    "description": "desc",
                    "compound": 0.8,
                    "source_url": "http://test.com",
                }
            ],
            "stages": {},
        }

    def test_hor_success(self):
        client = _mock_client()
        client.call.return_value = {
            "results": [{"passed": True}, {"passed": False}, {"passed": True}]
        }
        ctx = self._base_ctx()
        run(_stage_hor(client, ctx))
        assert ctx["stages"][7]["status"] == "ok"
        assert ctx["horPassed"] == 2
        assert ctx["horTotal"] == 3

    def test_hor_non_dict_result(self):
        client = _mock_client()
        client.call.return_value = "not a dict"
        ctx = self._base_ctx()
        run(_stage_hor(client, ctx))
        assert ctx["horPassed"] == 0
        assert ctx["horTotal"] == 64  # default


# ── Stage: Audit ───────────────────────────────────────────────────────────


class TestStageAudit:
    def test_audit_no_rules_dir(self):
        ctx = {
            "codebasePath": "/nonexistent/path",
            "prdFiles": {"overview": {"content": "test content"}},
            "stages": {},
        }
        client = _mock_client()
        run(_stage_audit(client, ctx))
        assert ctx["stages"][8]["status"] == "ok"
        assert ctx["totalRulesChecked"] == 0

    def test_audit_with_rules(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rules_dir = (
                Path(tmpdir)
                / "packages"
                / "AIPRDAuditFlagEngine"
                / "Sources"
                / "Resources"
                / "Rules"
            )
            rules_dir.mkdir(parents=True)
            (rules_dir / "auth.yaml").write_text(
                "- id: AUTH-001\n  mode: presence\n  - pattern: authentication\n- id: AUTH-002\n  mode: absence\n  - pattern: encryption",
                encoding="utf-8",
            )

            ctx = {
                "codebasePath": tmpdir,
                "prdFiles": {
                    "overview": {"content": "authentication module implementation"}
                },
                "stages": {},
            }
            client = _mock_client()
            run(_stage_audit(client, ctx))
            assert ctx["stages"][8]["status"] == "ok"
            assert ctx["totalRulesChecked"] == 2
            # AUTH-001 presence of "authentication" -> flagged
            # AUTH-002 absence of "encryption" -> flagged (encryption not in content)
            assert ctx["totalFlagsRaised"] == 2

    def test_audit_skips_non_yaml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rules_dir = (
                Path(tmpdir)
                / "packages"
                / "AIPRDAuditFlagEngine"
                / "Sources"
                / "Resources"
                / "Rules"
            )
            rules_dir.mkdir(parents=True)
            (rules_dir / "notes.txt").write_text("not a yaml", encoding="utf-8")
            (rules_dir / "data.json").write_text("{}", encoding="utf-8")

            ctx = {
                "codebasePath": tmpdir,
                "prdFiles": {"overview": {"content": "test"}},
                "stages": {},
            }
            client = _mock_client()
            run(_stage_audit(client, ctx))
            assert ctx["totalRulesChecked"] == 0


# ── Stage: Push & PR ──────────────────────────────────────────────────────


class TestStagePushAndPr:
    def _base_ctx(self):
        return {
            "branchName": "pipeline/TV-test",
            "topFindings": [
                {
                    "id": "F1",
                    "title": "Test Feature",
                    "description": "desc",
                    "compound": 0.8,
                    "actor": "bot",
                    "relevance_category_label": "feature",
                    "domain": "dev",
                }
            ],
            "findingId": "TV-test",
            "prdSections": [{"key": "overview", "file": "PRD-test-overview.md"}],
            "implementedFiles": [
                {"path": "src/auth.py", "changeType": "create", "size": 500}
            ],
            "verify": {"verdict": "pass", "score": 0.85},
            "stratName": "incremental",
            "auditResults": [{"family": "auth", "rulesChecked": 2, "flagsRaised": 1}],
            "totalRulesChecked": 2,
            "totalFlagsRaised": 1,
            "horPassed": 60,
            "horTotal": 64,
            "worktreePath": None,
            "wtArgs": {},
            "stages": {},
        }

    def test_push_and_pr_success(self):
        client = _mock_client()
        client.tool_calls = 50

        async def mock_call(tool, args):
            if tool == "ai_architect_github_create_pr":
                return {"url": "https://github.com/org/repo/pull/42"}
            return {}

        client.call = AsyncMock(side_effect=mock_call)
        ctx = self._base_ctx()
        run(_stage_push_and_pr(client, ctx))
        assert ctx["stages"][10]["status"] == "ok"
        assert ctx["prUrl"] == "https://github.com/org/repo/pull/42"

    def test_push_with_worktree_cleanup(self):
        client = _mock_client()
        client.tool_calls = 10

        calls = []

        async def mock_call(tool, args):
            calls.append(tool)
            if tool == "ai_architect_github_create_pr":
                return {"url": "https://github.com/org/repo/pull/1"}
            return {}

        client.call = AsyncMock(side_effect=mock_call)
        ctx = self._base_ctx()
        ctx["worktreePath"] = "/tmp/wt"
        run(_stage_push_and_pr(client, ctx))
        assert "ai_architect_git_worktree_remove" in calls

    def test_push_worktree_cleanup_failure_non_fatal(self):
        client = _mock_client()
        client.tool_calls = 10

        async def mock_call(tool, args):
            if tool == "ai_architect_git_worktree_remove":
                raise Exception("cleanup failed")
            if tool == "ai_architect_github_create_pr":
                return {"url": "https://github.com/org/repo/pull/1"}
            return {}

        client.call = AsyncMock(side_effect=mock_call)
        ctx = self._base_ctx()
        ctx["worktreePath"] = "/tmp/wt"
        run(_stage_push_and_pr(client, ctx))
        assert ctx["stages"][10]["status"] == "ok"

    def test_push_no_audit_results(self):
        client = _mock_client()
        client.tool_calls = 5

        async def mock_call(tool, args):
            if tool == "ai_architect_github_create_pr":
                return {"html_url": "https://github.com/org/repo/pull/2"}
            return {}

        client.call = AsyncMock(side_effect=mock_call)
        ctx = self._base_ctx()
        ctx["auditResults"] = []
        run(_stage_push_and_pr(client, ctx))
        assert ctx["prUrl"] == "https://github.com/org/repo/pull/2"

    def test_pr_url_fallback_to_number(self):
        client = _mock_client()
        client.tool_calls = 5

        async def mock_call(tool, args):
            if tool == "ai_architect_github_create_pr":
                return {"number": 99}
            return {}

        client.call = AsyncMock(side_effect=mock_call)
        ctx = self._base_ctx()
        run(_stage_push_and_pr(client, ctx))
        assert ctx["prUrl"] == 99

    def test_pr_non_dict_result(self):
        client = _mock_client()
        client.tool_calls = 5
        client.call.return_value = "https://github.com/org/repo/pull/5"
        ctx = self._base_ctx()
        run(_stage_push_and_pr(client, ctx))
        assert ctx["prUrl"] == "https://github.com/org/repo/pull/5"


# ── Main Handler ───────────────────────────────────────────────────────────


class TestHandler:
    @patch("mcp_server.handlers.run_pipeline.get_client")
    def test_handler_init_failure_returns_error(self, mock_get_client):
        client = _mock_client()
        client.tool_calls = 1
        client.call.return_value = {"status": "error", "message": "repo not found"}
        mock_get_client.return_value = client

        result = run(handler({"codebase_path": "/repo", "task_path": "/task.json"}))
        assert result["status"] == "error"
        assert result["failed_stage"] == "0: Init"

    @patch("mcp_server.handlers.run_pipeline.get_client")
    def test_handler_uses_custom_server(self, mock_get_client):
        client = _mock_client()
        client.tool_calls = 0
        client.call.return_value = {"status": "error", "message": "fail"}
        mock_get_client.return_value = client

        run(
            handler(
                {
                    "codebase_path": "/repo",
                    "task_path": "/t.json",
                    "server": "custom-srv",
                }
            )
        )
        mock_get_client.assert_awaited_once_with("custom-srv")

    @patch("mcp_server.handlers.run_pipeline.get_client")
    def test_handler_default_server(self, mock_get_client):
        client = _mock_client()
        client.tool_calls = 0
        client.call.return_value = {"status": "error", "message": "fail"}
        mock_get_client.return_value = client

        run(handler({"codebase_path": "/repo", "task_path": "/t.json"}))
        mock_get_client.assert_awaited_once_with("ai-architect")

    @patch("mcp_server.handlers.run_pipeline.get_client")
    def test_non_fatal_stage_continues(self, mock_get_client):
        """HOR and Audit failures should not stop the pipeline."""
        client = _mock_client()
        client.tool_calls = 100
        mock_get_client.return_value = client

        stage_calls = []

        def _make_ok(name):
            async def ok_stage(c, ctx):
                stage_calls.append(name)

            return ok_stage

        async def hor_fail(c, ctx):
            stage_calls.append("hor")
            raise Exception("HOR failed")

        async def audit_fail(c, ctx):
            stage_calls.append("audit")
            raise Exception("Audit failed")

        fns = {
            "stage_init": _make_ok("init"),
            "stage_discovery": _make_ok("discovery"),
            "stage_impact": _make_ok("impact"),
            "stage_strategy": _make_ok("strategy"),
            "stage_prd": _make_ok("prd"),
            "stage_interview": _make_ok("interview"),
            "stage_verification": _make_ok("verification"),
            "stage_implementation": _make_ok("implementation"),
            "stage_hor": hor_fail,
            "stage_audit": audit_fail,
            "stage_push_and_pr": _make_ok("push"),
        }

        with patch.dict("mcp_server.handlers.run_pipeline._STAGE_FNS", fns):
            result = run(
                handler(
                    {
                        "codebase_path": "/repo",
                        "task_path": "/task.json",
                    }
                )
            )

            assert result["status"] == "delivered"
            assert "push" in stage_calls
            assert "hor" in stage_calls
            assert "audit" in stage_calls

    @patch("mcp_server.handlers.run_pipeline.get_client")
    def test_fatal_stage_stops_pipeline(self, mock_get_client):
        """A fatal stage failure should stop the pipeline."""
        client = _mock_client()
        client.tool_calls = 5
        mock_get_client.return_value = client

        stage_calls = []

        async def ok_init(c, ctx):
            stage_calls.append("init")

        async def fail_disc(c, ctx):
            stage_calls.append("discovery")
            raise AnalysisError("no findings")

        async def ok_impact(c, ctx):
            stage_calls.append("impact")

        with patch.dict(
            "mcp_server.handlers.run_pipeline._STAGE_FNS",
            {
                "stage_init": ok_init,
                "stage_discovery": fail_disc,
                "stage_impact": ok_impact,
            },
        ):
            result = run(
                handler(
                    {
                        "codebase_path": "/repo",
                        "task_path": "/task.json",
                    }
                )
            )

            assert result["status"] == "error"
            assert result["failed_stage"] == "1: Discovery"
            assert "init" in stage_calls
            assert "discovery" in stage_calls
            assert "impact" not in stage_calls

    @patch("mcp_server.handlers.run_pipeline.get_client")
    def test_handler_full_success(self, mock_get_client):
        """Full pipeline success returns delivered status."""
        client = _mock_client()
        client.tool_calls = 200
        mock_get_client.return_value = client

        async def set_ctx_fields(c, ctx):
            ctx["findingId"] = "TV-test"
            ctx["branchName"] = "pipeline/TV-test"
            ctx["prUrl"] = "https://github.com/org/repo/pull/1"
            ctx["implementedFiles"] = [{"path": "x.py"}]
            ctx["prdSections"] = [{"key": "overview"}]
            ctx["horPassed"] = 60
            ctx["horTotal"] = 64
            ctx["totalRulesChecked"] = 10
            ctx["totalFlagsRaised"] = 2

        fns = {
            k: set_ctx_fields
            for k in [
                "stage_init",
                "stage_discovery",
                "stage_impact",
                "stage_strategy",
                "stage_prd",
                "stage_interview",
                "stage_verification",
                "stage_implementation",
                "stage_hor",
                "stage_audit",
                "stage_push_and_pr",
            ]
        }

        with patch.dict("mcp_server.handlers.run_pipeline._STAGE_FNS", fns):
            result = run(
                handler(
                    {
                        "codebase_path": "/repo",
                        "task_path": "/task.json",
                        "max_findings": 3,
                    }
                )
            )

            assert result["status"] == "delivered"
            assert result["finding_id"] == "TV-test"
            assert result["tool_calls"] == 200
            assert result["implemented_files"] == 1
            assert result["hor"] == "60/64"
            assert result["audit"]["rules"] == 10
            assert result["audit"]["flags"] == 2

    @patch("mcp_server.handlers.run_pipeline.get_client")
    def test_handler_ctx_defaults(self, mock_get_client):
        """Handler sets ctx defaults correctly."""
        client = _mock_client()
        client.tool_calls = 0
        mock_get_client.return_value = client

        captured_ctx = {}

        async def capture(c, ctx):
            captured_ctx.update(ctx)
            raise AnalysisError("stop")

        with patch.dict(
            "mcp_server.handlers.run_pipeline._STAGE_FNS",
            {"stage_init": capture},
        ):
            run(
                handler(
                    {
                        "codebase_path": "/my/repo",
                        "task_path": "/my/task.json",
                    }
                )
            )

            assert captured_ctx["codebasePath"] == "/my/repo"
            assert captured_ctx["taskPath"] == "/my/task.json"
            assert captured_ctx["contextPath"] is None
            assert captured_ctx["githubRepo"] == ""
            assert captured_ctx["maxFindings"] == 5

    @patch("mcp_server.handlers.run_pipeline.get_client")
    def test_handler_hor_none_in_result(self, mock_get_client):
        """When horPassed is None, hor should be None in result."""
        client = _mock_client()
        client.tool_calls = 0
        mock_get_client.return_value = client

        async def noop(c, ctx):
            pass

        fns = {
            k: noop
            for k in [
                "stage_init",
                "stage_discovery",
                "stage_impact",
                "stage_strategy",
                "stage_prd",
                "stage_interview",
                "stage_verification",
                "stage_implementation",
                "stage_hor",
                "stage_audit",
                "stage_push_and_pr",
            ]
        }

        with patch.dict("mcp_server.handlers.run_pipeline._STAGE_FNS", fns):
            result = run(
                handler(
                    {
                        "codebase_path": "/repo",
                        "task_path": "/task.json",
                    }
                )
            )

            assert result["status"] == "delivered"
            assert result["hor"] is None


# ── Log Helper ─────────────────────────────────────────────────────────────


class TestLog:
    def test_log_does_not_raise(self):
        # Just confirm _log doesn't crash
        _log("test message")
