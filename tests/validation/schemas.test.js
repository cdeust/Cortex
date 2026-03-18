const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const { validateToolArgs } = require("../../mcp-server/validation/schemas");
const { ValidationError } = require("../../mcp-server/errors");

describe("validateToolArgs", () => {
  it("passes valid args through", () => {
    const result = validateToolArgs("record_session_end", {
      session_id: "abc-123",
      domain: "web",
    });
    assert.equal(result.session_id, "abc-123");
    assert.equal(result.domain, "web");
  });

  it("throws ValidationError for missing required field", () => {
    assert.throws(
      () => validateToolArgs("record_session_end", {}),
      (err) => {
        assert.ok(err instanceof ValidationError);
        assert.ok(err.message.includes("session_id"));
        return true;
      }
    );
  });

  it("throws ValidationError when required field is null", () => {
    assert.throws(
      () => validateToolArgs("record_session_end", { session_id: null }),
      (err) => {
        assert.ok(err instanceof ValidationError);
        return true;
      }
    );
  });

  it("throws ValidationError for string type mismatch", () => {
    assert.throws(
      () =>
        validateToolArgs("record_session_end", {
          session_id: "ok",
          domain: 123,
        }),
      (err) => {
        assert.ok(err instanceof ValidationError);
        assert.ok(err.message.includes("string"));
        return true;
      }
    );
  });

  it("throws ValidationError for number type mismatch", () => {
    assert.throws(
      () =>
        validateToolArgs("record_session_end", {
          session_id: "ok",
          duration: "not-a-number",
        }),
      (err) => {
        assert.ok(err instanceof ValidationError);
        assert.ok(err.message.includes("number"));
        return true;
      }
    );
  });

  it("throws ValidationError for boolean type mismatch", () => {
    assert.throws(
      () =>
        validateToolArgs("rebuild_profiles", {
          force: "yes",
        }),
      (err) => {
        assert.ok(err instanceof ValidationError);
        assert.ok(err.message.includes("boolean"));
        return true;
      }
    );
  });

  it("throws ValidationError for array type mismatch", () => {
    assert.throws(
      () =>
        validateToolArgs("record_session_end", {
          session_id: "ok",
          tools_used: "not-an-array",
        }),
      (err) => {
        assert.ok(err instanceof ValidationError);
        assert.ok(err.message.includes("array"));
        return true;
      }
    );
  });

  it("applies default values for missing optional fields", () => {
    const result = validateToolArgs("rebuild_profiles", {});
    assert.equal(result.force, false);
  });

  it("does not override provided values with defaults", () => {
    const result = validateToolArgs("rebuild_profiles", { force: true });
    assert.equal(result.force, true);
  });

  it("passes through args for unknown tool names", () => {
    const args = { foo: "bar", baz: 42 };
    const result = validateToolArgs("unknown_tool", args);
    assert.deepEqual(result, args);
  });

  it("returns empty object for unknown tool with no args", () => {
    const result = validateToolArgs("unknown_tool", null);
    assert.deepEqual(result, {});
  });

  it("handles tool with no required fields and no args", () => {
    const result = validateToolArgs("list_domains", {});
    assert.deepEqual(result, {});
  });

  it("only includes known properties in result", () => {
    const result = validateToolArgs("rebuild_profiles", {
      domain: "web",
      force: true,
      extra_field: "should not appear",
    });
    assert.equal(result.domain, "web");
    assert.equal(result.force, true);
    assert.equal(result.extra_field, undefined);
  });
});
