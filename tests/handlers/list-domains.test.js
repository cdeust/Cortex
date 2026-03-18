const { describe, it } = require("node:test");
const assert = require("node:assert/strict");

const { handler } = require("../../mcp-server/handlers/list-domains");

describe("list-domains handler", () => {
  it("returns domains array and totalDomains", async () => {
    const result = await handler();

    assert.ok(result, "handler should return a result");
    assert.ok("domains" in result, "result should have domains");
    assert.ok(Array.isArray(result.domains), "domains should be an array");
    assert.ok("totalDomains" in result, "result should have totalDomains");
    assert.equal(typeof result.totalDomains, "number");
    assert.equal(result.totalDomains, result.domains.length, "totalDomains should match domains.length");
  });

  it("includes globalStyle field", async () => {
    const result = await handler();

    assert.ok("globalStyle" in result, "result should have globalStyle");
  });

  it("domain entries have expected shape when present", async () => {
    const result = await handler();

    for (const domain of result.domains) {
      assert.ok("id" in domain, "domain should have id");
      assert.ok("label" in domain, "domain should have label");
      assert.ok("sessionCount" in domain, "domain should have sessionCount");
      assert.equal(typeof domain.sessionCount, "number");
    }
  });
});
