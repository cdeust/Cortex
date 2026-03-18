const { describe, it } = require("node:test");
const assert = require("node:assert/strict");

const openVisualization = require("../../mcp-server/handlers/open-visualization");

describe("open-visualization handler", () => {
  it("exports schema and handler", () => {
    assert.ok(openVisualization.schema, "module should export schema");
    assert.ok(openVisualization.handler, "module should export handler");
    assert.equal(typeof openVisualization.handler, "function", "handler should be a function");
    assert.ok(openVisualization.schema.description, "schema should have description");
    assert.ok(openVisualization.schema.inputSchema, "schema should have inputSchema");
  });
});
