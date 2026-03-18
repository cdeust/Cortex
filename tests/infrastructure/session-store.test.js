const { describe, it } = require("node:test");
const assert = require("node:assert/strict");

const { loadSessionLog, saveSessionLog } = require("../../mcp-server/infrastructure/session-store");

describe("session-store", () => {
  describe("loadSessionLog", () => {
    it("returns a valid structure with sessions array", () => {
      const log = loadSessionLog();

      assert.ok(log, "loadSessionLog should return an object");
      assert.ok(Array.isArray(log.sessions), "sessions should be an array");
    });
  });

  describe("saveSessionLog", () => {
    it("does not throw when saving current log", () => {
      const log = loadSessionLog();

      assert.doesNotThrow(() => {
        saveSessionLog(log);
      });
    });
  });
});
