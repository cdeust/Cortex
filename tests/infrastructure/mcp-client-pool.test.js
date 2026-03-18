const { describe, it, beforeEach, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const { ConnectionError } = require("../../mcp-server/errors");

// We test the pool's config loading logic without spawning real processes.
// The pool reads config from MCP_CONNECTIONS_PATH, so we test that path.

describe("mcp-client-pool", () => {
  // Import after setup so module loads cleanly
  const { getClient, closeClient, closeAll } = require("../../mcp-server/infrastructure/mcp-client-pool");

  afterEach(() => {
    closeAll();
  });

  describe("getClient", () => {
    it("throws ConnectionError for unknown server", async () => {
      await assert.rejects(
        () => getClient("nonexistent-server-12345"),
        (err) => {
          assert.ok(err instanceof ConnectionError);
          assert.ok(err.message.includes("nonexistent-server-12345"));
          return true;
        }
      );
    });
  });

  describe("closeClient", () => {
    it("is safe to call for non-existent server", () => {
      // Should not throw
      closeClient("never-connected");
    });
  });

  describe("closeAll", () => {
    it("is safe to call when pool is empty", () => {
      // Should not throw
      closeAll();
    });

    it("can be called multiple times", () => {
      closeAll();
      closeAll();
    });
  });
});
