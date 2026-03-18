const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const { classifyStyle, updateStyleEMA } = require("../../mcp-server/core/style-classifier");

// ---------------------------------------------------------------------------
// classifyStyle
// ---------------------------------------------------------------------------

describe("classifyStyle", () => {
  it("returns zeros and defaults for empty input", () => {
    const style = classifyStyle([]);
    assert.equal(style.activeReflective, 0);
    assert.equal(style.sensingIntuitive, 0);
    assert.equal(style.sequentialGlobal, 0);
    assert.equal(typeof style.problemDecomposition, "string");
    assert.equal(typeof style.explorationStyle, "string");
    assert.equal(typeof style.verificationBehavior, "string");
  });

  it("returns zeros and defaults for null input", () => {
    const style = classifyStyle(null);
    assert.equal(style.activeReflective, 0);
    assert.equal(style.sensingIntuitive, 0);
    assert.equal(style.sequentialGlobal, 0);
  });

  it("returns valid structure with all expected keys", () => {
    const convs = [
      {
        toolsUsed: ["Edit", "Edit", "Write", "Read"],
        duration: 5,
        durationMinutes: 5,
        summary: "try to fix the bug quickly",
        filesTouched: ["src/a.js", "src/b.js"],
      },
    ];
    const style = classifyStyle(convs);
    assert.ok("activeReflective" in style);
    assert.ok("sensingIntuitive" in style);
    assert.ok("sequentialGlobal" in style);
    assert.ok("problemDecomposition" in style);
    assert.ok("explorationStyle" in style);
    assert.ok("verificationBehavior" in style);

    // Numeric dimensions in [-1, 1]
    assert.ok(style.activeReflective >= -1 && style.activeReflective <= 1);
    assert.ok(style.sensingIntuitive >= -1 && style.sensingIntuitive <= 1);
    assert.ok(style.sequentialGlobal >= -1 && style.sequentialGlobal <= 1);
  });

  it("active style — short sessions, heavy edits, trial keywords", () => {
    const convs = Array.from({ length: 5 }, () => ({
      toolsUsed: ["Edit", "Edit", "Edit", "Write", "Read"],
      durationMinutes: 5,
      summary: "try quick iterate experiment tweak",
      filesTouched: ["src/a.js"],
    }));
    const style = classifyStyle(convs);
    // Should lean active (positive)
    assert.ok(style.activeReflective > 0, `activeReflective=${style.activeReflective} should be > 0`);
  });

  it("reflective style — long sessions, heavy reads, planning keywords", () => {
    const convs = Array.from({ length: 5 }, () => ({
      toolsUsed: ["Read", "Read", "Read", "Grep", "Edit"],
      durationMinutes: 45,
      summary: "plan strategy review analyse evaluate consider",
      filesTouched: ["src/a.js"],
    }));
    const style = classifyStyle(convs);
    assert.ok(style.activeReflective < 0, `activeReflective=${style.activeReflective} should be < 0`);
  });

  it("sensing style — concrete keywords, many files", () => {
    const convs = Array.from({ length: 5 }, () => ({
      toolsUsed: [],
      summary: "example specifically instance step-by-step file line function",
      filesTouched: Array.from({ length: 10 }, (_, i) => `src/file${i}.js`),
    }));
    const style = classifyStyle(convs);
    assert.ok(style.sensingIntuitive > 0, `sensingIntuitive=${style.sensingIntuitive} should be > 0`);
  });

  it("intuitive style — abstract keywords", () => {
    const convs = Array.from({ length: 5 }, () => ({
      toolsUsed: [],
      summary: "architecture pattern system design module abstraction principle paradigm framework",
      filesTouched: [],
    }));
    const style = classifyStyle(convs);
    assert.ok(style.sensingIntuitive < 0, `sensingIntuitive=${style.sensingIntuitive} should be < 0`);
  });

  it("problemDecomposition defaults to top-down", () => {
    const style = classifyStyle([]);
    assert.equal(style.problemDecomposition, "top-down");
  });

  it("explorationStyle defaults to depth-first", () => {
    const style = classifyStyle([]);
    assert.equal(style.explorationStyle, "depth-first");
  });

  it("verificationBehavior defaults to no-test", () => {
    const style = classifyStyle([]);
    assert.equal(style.verificationBehavior, "no-test");
  });

  it("detects test-first verification when reads >= edits and test content present", () => {
    const convs = Array.from({ length: 5 }, () => ({
      toolsUsed: ["Read", "Read", "Grep", "Edit"],
      allText: "write unit test assert expect coverage",
      summary: "",
    }));
    const style = classifyStyle(convs);
    assert.equal(style.verificationBehavior, "test-first");
  });

  it("depth-first exploration — high calls per file", () => {
    const convs = Array.from({ length: 5 }, () => ({
      toolsUsed: Array(20).fill("Read"),
      filesTouched: ["src/a.js", "src/b.js"],
    }));
    const style = classifyStyle(convs);
    assert.equal(style.explorationStyle, "depth-first");
  });

  it("breadth-first exploration — low calls per file", () => {
    const convs = Array.from({ length: 5 }, () => ({
      toolsUsed: ["Read", "Edit"],
      filesTouched: Array.from({ length: 10 }, (_, i) => `src/f${i}.js`),
    }));
    const style = classifyStyle(convs);
    assert.equal(style.explorationStyle, "breadth-first");
  });
});

// ---------------------------------------------------------------------------
// updateStyleEMA
// ---------------------------------------------------------------------------

describe("updateStyleEMA", () => {
  it("returns new observation when old is null", () => {
    const obs = { activeReflective: 0.5, sensingIntuitive: -0.3, sequentialGlobal: 0.1, problemDecomposition: "bottom-up" };
    const result = updateStyleEMA(null, obs);
    assert.deepEqual(result, obs);
  });

  it("returns old style when new observation is null", () => {
    const old = { activeReflective: 0.5, sensingIntuitive: -0.3, sequentialGlobal: 0.1, problemDecomposition: "top-down" };
    const result = updateStyleEMA(old, null);
    assert.deepEqual(result, old);
  });

  it("blends with alpha=0.5", () => {
    const old = { activeReflective: 1.0, sensingIntuitive: 0, sequentialGlobal: -1.0, problemDecomposition: "top-down", explorationStyle: "depth-first", verificationBehavior: "no-test" };
    const obs = { activeReflective: -1.0, sensingIntuitive: 0, sequentialGlobal: 1.0, problemDecomposition: "bottom-up", explorationStyle: "breadth-first", verificationBehavior: "test-first" };
    const result = updateStyleEMA(old, obs, 0.5);

    // Numeric: 0.5 * new + 0.5 * old
    assert.ok(Math.abs(result.activeReflective - 0) < 0.001);
    assert.ok(Math.abs(result.sequentialGlobal - 0) < 0.001);
  });

  it("alpha=0.1 preserves old style mostly", () => {
    const old = { activeReflective: 0.8, sensingIntuitive: 0.6, sequentialGlobal: -0.4, problemDecomposition: "top-down", explorationStyle: "depth-first", verificationBehavior: "test-after" };
    const obs = { activeReflective: -0.8, sensingIntuitive: -0.6, sequentialGlobal: 0.4, problemDecomposition: "bottom-up", explorationStyle: "breadth-first", verificationBehavior: "test-first" };
    const result = updateStyleEMA(old, obs, 0.1);

    // Should be much closer to old
    assert.ok(Math.abs(result.activeReflective - 0.64) < 0.01, `ar=${result.activeReflective} expected ~0.64`);
    // Categorical: alpha < 0.5 → keeps old
    assert.equal(result.problemDecomposition, "top-down");
    assert.equal(result.explorationStyle, "depth-first");
    assert.equal(result.verificationBehavior, "test-after");
  });

  it("categorical dimensions switch at alpha>=0.5", () => {
    const old = { activeReflective: 0, sensingIntuitive: 0, sequentialGlobal: 0, problemDecomposition: "top-down", explorationStyle: "depth-first", verificationBehavior: "no-test" };
    const obs = { activeReflective: 0, sensingIntuitive: 0, sequentialGlobal: 0, problemDecomposition: "bottom-up", explorationStyle: "breadth-first", verificationBehavior: "test-first" };

    const result = updateStyleEMA(old, obs, 0.5);
    assert.equal(result.problemDecomposition, "bottom-up");
    assert.equal(result.explorationStyle, "breadth-first");
    assert.equal(result.verificationBehavior, "test-first");
  });

  it("clamps numeric dimensions to [-1, 1]", () => {
    const old = { activeReflective: 1.0, sensingIntuitive: -1.0, sequentialGlobal: 0 };
    const obs = { activeReflective: 1.0, sensingIntuitive: -1.0, sequentialGlobal: 0 };
    const result = updateStyleEMA(old, obs, 0.9);
    assert.ok(result.activeReflective <= 1.0);
    assert.ok(result.sensingIntuitive >= -1.0);
  });

  it("handles missing fields gracefully (defaults to 0)", () => {
    const old = { activeReflective: 0.5 };
    const obs = { sensingIntuitive: -0.3 };
    const result = updateStyleEMA(old, obs, 0.5);
    // activeReflective: 0.5 * 0 + 0.5 * 0.5 = 0.25
    assert.ok(Math.abs(result.activeReflective - 0.25) < 0.01);
    // sensingIntuitive: 0.5 * -0.3 + 0.5 * 0 = -0.15
    assert.ok(Math.abs(result.sensingIntuitive - (-0.15)) < 0.01);
  });
});
