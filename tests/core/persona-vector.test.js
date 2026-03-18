const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const {
  buildPersonaVector,
  personaDistance,
  personaDrift,
  composePersonas,
  steerContext,
  personaToArray,
  PERSONA_DIMENSIONS,
} = require("../../mcp-server/core/persona-vector");

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeProfile(overrides = {}) {
  return {
    metacognitive: {
      activeReflective: 0.3,
      sensingIntuitive: -0.2,
      sequentialGlobal: 0.5,
      problemDecomposition: "top-down",
      explorationStyle: "depth-first",
      verificationBehavior: "test-after",
    },
    sessionShape: {
      avgDuration: 1200000,
      avgTurns: 15,
      avgMessages: 12,
      burstRatio: 0.4,
      explorationRatio: 0.3,
      dominantMode: "mixed",
    },
    toolPreferences: {
      Read: { ratio: 0.8, avgPerSession: 5 },
      Edit: { ratio: 0.6, avgPerSession: 3 },
      Grep: { ratio: 0.5, avgPerSession: 2 },
      Bash: { ratio: 0.3, avgPerSession: 1 },
      Glob: { ratio: 0.2, avgPerSession: 1 },
      Agent: { ratio: 0.1, avgPerSession: 0.5 },
    },
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("PERSONA_DIMENSIONS", () => {
  it("has 9 dimensions", () => {
    assert.equal(PERSONA_DIMENSIONS.length, 9);
  });

  it("includes all expected dimensions", () => {
    assert.ok(PERSONA_DIMENSIONS.includes("activeReflective"));
    assert.ok(PERSONA_DIMENSIONS.includes("thoroughness"));
    assert.ok(PERSONA_DIMENSIONS.includes("iterationSpeed"));
  });
});

describe("buildPersonaVector", () => {
  it("returns all 9 numeric dimensions", () => {
    const pv = buildPersonaVector(makeProfile());
    for (const dim of PERSONA_DIMENSIONS) {
      assert.ok(typeof pv[dim] === "number", `${dim} should be a number`);
    }
  });

  it("all dimensions are in [-1, 1]", () => {
    const pv = buildPersonaVector(makeProfile());
    for (const dim of PERSONA_DIMENSIONS) {
      assert.ok(pv[dim] >= -1 && pv[dim] <= 1, `${dim}: ${pv[dim]}`);
    }
  });

  it("preserves cognitive style dimensions", () => {
    const pv = buildPersonaVector(makeProfile());
    assert.equal(pv.activeReflective, 0.3);
    assert.equal(pv.sensingIntuitive, -0.2);
    assert.equal(pv.sequentialGlobal, 0.5);
  });

  it("handles empty profile gracefully", () => {
    const pv = buildPersonaVector({});
    for (const dim of PERSONA_DIMENSIONS) {
      assert.ok(typeof pv[dim] === "number");
      assert.ok(pv[dim] >= -1 && pv[dim] <= 1);
    }
  });

  it("burst-heavy profile has positive iterationSpeed", () => {
    const pv = buildPersonaVector(makeProfile({
      sessionShape: { avgDuration: 200000, avgTurns: 5, avgMessages: 5, burstRatio: 0.9, explorationRatio: 0.1, dominantMode: "burst" },
    }));
    assert.ok(pv.iterationSpeed > 0);
  });

  it("edit-heavy profile has positive riskTolerance", () => {
    const pv = buildPersonaVector(makeProfile({
      toolPreferences: { Edit: { ratio: 0.9, avgPerSession: 10 }, Read: { ratio: 0.1, avgPerSession: 1 } },
    }));
    assert.ok(pv.riskTolerance > 0);
  });
});

describe("personaToArray", () => {
  it("converts persona to 9D array", () => {
    const pv = buildPersonaVector(makeProfile());
    const arr = personaToArray(pv);
    assert.equal(arr.length, 9);
    assert.equal(arr[0], pv.activeReflective);
  });
});

describe("personaDistance", () => {
  it("returns 0 for identical vectors", () => {
    const pv = buildPersonaVector(makeProfile());
    const d = personaDistance(pv, pv);
    assert.ok(Math.abs(d) < 1e-10);
  });

  it("returns positive distance for different vectors", () => {
    const a = buildPersonaVector(makeProfile());
    const b = buildPersonaVector(makeProfile({
      metacognitive: { activeReflective: -0.8, sensingIntuitive: 0.8, sequentialGlobal: -0.5 },
    }));
    const d = personaDistance(a, b);
    assert.ok(d > 0);
  });

  it("distance is in [0, 2]", () => {
    const a = buildPersonaVector(makeProfile());
    const b = buildPersonaVector(makeProfile({
      metacognitive: { activeReflective: -1, sensingIntuitive: 1, sequentialGlobal: -1 },
    }));
    const d = personaDistance(a, b);
    assert.ok(d >= 0 && d <= 2);
  });
});

describe("personaDrift", () => {
  it("returns zero magnitude for identical vectors", () => {
    const pv = buildPersonaVector(makeProfile());
    const drift = personaDrift(pv, pv);
    assert.ok(drift.magnitude < 1e-10);
  });

  it("returns non-zero magnitude for different vectors", () => {
    const old = buildPersonaVector(makeProfile());
    const newPv = buildPersonaVector(makeProfile({
      metacognitive: { activeReflective: -0.8, sensingIntuitive: 0.8, sequentialGlobal: -0.5 },
    }));
    const drift = personaDrift(old, newPv);
    assert.ok(drift.magnitude > 0);
    assert.ok(typeof drift.interpretation === "string");
    assert.ok(drift.interpretation.length > 0);
  });

  it("direction contains all dimension diffs", () => {
    const old = buildPersonaVector(makeProfile());
    const newPv = buildPersonaVector(makeProfile({
      metacognitive: { activeReflective: -0.5, sensingIntuitive: 0.5, sequentialGlobal: 0 },
    }));
    const drift = personaDrift(old, newPv);
    for (const dim of PERSONA_DIMENSIONS) {
      assert.ok(typeof drift.direction[dim] === "number");
    }
  });
});

describe("composePersonas", () => {
  it("returns neutral vector for empty input", () => {
    const result = composePersonas([], []);
    for (const dim of PERSONA_DIMENSIONS) {
      assert.equal(result[dim], 0);
    }
  });

  it("returns same vector for single input with weight", () => {
    const pv = buildPersonaVector(makeProfile());
    const result = composePersonas([pv], [1]);
    for (const dim of PERSONA_DIMENSIONS) {
      assert.ok(Math.abs(result[dim] - pv[dim]) < 0.02);
    }
  });

  it("weighted average of two vectors", () => {
    const a = { activeReflective: 1, sensingIntuitive: 0, sequentialGlobal: 0, thoroughness: 0, autonomy: 0, verbosity: 0, riskTolerance: 0, focusScope: 0, iterationSpeed: 0 };
    const b = { activeReflective: -1, sensingIntuitive: 0, sequentialGlobal: 0, thoroughness: 0, autonomy: 0, verbosity: 0, riskTolerance: 0, focusScope: 0, iterationSpeed: 0 };
    const result = composePersonas([a, b], [1, 1]);
    assert.equal(result.activeReflective, 0);
  });

  it("all dimensions in [-1, 1]", () => {
    const a = buildPersonaVector(makeProfile());
    const b = buildPersonaVector(makeProfile({
      metacognitive: { activeReflective: -1, sensingIntuitive: 1, sequentialGlobal: -1 },
    }));
    const result = composePersonas([a, b], [3, 1]);
    for (const dim of PERSONA_DIMENSIONS) {
      assert.ok(result[dim] >= -1 && result[dim] <= 1, `${dim}: ${result[dim]}`);
    }
  });
});

describe("steerContext", () => {
  it("returns base context when no adjustments", () => {
    const pv = buildPersonaVector(makeProfile());
    const result = steerContext("Base context.", pv, {});
    assert.equal(result, "Base context.");
  });

  it("returns base context when adjustments are null", () => {
    const pv = buildPersonaVector(makeProfile());
    const result = steerContext("Base context.", pv, null);
    assert.equal(result, "Base context.");
  });

  it("appends steering when drift exceeds threshold", () => {
    const pv = buildPersonaVector(makeProfile());
    const result = steerContext("Base context.", pv, { thoroughness: 1 });
    assert.ok(result.startsWith("Base context."));
    assert.ok(result.length > "Base context.".length);
  });

  it("does not steer when within threshold", () => {
    const pv = { thoroughness: 0.5, autonomy: 0, verbosity: 0, riskTolerance: 0, focusScope: 0, iterationSpeed: 0, activeReflective: 0, sensingIntuitive: 0, sequentialGlobal: 0 };
    const result = steerContext("Base.", pv, { thoroughness: 0.6 });
    assert.equal(result, "Base.");
  });
});
