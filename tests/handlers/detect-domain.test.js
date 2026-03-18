const { describe, it } = require("node:test");
const assert = require("node:assert/strict");

const { handler } = require("../../mcp-server/handlers/detect-domain");

describe("detect-domain handler", () => {
  it("returns a detection result with no args", async () => {
    const result = await handler();

    assert.ok(result, "handler should return a result");
    assert.ok("domain" in result || "coldStart" in result, "result should have domain or coldStart");
  });

  it("returns detection result with cwd", async () => {
    const result = await handler({ cwd: "/tmp/some-project" });

    assert.ok(result, "handler should return a result");
  });

  it("returns detection result with first_message", async () => {
    const result = await handler({ first_message: "help me refactor this module" });

    assert.ok(result, "handler should return a result");
  });
});
