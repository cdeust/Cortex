const { describe, it } = require("node:test");
const assert = require("node:assert/strict");

const { handler } = require("../../mcp-server/handlers/query-methodology");

describe("query-methodology handler", () => {
  it("returns expected response shape with no args", async () => {
    const result = await handler();

    assert.ok(result, "handler should return a result");
    assert.ok("domain" in result, "result should have domain");
    assert.ok("confidence" in result, "result should have confidence");
    assert.ok("coldStart" in result, "result should have coldStart");
    assert.ok("context" in result, "result should have context");
    assert.ok(typeof result.context === "string", "context should be a string");
    assert.ok("entryPoints" in result, "result should have entryPoints");
    assert.ok(Array.isArray(result.entryPoints), "entryPoints should be an array");
    assert.ok("recurringPatterns" in result, "result should have recurringPatterns");
    assert.ok(Array.isArray(result.recurringPatterns), "recurringPatterns should be an array");
    assert.ok("toolPreferences" in result, "result should have toolPreferences");
    assert.ok("blindSpots" in result, "result should have blindSpots");
    assert.ok(Array.isArray(result.blindSpots), "blindSpots should be an array");
    assert.ok("connectionBridges" in result, "result should have connectionBridges");
    assert.ok("sessionCount" in result, "result should have sessionCount");
    assert.ok(typeof result.sessionCount === "number", "sessionCount should be a number");
  });

  it("returns expected shape with cwd argument", async () => {
    const result = await handler({ cwd: "/tmp/test-project" });

    assert.ok(result, "handler should return a result");
    assert.ok("domain" in result, "result should have domain");
    assert.ok("context" in result, "result should have context");
  });

  it("returns expected shape with project argument", async () => {
    const result = await handler({ project: "test-project" });

    assert.ok(result, "handler should return a result");
    assert.ok("confidence" in result, "result should have confidence");
    assert.equal(typeof result.confidence, "number");
  });
});
