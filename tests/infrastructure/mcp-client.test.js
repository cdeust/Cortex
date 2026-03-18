const { describe, it, beforeEach, afterEach, mock } = require("node:test");
const assert = require("node:assert/strict");
const { MCPClient } = require("../../mcp-server/infrastructure/mcp-client");
const { ConnectionError } = require("../../mcp-server/errors");
const { EventEmitter } = require("node:events");

/**
 * Create a mock child process that speaks JSON-RPC 2.0.
 * Responds to initialize with server info and tools/list with empty tools.
 */
function createMockProcess(options = {}) {
  const proc = new EventEmitter();
  proc.stdin = {
    _written: [],
    write(data) { this._written.push(data); },
    end() {},
  };
  proc.stdout = new EventEmitter();
  proc.stderr = new EventEmitter();
  proc.kill = mock.fn();

  // Auto-respond to JSON-RPC messages
  if (!options.noAutoRespond) {
    const originalWrite = proc.stdin.write.bind(proc.stdin);
    proc.stdin.write = function (data) {
      this._written.push(data);
      try {
        const msg = JSON.parse(data.trim());
        if (msg.id == null) return; // notification — no response

        let result;
        if (msg.method === "initialize") {
          result = {
            protocolVersion: options.serverVersion || "2025-11-25",
            capabilities: { tools: {} },
            serverInfo: { name: "mock-server", version: "1.0.0" },
          };
        } else if (msg.method === "tools/list") {
          result = {
            tools: options.tools || [
              { name: "test_tool", description: "A test tool", inputSchema: { type: "object" } },
            ],
          };
        } else if (msg.method === "tools/call") {
          if (options.callError) {
            const response = JSON.stringify({ jsonrpc: "2.0", id: msg.id, error: { code: -32602, message: "Unknown tool" } });
            setTimeout(() => proc.stdout.emit("data", response + "\n"), 5);
            return;
          }
          result = {
            content: [{ type: "text", text: JSON.stringify(options.callResult || { ok: true }) }],
          };
        }

        if (result) {
          const response = JSON.stringify({ jsonrpc: "2.0", id: msg.id, result });
          setTimeout(() => proc.stdout.emit("data", response + "\n"), 5);
        }
      } catch (_) {}
    };
  }

  return proc;
}

describe("MCPClient", () => {
  let originalSpawn;
  let mockProc;

  beforeEach(() => {
    // We'll mock spawn per test as needed
  });

  describe("constructor", () => {
    it("sets default timeouts", () => {
      const client = new MCPClient({ command: "echo", args: [] });
      assert.equal(client._connectTimeoutMs, 10000);
      assert.equal(client._callTimeoutMs, 120000);
      assert.equal(client._idleTimeoutMs, 300000);
    });

    it("accepts custom timeouts", () => {
      const client = new MCPClient({
        command: "echo",
        args: [],
        connectTimeoutMs: 5000,
        callTimeoutMs: 60000,
        idleTimeoutMs: 120000,
      });
      assert.equal(client._connectTimeoutMs, 5000);
      assert.equal(client._callTimeoutMs, 60000);
      assert.equal(client._idleTimeoutMs, 120000);
    });

    it("starts with toolCalls at 0", () => {
      const client = new MCPClient({ command: "echo", args: [] });
      assert.equal(client.toolCalls, 0);
    });

    it("starts not connected", () => {
      const client = new MCPClient({ command: "echo", args: [] });
      assert.equal(client.connected, false);
    });
  });

  describe("listTools", () => {
    it("returns empty object before connect", () => {
      const client = new MCPClient({ command: "echo", args: [] });
      assert.deepEqual(client.listTools(), {});
    });
  });

  describe("close", () => {
    it("is safe to call when not connected", () => {
      const client = new MCPClient({ command: "echo", args: [] });
      // Should not throw
      client.close();
      assert.equal(client.connected, false);
    });
  });

  describe("_notify", () => {
    it("sends message without id field", () => {
      const client = new MCPClient({ command: "echo", args: [] });
      // Manually set up a mock proc to test _notify
      client._proc = {
        stdin: {
          _written: [],
          write(data) { this._written.push(data); },
        },
      };

      client._notify("notifications/initialized");
      const sent = JSON.parse(client._proc.stdin._written[0].replace("\n", ""));
      assert.equal(sent.jsonrpc, "2.0");
      assert.equal(sent.method, "notifications/initialized");
      assert.equal(sent.id, undefined, "notifications must not have an id field");
    });
  });
});
