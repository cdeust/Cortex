const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const { generateContext, generateShortContext } = require("../../mcp-server/core/context-generator");

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeProfile(overrides = {}) {
  return {
    label: "Jarvis",
    entryPoints: [{ pattern: "fix / api / auth", frequency: 5, confidence: 0.8 }],
    recurringPatterns: [
      { pattern: "read before edit", frequency: 4, confidence: 0.6 },
      { pattern: "grep then fix", frequency: 3, confidence: 0.5 },
    ],
    blindSpots: [
      { type: "category", value: "testing", severity: "high", description: "No testing sessions", suggestion: "Add tests" },
    ],
    connectionBridges: [
      { toDomain: "devops", pattern: "deployment pipeline", weight: 2 },
    ],
    metacognitive: {
      explorationStyle: "depth-first",
      problemDecomposition: "top-down",
      activeReflective: 0.3,
      sensingIntuitive: -0.2,
      sequentialGlobal: 0.1,
      verificationBehavior: "test-after",
    },
    sessionShape: { dominantMode: "burst", avgDuration: 300000, avgTurns: 8, burstRatio: 0.7 },
    sessionCount: 25,
    confidence: 0.72,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// generateContext
// ---------------------------------------------------------------------------

describe("generateContext", () => {
  it("includes all sections when profile is fully populated", () => {
    const ctx = generateContext("jarvis", makeProfile());

    assert.ok(ctx.includes("You're working in Jarvis"), "should include domain label");
    assert.ok(ctx.includes("You typically fix / api / auth"), "should include top entry point");
    assert.ok(ctx.includes("read before edit"), "should include first recurring pattern");
    assert.ok(ctx.includes("grep then fix"), "should include second recurring pattern");
    assert.ok(ctx.includes("Blind spot: No testing sessions"), "should include blind spot");
    assert.ok(ctx.includes("Add tests"), "should include blind spot suggestion");
    assert.ok(ctx.includes("connect this to devops"), "should include bridge");
    assert.ok(ctx.includes("depth-first"), "should include exploration style");
    assert.ok(ctx.includes("top-down"), "should include problem decomposition");
    assert.ok(ctx.includes("burst"), "should include session mode");
    assert.ok(ctx.includes("25 prior sessions"), "should include session count");
    assert.ok(ctx.includes("72% confidence"), "should include confidence");
  });

  it("returns default message when profile is null", () => {
    const ctx = generateContext("jarvis", null);
    assert.equal(ctx, "No cognitive profile yet. Building one as we go.");
  });

  it("returns default message when domain is null", () => {
    const ctx = generateContext(null, makeProfile());
    assert.equal(ctx, "No cognitive profile yet. Building one as we go.");
  });

  it("uses domain id as label when label is missing", () => {
    const ctx = generateContext("jarvis", makeProfile({ label: null }));
    assert.ok(ctx.includes("You're working in jarvis"));
  });

  it("handles profile with no entry points", () => {
    const ctx = generateContext("d", makeProfile({ entryPoints: [] }));
    assert.ok(!ctx.includes("You typically"), "should not include entry point section");
  });

  it("handles profile with single recurring pattern", () => {
    const ctx = generateContext("d", makeProfile({
      recurringPatterns: [{ pattern: "read first", frequency: 4, confidence: 0.6 }],
    }));
    assert.ok(ctx.includes("You read first."), "should include single pattern");
    assert.ok(!ctx.includes(", and you"), "should not use conjunction for single pattern");
  });

  it("handles profile with no blind spots", () => {
    const ctx = generateContext("d", makeProfile({ blindSpots: [] }));
    assert.ok(!ctx.includes("Blind spot"), "should skip blind spot section");
  });

  it("handles profile with no bridges", () => {
    const ctx = generateContext("d", makeProfile({ connectionBridges: [] }));
    assert.ok(!ctx.includes("connect this to"), "should skip bridge section");
  });

  it("handles profile with no metacognitive data", () => {
    const ctx = generateContext("d", makeProfile({ metacognitive: null }));
    assert.ok(!ctx.includes("thinker"), "should skip style section");
  });

  it("handles profile with no session shape", () => {
    const ctx = generateContext("d", makeProfile({ sessionShape: null }));
    assert.ok(!ctx.includes("prefer"), "should skip session shape section");
  });

  it("defaults sessionCount and confidence to 0", () => {
    const ctx = generateContext("d", makeProfile({ sessionCount: 0, confidence: 0 }));
    assert.ok(ctx.includes("0 prior sessions"));
    assert.ok(ctx.includes("0% confidence"));
  });

  it("blind spot without suggestion omits suggestion sentence", () => {
    const ctx = generateContext("d", makeProfile({
      blindSpots: [{ type: "category", value: "x", severity: "high", description: "Missing X" }],
    }));
    assert.ok(ctx.includes("Blind spot: Missing X"));
  });
});

// ---------------------------------------------------------------------------
// generateShortContext
// ---------------------------------------------------------------------------

describe("generateShortContext", () => {
  it("produces label + style + mode format", () => {
    const short = generateShortContext("jarvis", makeProfile());
    assert.equal(short, "Jarvis · depth-first · top-down · burst");
  });

  it("returns null when profile is null", () => {
    assert.equal(generateShortContext("d", null), null);
  });

  it("returns null when domain is null", () => {
    assert.equal(generateShortContext(null, makeProfile()), null);
  });

  it("uses domain id when label is missing", () => {
    const short = generateShortContext("mydom", makeProfile({ label: null }));
    assert.ok(short.startsWith("mydom"));
  });

  it("omits style parts when metacognitive is null", () => {
    const short = generateShortContext("d", makeProfile({ metacognitive: null }));
    assert.ok(!short.includes("depth-first"));
  });

  it("omits mode when sessionShape is null", () => {
    const short = generateShortContext("d", makeProfile({ sessionShape: null }));
    assert.ok(!short.includes("burst"));
  });

  it("returns just the label when no metacognitive and no sessionShape", () => {
    const short = generateShortContext("d", makeProfile({ metacognitive: null, sessionShape: null }));
    assert.equal(short, "Jarvis");
  });
});
