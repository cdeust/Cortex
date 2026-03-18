const { describe, it } = require("node:test");
const assert = require("node:assert/strict");

const { handler } = require("../../mcp-server/handlers/record-session-end");

describe("record-session-end handler", () => {
  it("returns domain and profileUpdated with session_id", async () => {
    const result = await handler({
      session_id: "test-session-" + Date.now(),
    });

    assert.ok(result, "handler should return a result");
    assert.ok("domain" in result, "result should have domain");
    assert.equal(typeof result.domain, "string", "domain should be a string");
    assert.ok("profileUpdated" in result, "result should have profileUpdated");
    assert.equal(typeof result.profileUpdated, "boolean", "profileUpdated should be a boolean");
  });

  it("returns confidence field", async () => {
    const result = await handler({
      session_id: "test-session-confidence-" + Date.now(),
    });

    assert.ok("confidence" in result, "result should have confidence");
    assert.equal(typeof result.confidence, "number");
  });

  it("accepts optional fields without throwing", async () => {
    const result = await handler({
      session_id: "test-session-full-" + Date.now(),
      tools_used: ["Read", "Edit"],
      duration: 60000,
      turn_count: 10,
      keywords: ["refactor", "testing"],
      cwd: "/tmp/test",
    });

    assert.ok(result, "handler should return a result");
    assert.ok("domain" in result, "result should have domain");
  });
});
