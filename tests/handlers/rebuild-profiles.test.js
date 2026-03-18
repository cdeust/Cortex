const { describe, it } = require("node:test");
const assert = require("node:assert/strict");

const { handler } = require("../../mcp-server/handlers/rebuild-profiles");

describe("rebuild-profiles handler", () => {
  it("returns domains array with force=true", async () => {
    const result = await handler({ force: true });

    assert.ok(result, "handler should return a result");
    assert.ok("domains" in result, "result should have domains");
    assert.ok(Array.isArray(result.domains), "domains should be an array");
  });

  it("includes totalSessions and totalMemories when rebuilt", async () => {
    const result = await handler({ force: true });

    assert.ok("totalSessions" in result, "result should have totalSessions");
    assert.ok("totalMemories" in result, "result should have totalMemories");
    assert.equal(typeof result.totalSessions, "number");
    assert.equal(typeof result.totalMemories, "number");
  });

  it("includes duration metric when rebuilt", async () => {
    const result = await handler({ force: true });

    assert.ok("duration" in result, "result should have duration");
    assert.equal(typeof result.duration, "number");
    assert.ok(result.duration >= 0, "duration should be non-negative");
  });
});
