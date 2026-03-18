const { describe, it } = require("node:test");
const assert = require("node:assert/strict");

const { handler } = require("../../mcp-server/handlers/get-methodology-graph");

describe("get-methodology-graph handler", () => {
  it("returns nodes, edges, and blindSpotRegions arrays", async () => {
    const result = await handler();

    assert.ok(result, "handler should return a result");
    assert.ok("nodes" in result, "result should have nodes");
    assert.ok(Array.isArray(result.nodes), "nodes should be an array");
    assert.ok("edges" in result, "result should have edges");
    assert.ok(Array.isArray(result.edges), "edges should be an array");
    assert.ok("blindSpotRegions" in result, "result should have blindSpotRegions");
    assert.ok(Array.isArray(result.blindSpotRegions), "blindSpotRegions should be an array");
  });

  it("accepts optional domain filter", async () => {
    const result = await handler({ domain: "nonexistent-domain" });

    assert.ok(result, "handler should return a result");
    assert.ok(Array.isArray(result.nodes));
    assert.ok(Array.isArray(result.edges));
  });
});
