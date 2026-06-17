"""Tests for mcp_server.handlers.add_rule — neuro-symbolic rule persistence.

Contract under test (from add_rule.py):
  POST-1  Success: returns {created: True, rule_id: int, rule_type, scope,
          scope_value, condition, action, priority} — all fields present, all
          values echo the caller's inputs.
  POST-2  rule_id is a positive integer (persisted row id from memory_rules).
  POST-3  Defaults: rule_type defaults to "soft", scope defaults to "global",
          priority defaults to 0, scope_value defaults to None.
  POST-4  domain/directory scope requires scope_value; returns
          {created: False, reason: ...} when scope_value is absent.
  POST-5  Missing condition returns {created: False, reason: ...}.
  POST-6  Missing action returns {created: False, reason: ...}.
  POST-7  Invalid rule_type returns {created: False, reason: ...}.
  POST-8  Invalid scope returns {created: False, reason: ...}.
  POST-9  Hard rule: rule_type="hard", action="exclude" round-trips correctly.
  POST-10 Tag rule: rule_type="tag", action="tag:review" round-trips correctly.
  POST-11 Priority bounds: priority integer is preserved in the response.
  POST-12 No-args call (None) treated as empty dict — validated, not crashed.
"""

from __future__ import annotations

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────


def _minimal_args(**overrides) -> dict:
    """Return the minimum valid args, with optional field overrides."""
    base = {"condition": "tag:deprecated", "action": "exclude"}
    base.update(overrides)
    return base


# ── POST-1 through POST-3: success path, output shape, defaults ───────────────


class TestAddRuleSuccess:
    @pytest.mark.asyncio
    async def test_success_output_shape(self):
        """POST-1: all required keys present on success."""
        from mcp_server.handlers.add_rule import handler

        result = await handler(_minimal_args())

        assert result["created"] is True
        for key in (
            "rule_id",
            "rule_type",
            "scope",
            "scope_value",
            "condition",
            "action",
            "priority",
        ):
            assert key in result, f"missing key in success response: {key}"

    @pytest.mark.asyncio
    async def test_rule_id_is_positive_integer(self):
        """POST-2: rule_id is a positive integer (real persisted row id)."""
        from mcp_server.handlers.add_rule import handler

        result = await handler(_minimal_args())

        assert result["created"] is True
        assert isinstance(result["rule_id"], int)
        assert result["rule_id"] > 0

    @pytest.mark.asyncio
    async def test_defaults_applied(self):
        """POST-3: rule_type, scope, priority, scope_value default correctly."""
        from mcp_server.handlers.add_rule import handler

        result = await handler(_minimal_args())

        assert result["rule_type"] == "soft"
        assert result["scope"] == "global"
        assert result["priority"] == 0
        assert result["scope_value"] is None

    @pytest.mark.asyncio
    async def test_inputs_echoed_in_response(self):
        """POST-1: every caller-supplied field is echoed back verbatim."""
        from mcp_server.handlers.add_rule import handler

        args = {
            "condition": "keyword:secret",
            "action": "boost:0.3",
            "rule_type": "soft",
            "scope": "global",
            "priority": 10,
        }
        result = await handler(args)

        assert result["created"] is True
        assert result["condition"] == "keyword:secret"
        assert result["action"] == "boost:0.3"
        assert result["rule_type"] == "soft"
        assert result["scope"] == "global"
        assert result["priority"] == 10

    @pytest.mark.asyncio
    async def test_successive_inserts_produce_distinct_ids(self):
        """POST-2: two separate rules get distinct rule_ids — each is persisted."""
        from mcp_server.handlers.add_rule import handler

        r1 = await handler(_minimal_args(condition="tag:old"))
        r2 = await handler(_minimal_args(condition="tag:new"))

        assert r1["created"] is True
        assert r2["created"] is True
        assert r1["rule_id"] != r2["rule_id"]


# ── POST-9: hard rule ─────────────────────────────────────────────────────────


class TestAddRuleHardType:
    @pytest.mark.asyncio
    async def test_hard_rule_round_trips(self):
        """POST-9: rule_type=hard, action=exclude stored and echoed correctly."""
        from mcp_server.handlers.add_rule import handler

        result = await handler(
            {
                "condition": "tag:deprecated",
                "action": "exclude",
                "rule_type": "hard",
            }
        )

        assert result["created"] is True
        assert result["rule_type"] == "hard"
        assert result["action"] == "exclude"


# ── POST-10: tag rule ─────────────────────────────────────────────────────────


class TestAddRuleTagType:
    @pytest.mark.asyncio
    async def test_tag_rule_round_trips(self):
        """POST-10: rule_type=tag, action=tag:<name> stored and echoed correctly."""
        from mcp_server.handlers.add_rule import handler

        result = await handler(
            {
                "condition": "keyword:TODO",
                "action": "tag:review",
                "rule_type": "tag",
            }
        )

        assert result["created"] is True
        assert result["rule_type"] == "tag"
        assert result["action"] == "tag:review"


# ── POST-11: priority ─────────────────────────────────────────────────────────


class TestAddRulePriority:
    @pytest.mark.asyncio
    async def test_custom_priority_preserved(self):
        """POST-11: supplied priority integer survives round-trip."""
        from mcp_server.handlers.add_rule import handler

        result = await handler(_minimal_args(priority=50))

        assert result["created"] is True
        assert result["priority"] == 50

    @pytest.mark.asyncio
    async def test_negative_priority_preserved(self):
        """POST-11: negative priority (within -100..100) survives round-trip."""
        from mcp_server.handlers.add_rule import handler

        result = await handler(_minimal_args(priority=-10))

        assert result["created"] is True
        assert result["priority"] == -10


# ── POST-3 / scope_value: domain scope ───────────────────────────────────────


class TestAddRuleDomainScope:
    @pytest.mark.asyncio
    async def test_domain_scope_with_scope_value(self):
        """Scope=domain with scope_value stored and echoed."""
        from mcp_server.handlers.add_rule import handler

        result = await handler(
            {
                "condition": "tag:old",
                "action": "penalize:0.5",
                "rule_type": "soft",
                "scope": "domain",
                "scope_value": "auth-service",
            }
        )

        assert result["created"] is True
        assert result["scope"] == "domain"
        assert result["scope_value"] == "auth-service"

    @pytest.mark.asyncio
    async def test_directory_scope_with_scope_value(self):
        """Scope=directory with scope_value stored and echoed."""
        from mcp_server.handlers.add_rule import handler

        result = await handler(
            {
                "condition": "source:import",
                "action": "exclude",
                "rule_type": "hard",
                "scope": "directory",
                "scope_value": "/Users/alice/code/cortex",
            }
        )

        assert result["created"] is True
        assert result["scope"] == "directory"
        assert result["scope_value"] == "/Users/alice/code/cortex"


# ── POST-4 through POST-8: validation / error paths ──────────────────────────


class TestAddRuleValidationErrors:
    @pytest.mark.asyncio
    async def test_missing_condition_returns_error(self):
        """POST-5: no condition → created=False with a reason."""
        from mcp_server.handlers.add_rule import handler

        result = await handler({"action": "exclude"})

        assert result["created"] is False
        assert "reason" in result
        assert result["reason"]  # non-empty string

    @pytest.mark.asyncio
    async def test_empty_condition_returns_error(self):
        """POST-5: blank condition string is treated as missing."""
        from mcp_server.handlers.add_rule import handler

        result = await handler({"condition": "   ", "action": "exclude"})

        assert result["created"] is False
        assert "reason" in result

    @pytest.mark.asyncio
    async def test_missing_action_returns_error(self):
        """POST-6: no action → created=False with a reason."""
        from mcp_server.handlers.add_rule import handler

        result = await handler({"condition": "tag:old"})

        assert result["created"] is False
        assert "reason" in result
        assert result["reason"]

    @pytest.mark.asyncio
    async def test_invalid_rule_type_returns_error(self):
        """POST-7: rule_type not in {hard,soft,tag} → created=False."""
        from mcp_server.handlers.add_rule import handler

        result = await handler(
            {
                "condition": "tag:old",
                "action": "exclude",
                "rule_type": "unknown_type",
            }
        )

        assert result["created"] is False
        assert "reason" in result

    @pytest.mark.asyncio
    async def test_invalid_scope_returns_error(self):
        """POST-8: scope not in {global,domain,directory} → created=False."""
        from mcp_server.handlers.add_rule import handler

        result = await handler(
            {
                "condition": "tag:old",
                "action": "exclude",
                "scope": "cluster",
            }
        )

        assert result["created"] is False
        assert "reason" in result

    @pytest.mark.asyncio
    async def test_domain_scope_without_scope_value_returns_error(self):
        """POST-4: scope=domain but no scope_value → created=False."""
        from mcp_server.handlers.add_rule import handler

        result = await handler(
            {
                "condition": "tag:old",
                "action": "exclude",
                "scope": "domain",
            }
        )

        assert result["created"] is False
        assert "reason" in result
        assert (
            "scope_value" in result["reason"].lower()
            or "scope" in result["reason"].lower()
        )

    @pytest.mark.asyncio
    async def test_directory_scope_without_scope_value_returns_error(self):
        """POST-4: scope=directory but no scope_value → created=False."""
        from mcp_server.handlers.add_rule import handler

        result = await handler(
            {
                "condition": "tag:old",
                "action": "exclude",
                "scope": "directory",
            }
        )

        assert result["created"] is False
        assert "reason" in result

    @pytest.mark.asyncio
    async def test_none_args_does_not_crash(self):
        """POST-12: handler(None) treated as empty dict, returns validation error."""
        from mcp_server.handlers.add_rule import handler

        result = await handler(None)

        # Must not raise; must be a well-formed error dict
        assert isinstance(result, dict)
        assert "created" in result
        assert result["created"] is False


# ── Validate validation helper directly ───────────────────────────────────────


class TestValidateRuleArgs:
    """Unit tests for _validate_rule_args — pure function, no I/O."""

    def test_valid_args_returns_none(self):
        from mcp_server.handlers.add_rule import _validate_rule_args

        err = _validate_rule_args({"condition": "tag:old", "action": "exclude"})
        assert err is None

    def test_missing_condition_returns_dict(self):
        from mcp_server.handlers.add_rule import _validate_rule_args

        err = _validate_rule_args({"action": "exclude"})
        assert err is not None
        assert err["created"] is False

    def test_missing_action_returns_dict(self):
        from mcp_server.handlers.add_rule import _validate_rule_args

        err = _validate_rule_args({"condition": "tag:old"})
        assert err is not None
        assert err["created"] is False

    def test_invalid_rule_type(self):
        from mcp_server.handlers.add_rule import _validate_rule_args

        err = _validate_rule_args(
            {
                "condition": "tag:old",
                "action": "exclude",
                "rule_type": "mega",
            }
        )
        assert err is not None
        assert err["created"] is False

    def test_invalid_scope(self):
        from mcp_server.handlers.add_rule import _validate_rule_args

        err = _validate_rule_args(
            {
                "condition": "tag:old",
                "action": "exclude",
                "scope": "cluster",
            }
        )
        assert err is not None
        assert err["created"] is False

    def test_domain_scope_missing_scope_value(self):
        from mcp_server.handlers.add_rule import _validate_rule_args

        err = _validate_rule_args(
            {
                "condition": "tag:old",
                "action": "exclude",
                "scope": "domain",
            }
        )
        assert err is not None
        assert err["created"] is False

    def test_domain_scope_with_scope_value_ok(self):
        from mcp_server.handlers.add_rule import _validate_rule_args

        err = _validate_rule_args(
            {
                "condition": "tag:old",
                "action": "exclude",
                "scope": "domain",
                "scope_value": "auth",
            }
        )
        assert err is None


# ── Schema introspection ───────────────────────────────────────────────────────


class TestAddRuleSchema:
    def test_schema_exists_and_has_required_fields(self):
        from mcp_server.handlers.add_rule import schema

        assert "description" in schema
        assert "inputSchema" in schema
        required = schema["inputSchema"].get("required", [])
        assert "condition" in required
        assert "action" in required

    def test_rule_type_enum_in_schema(self):
        from mcp_server.handlers.add_rule import schema

        props = schema["inputSchema"]["properties"]
        assert "rule_type" in props
        assert set(props["rule_type"]["enum"]) == {"hard", "soft", "tag"}

    def test_scope_enum_in_schema(self):
        from mcp_server.handlers.add_rule import schema

        props = schema["inputSchema"]["properties"]
        assert "scope" in props
        assert set(props["scope"]["enum"]) == {"global", "domain", "directory"}
