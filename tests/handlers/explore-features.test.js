const { describe, it } = require("node:test");
const assert = require("node:assert/strict");

const { handler, schema } = require("../../mcp-server/handlers/explore-features");

// ---------------------------------------------------------------------------
// Tests — handler reads from disk (same pattern as other handler tests)
// ---------------------------------------------------------------------------

describe("explore-features schema", () => {
  it("requires mode field", () => {
    assert.ok(schema.inputSchema.required.includes("mode"));
  });

  it("has description", () => {
    assert.ok(schema.description.length > 0);
  });

  it("defines mode enum", () => {
    const modeEnum = schema.inputSchema.properties.mode.enum;
    assert.ok(modeEnum.includes("features"));
    assert.ok(modeEnum.includes("attribution"));
    assert.ok(modeEnum.includes("persona"));
    assert.ok(modeEnum.includes("crosscoder"));
  });
});

describe("explore-features handler", () => {
  describe("mode: features", () => {
    it("returns ok or no_data status", async () => {
      const result = await handler({ mode: "features" });
      assert.ok(result.status === "ok" || result.status === "no_data");
    });

    it("returns dictionary when profiles exist", async () => {
      const result = await handler({ mode: "features" });
      if (result.status === "ok") {
        assert.ok(result.dictionary);
        assert.ok(typeof result.dictionary.K === "number");
        assert.ok(typeof result.dictionary.D === "number");
        assert.ok(Array.isArray(result.dictionary.features));
      }
    });
  });

  describe("mode: attribution", () => {
    it("returns graph or no_data", async () => {
      const result = await handler({ mode: "attribution" });
      assert.ok(result.status === "ok" || result.status === "no_data" || result.status === "error");
      if (result.status === "ok") {
        assert.ok(result.graph);
        assert.ok(result.domain);
      }
    });

    it("returns error for unknown domain", async () => {
      const result = await handler({ mode: "attribution", domain: "definitely-not-a-real-domain-xyz" });
      // Either no_data (no profiles at all) or error (domain not found)
      assert.ok(result.status === "error" || result.status === "no_data");
    });
  });

  describe("mode: persona", () => {
    it("returns persona data or no_data", async () => {
      const result = await handler({ mode: "persona" });
      assert.ok(result.status === "ok" || result.status === "no_data");
      if (result.status === "ok") {
        assert.ok(result.dimensions);
        assert.ok(result.domains || result.persona);
      }
    });

    it("returns error for unknown domain", async () => {
      const result = await handler({ mode: "persona", domain: "definitely-not-a-real-domain-xyz" });
      assert.ok(result.status === "error" || result.status === "no_data");
    });
  });

  describe("mode: crosscoder", () => {
    it("returns persistent features or no_data", async () => {
      const result = await handler({ mode: "crosscoder" });
      assert.ok(result.status === "ok" || result.status === "no_data");
      if (result.status === "ok") {
        assert.ok(Array.isArray(result.persistentFeatures));
      }
    });

    it("returns error for unknown domain comparison", async () => {
      const result = await handler({
        mode: "crosscoder",
        domain: "definitely-not-a-real-domain-xyz",
        compare_domain: "also-not-real",
      });
      assert.ok(result.status === "error" || result.status === "no_data");
    });
  });

  it("returns error for unknown mode", async () => {
    const result = await handler({ mode: "unknown_mode_xyz" });
    // Either error (unknown mode) or no_data (no profiles)
    assert.ok(result.status === "error" || result.status === "no_data");
  });
});
