const { describe, it } = require("node:test");
const assert = require("node:assert/strict");

const stdioModule = require("../../mcp-server/transport/stdio");

describe("stdio transport", () => {
  it("exports startStdioTransport function", () => {
    assert.ok(stdioModule.startStdioTransport, "should export startStdioTransport");
    assert.equal(typeof stdioModule.startStdioTransport, "function", "should be a function");
  });
});
