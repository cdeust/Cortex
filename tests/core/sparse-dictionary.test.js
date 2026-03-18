const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const {
  extractSessionActivation,
  learnDictionary,
  encodeSession,
  labelFeature,
  buildSeedDictionary,
  omp,
  SIGNAL_NAMES,
  D,
} = require("../../mcp-server/core/sparse-dictionary");
const { norm, normalize } = require("../../mcp-server/shared/linear-algebra");

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeConv(overrides = {}) {
  return {
    sessionId: "test-session",
    toolsUsed: ["Read", "Edit", "Grep", "Bash"],
    allText: "fix the bug in the authentication module",
    firstMessage: "fix the auth bug",
    duration: 600000,
    turnCount: 10,
    messageCount: 20,
    keywords: new Set(["authentication", "module"]),
    ...overrides,
  };
}

function makeConversations(n, overrides = {}) {
  return Array.from({ length: n }, (_, i) => makeConv({ sessionId: `session-${i}`, ...overrides }));
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("SIGNAL_NAMES", () => {
  it("has 27 dimensions", () => {
    assert.equal(SIGNAL_NAMES.length, 27);
    assert.equal(D, 27);
  });

  it("has no duplicates", () => {
    assert.equal(new Set(SIGNAL_NAMES).size, SIGNAL_NAMES.length);
  });
});

describe("extractSessionActivation", () => {
  it("returns a 27-dimensional vector", () => {
    const result = extractSessionActivation(makeConv());
    assert.equal(result.length, 27);
  });

  it("all values are finite numbers", () => {
    const result = extractSessionActivation(makeConv());
    for (const v of result) {
      assert.ok(Number.isFinite(v), `Expected finite, got ${v}`);
    }
  });

  it("tool ratios sum to approximately 1 for sessions with tools", () => {
    const result = extractSessionActivation(makeConv({ toolsUsed: ["Read", "Edit", "Read"] }));
    const toolSum = result.slice(0, 7).reduce((s, v) => s + v, 0);
    assert.ok(Math.abs(toolSum - 1) < 0.01, `Tool ratios sum: ${toolSum}`);
  });

  it("handles empty conversation", () => {
    const result = extractSessionActivation({});
    assert.equal(result.length, 27);
  });

  it("burst indicator is 1 for short sessions", () => {
    const result = extractSessionActivation(makeConv({ duration: 300000 }));
    assert.equal(result[13], 1); // tmp:burst
  });

  it("exploration indicator is 1 for high-turn sessions", () => {
    const result = extractSessionActivation(makeConv({ turnCount: 30 }));
    assert.equal(result[14], 1); // tmp:exploration
  });
});

describe("buildSeedDictionary", () => {
  it("returns valid dictionary structure", () => {
    const dict = buildSeedDictionary();
    assert.equal(dict.K, 8);
    assert.equal(dict.D, 27);
    assert.equal(dict.sparsity, 3);
    assert.equal(dict.learnedFromSessions, 0);
    assert.equal(dict.features.length, 8);
  });

  it("all atoms are unit vectors", () => {
    const dict = buildSeedDictionary();
    for (const feature of dict.features) {
      const n = norm(feature.direction);
      assert.ok(Math.abs(n - 1) < 0.01, `Norm of ${feature.label}: ${n}`);
    }
  });

  it("features have labels and descriptions", () => {
    const dict = buildSeedDictionary();
    for (const feature of dict.features) {
      assert.ok(feature.label.length > 0);
      assert.ok(feature.description.length > 0);
      assert.ok(feature.topSignals.length > 0);
    }
  });
});

describe("omp", () => {
  it("returns empty for zero signal", () => {
    const atoms = [normalize([1, 0, 0]), normalize([0, 1, 0])];
    const { indices, coefficients } = omp([0, 0, 0], atoms, 2);
    assert.equal(indices.length, 0);
  });

  it("finds correct single atom", () => {
    const atoms = [normalize([1, 0, 0]), normalize([0, 1, 0]), normalize([0, 0, 1])];
    const { indices, coefficients } = omp([5, 0, 0], atoms, 1);
    assert.equal(indices.length, 1);
    assert.equal(indices[0], 0);
    assert.ok(Math.abs(coefficients[0] - 5) < 0.01);
  });

  it("respects sparsity constraint", () => {
    const atoms = [
      normalize([1, 0, 0]), normalize([0, 1, 0]),
      normalize([0, 0, 1]), normalize([1, 1, 0]),
    ];
    const { indices } = omp([1, 1, 1], atoms, 2);
    assert.ok(indices.length <= 2);
  });

  it("reconstructs signal with low error for matching atoms", () => {
    const atoms = [normalize([1, 0]), normalize([0, 1])];
    const signal = [3, 4];
    const { residual } = omp(signal, atoms, 2);
    assert.ok(norm(residual) < 0.01);
  });
});

describe("learnDictionary", () => {
  it("returns seed dictionary for < 10 sessions", () => {
    const convs = makeConversations(5);
    const dict = learnDictionary(convs);
    assert.equal(dict.learnedFromSessions, 0);
    assert.equal(dict.K, 8);
  });

  it("returns seed dictionary for null input", () => {
    const dict = learnDictionary(null);
    assert.equal(dict.learnedFromSessions, 0);
  });

  it("learns dictionary for >= 10 sessions", () => {
    const convs = makeConversations(15, {
      toolsUsed: ["Read", "Edit", "Grep", "Bash", "Glob"],
      allText: "implement the new feature with proper testing and architecture design",
      duration: 1200000,
      turnCount: 15,
    });
    const dict = learnDictionary(convs, { K: 5, sparsity: 2, iterations: 2 });
    assert.equal(dict.learnedFromSessions, 15);
    assert.ok(dict.K <= 5);
    assert.equal(dict.D, 27);
    assert.equal(dict.sparsity, 2);
  });

  it("all learned atoms are unit vectors", () => {
    const convs = makeConversations(12);
    const dict = learnDictionary(convs, { K: 4, sparsity: 2, iterations: 2 });
    for (const feature of dict.features) {
      const n = norm(feature.direction);
      assert.ok(Math.abs(n - 1) < 0.01, `Norm: ${n}`);
    }
  });

  it("features have auto-generated labels", () => {
    const convs = makeConversations(12);
    const dict = learnDictionary(convs, { K: 4, sparsity: 2, iterations: 2 });
    for (const feature of dict.features) {
      assert.ok(feature.label.length > 0);
      assert.ok(feature.description.length > 0);
    }
  });
});

describe("encodeSession", () => {
  it("returns sparse activation with reconstruction error", () => {
    const dict = buildSeedDictionary();
    const result = encodeSession(makeConv(), dict);
    assert.ok(result.weights instanceof Map);
    assert.ok(typeof result.reconstructionError === "number");
    assert.ok(result.reconstructionError >= 0);
  });

  it("respects sparsity constraint", () => {
    const dict = buildSeedDictionary();
    const result = encodeSession(makeConv(), dict);
    assert.ok(result.weights.size <= dict.sparsity);
  });

  it("weights are non-zero", () => {
    const dict = buildSeedDictionary();
    const result = encodeSession(makeConv({
      toolsUsed: ["Edit", "Edit", "Edit", "Bash"],
      allText: "fix the critical bug immediately",
      duration: 180000,
    }), dict);
    for (const [, w] of result.weights) {
      assert.ok(Math.abs(w) > 1e-10);
    }
  });
});

describe("labelFeature", () => {
  it("generates meaningful label from direction", () => {
    const direction = new Array(27).fill(0);
    direction[1] = 0.8; // tool:Edit
    direction[13] = 0.5; // tmp:burst
    const result = labelFeature(normalize(direction), 0);
    assert.ok(result.label.length > 0);
    assert.ok(result.topSignals.length > 0);
  });

  it("handles zero direction", () => {
    const result = labelFeature(new Array(27).fill(0), 5);
    assert.equal(result.label, "feature-5");
  });
});
