const { describe, it } = require("node:test");
const assert = require("node:assert/strict");

const { loadProfiles, saveProfiles } = require("../../mcp-server/infrastructure/profile-store");

describe("profile-store", () => {
  describe("loadProfiles", () => {
    it("returns a valid v2 structure", () => {
      const profiles = loadProfiles();

      assert.ok(profiles, "loadProfiles should return an object");
      assert.ok(profiles.version >= 2, "version should be at least 2");
      assert.ok("domains" in profiles, "should have domains property");
      assert.equal(typeof profiles.domains, "object", "domains should be an object");
    });
  });

  describe("saveProfiles", () => {
    it("does not throw when saving current profiles", () => {
      const profiles = loadProfiles();

      assert.doesNotThrow(() => {
        saveProfiles(profiles);
      });

      // Verify updatedAt was set
      assert.ok(profiles.updatedAt, "updatedAt should be set after save");
      assert.ok(
        !isNaN(Date.parse(profiles.updatedAt)),
        "updatedAt should be a valid ISO date"
      );
    });
  });
});
