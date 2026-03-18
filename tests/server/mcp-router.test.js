const { describe, it } = require("node:test");
const assert = require("node:assert/strict");

const { createRouter, negotiateVersion, SUPPORTED_VERSIONS, SERVER_INFO } = require("../../mcp-server/server/mcp-router");

describe("mcp-router", () => {
  // Minimal tool registry for testing
  const mockRegistry = {
    test_tool: {
      description: "A test tool",
      inputSchema: { type: "object", properties: {}, required: [] },
      handler: async () => ({ status: "ok", value: 42 }),
    },
  };

  describe("createRouter", () => {
    it("returns a function", () => {
      const router = createRouter(mockRegistry);
      assert.equal(typeof router, "function");
    });
  });

  describe("initialize", () => {
    it("returns server info", async () => {
      const router = createRouter(mockRegistry);
      const response = await router({
        jsonrpc: "2.0",
        id: 1,
        method: "initialize",
        params: {},
      });

      assert.ok(response, "should return a response");
      const parsed = JSON.parse(response);
      assert.equal(parsed.jsonrpc, "2.0");
      assert.equal(parsed.id, 1);
      assert.ok(parsed.result.serverInfo, "should have serverInfo");
      assert.equal(parsed.result.serverInfo.name, "methodology-agent");
      assert.ok(parsed.result.protocolVersion, "should have protocolVersion");
      assert.ok(parsed.result.capabilities, "should have capabilities");
    });
  });

  describe("tools/list", () => {
    it("returns tools array", async () => {
      const router = createRouter(mockRegistry);
      const response = await router({
        jsonrpc: "2.0",
        id: 2,
        method: "tools/list",
        params: {},
      });

      const parsed = JSON.parse(response);
      assert.equal(parsed.id, 2);
      assert.ok(Array.isArray(parsed.result.tools), "tools should be an array");
      assert.equal(parsed.result.tools.length, 1);
      assert.equal(parsed.result.tools[0].name, "test_tool");
      assert.equal(parsed.result.tools[0].description, "A test tool");
    });
  });

  describe("tools/call", () => {
    it("returns JSON-RPC error for unknown tool", async () => {
      const router = createRouter(mockRegistry);
      const response = await router({
        jsonrpc: "2.0",
        id: 3,
        method: "tools/call",
        params: { name: "nonexistent_tool", arguments: {} },
      });

      const parsed = JSON.parse(response);
      assert.equal(parsed.id, 3);
      assert.ok(parsed.error, "should have JSON-RPC error");
      assert.equal(parsed.error.code, -32602);
      assert.ok(parsed.error.message.includes("nonexistent_tool"), "error should mention tool name");
    });

    it("returns content for valid tool", async () => {
      const router = createRouter(mockRegistry);
      const response = await router({
        jsonrpc: "2.0",
        id: 4,
        method: "tools/call",
        params: { name: "test_tool", arguments: {} },
      });

      const parsed = JSON.parse(response);
      assert.equal(parsed.id, 4);
      assert.ok(parsed.result.content, "should have content");
      assert.equal(parsed.result.content[0].type, "text");
      const text = JSON.parse(parsed.result.content[0].text);
      assert.equal(text.status, "ok");
      assert.equal(text.value, 42);
    });
  });

  describe("notifications/initialized", () => {
    it("returns null for notification", async () => {
      const router = createRouter(mockRegistry);
      const response = await router({
        jsonrpc: "2.0",
        method: "notifications/initialized",
      });

      assert.equal(response, null);
    });
  });

  describe("version negotiation", () => {
    it("accepts 2025-11-25", () => {
      assert.equal(negotiateVersion("2025-11-25"), "2025-11-25");
    });

    it("accepts 2024-11-05", () => {
      assert.equal(negotiateVersion("2024-11-05"), "2024-11-05");
    });

    it("returns latest for unknown version", () => {
      assert.equal(negotiateVersion("2099-01-01"), "2025-11-25");
    });

    it("initialize responds with negotiated version", async () => {
      const router = createRouter(mockRegistry);
      const response = await router({
        jsonrpc: "2.0",
        id: 10,
        method: "initialize",
        params: { protocolVersion: "2024-11-05" },
      });

      const parsed = JSON.parse(response);
      assert.equal(parsed.result.protocolVersion, "2024-11-05");
    });

    it("serverInfo includes title and description", async () => {
      const router = createRouter(mockRegistry);
      const response = await router({
        jsonrpc: "2.0",
        id: 11,
        method: "initialize",
        params: { protocolVersion: "2025-11-25" },
      });

      const parsed = JSON.parse(response);
      assert.ok(parsed.result.serverInfo.title, "should have title");
      assert.ok(parsed.result.serverInfo.description, "should have description");
    });
  });

  describe("tools/list (2025-11-25)", () => {
    it("includes title field per tool", async () => {
      const router = createRouter(mockRegistry);
      const response = await router({
        jsonrpc: "2.0",
        id: 12,
        method: "tools/list",
        params: {},
      });

      const parsed = JSON.parse(response);
      assert.ok(parsed.result.tools[0].title, "should have title");
    });

    it("ensures inputSchema is never null", async () => {
      const registryWithNull = {
        null_schema_tool: {
          description: "Tool with null schema",
          inputSchema: null,
          handler: async () => ({}),
        },
      };
      const router = createRouter(registryWithNull);
      const response = await router({
        jsonrpc: "2.0",
        id: 13,
        method: "tools/list",
        params: {},
      });

      const parsed = JSON.parse(response);
      assert.ok(parsed.result.tools[0].inputSchema, "inputSchema should not be null");
      assert.equal(parsed.result.tools[0].inputSchema.type, "object");
    });
  });

  describe("unknown method", () => {
    it("returns error for unknown method with id", async () => {
      const router = createRouter(mockRegistry);
      const response = await router({
        jsonrpc: "2.0",
        id: 5,
        method: "unknown/method",
      });

      const parsed = JSON.parse(response);
      assert.equal(parsed.id, 5);
      assert.ok(parsed.error, "should have error");
      assert.equal(parsed.error.code, -32601);
    });
  });
});
