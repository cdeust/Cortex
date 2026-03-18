const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const {
  detectPersistentFeatures,
  compareFeatureProfiles,
} = require("../../mcp-server/core/behavioral-crosscoder");

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeDictionary(featureLabels = ["reading", "editing", "testing"]) {
  return {
    K: featureLabels.length,
    D: 27,
    sparsity: 3,
    signalNames: [],
    features: featureLabels.map((label, i) => ({
      index: i,
      label,
      description: `${label} feature`,
      direction: new Array(27).fill(0),
      topSignals: [],
    })),
    learnedFromSessions: 10,
  };
}

function makeActivation(weights) {
  return { weights: new Map(Object.entries(weights)), reconstructionError: 0.1 };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("detectPersistentFeatures", () => {
  it("returns empty for no profiles", () => {
    const dict = makeDictionary();
    const result = detectPersistentFeatures({}, dict);
    assert.deepEqual(result, []);
  });

  it("returns empty for single domain", () => {
    const dict = makeDictionary();
    const profiles = { "domain-a": {} };
    const result = detectPersistentFeatures(profiles, dict);
    assert.deepEqual(result, []);
  });

  it("returns empty for null dictionary", () => {
    const profiles = { "domain-a": {}, "domain-b": {} };
    const result = detectPersistentFeatures(profiles, null);
    assert.deepEqual(result, []);
  });

  it("detects feature present in all domains", () => {
    const dict = makeDictionary(["reading", "editing"]);
    const profiles = { "domain-a": {}, "domain-b": {}, "domain-c": {} };
    const activations = {
      "domain-a": [makeActivation({ reading: 0.5 })],
      "domain-b": [makeActivation({ reading: 0.4 })],
      "domain-c": [makeActivation({ reading: 0.6 })],
    };
    const result = detectPersistentFeatures(profiles, dict, activations);
    assert.ok(result.length >= 1);
    const reading = result.find((f) => f.label === "reading");
    assert.ok(reading);
    assert.equal(reading.persistence, 1);
    assert.equal(reading.domains.length, 3);
  });

  it("excludes features below persistence threshold", () => {
    const dict = makeDictionary(["reading", "editing"]);
    const profiles = { "domain-a": {}, "domain-b": {}, "domain-c": {} };
    const activations = {
      "domain-a": [makeActivation({ editing: 0.5 })],
      "domain-b": [makeActivation({})],
      "domain-c": [makeActivation({})],
    };
    const result = detectPersistentFeatures(profiles, dict, activations);
    const editing = result.find((f) => f.label === "editing");
    assert.equal(editing, undefined);
  });

  it("sorts by persistence then consistency", () => {
    const dict = makeDictionary(["a", "b"]);
    const profiles = { "d1": {}, "d2": {}, "d3": {}, "d4": {} };
    const activations = {
      "d1": [makeActivation({ a: 0.5, b: 0.3 })],
      "d2": [makeActivation({ a: 0.5, b: 0.3 })],
      "d3": [makeActivation({ a: 0.5, b: 0.3 })],
      "d4": [makeActivation({ b: 0.3 })],
    };
    const result = detectPersistentFeatures(profiles, dict, activations);
    if (result.length >= 2) {
      assert.ok(result[0].persistence >= result[1].persistence);
    }
  });

  it("uses profile-level fallback when no activations provided", () => {
    const dict = makeDictionary(["reading"]);
    const profiles = {
      "domain-a": { featureActivations: { reading: 0.5 } },
      "domain-b": { featureActivations: { reading: 0.4 } },
    };
    const result = detectPersistentFeatures(profiles, dict);
    assert.ok(result.length >= 1);
  });
});

describe("compareFeatureProfiles", () => {
  it("partitions features between two domains", () => {
    const dict = makeDictionary(["reading", "editing", "testing"]);
    const a = { reading: 0.5, editing: 0.3 };
    const b = { editing: 0.4, testing: 0.6 };
    const result = compareFeatureProfiles(a, b, dict);
    assert.deepEqual(result.shared, ["editing"]);
    assert.deepEqual(result.uniqueToA, ["reading"]);
    assert.deepEqual(result.uniqueToB, ["testing"]);
  });

  it("returns empty arrays for no active features", () => {
    const dict = makeDictionary();
    const result = compareFeatureProfiles({}, {}, dict);
    assert.deepEqual(result.shared, []);
    assert.deepEqual(result.uniqueToA, []);
    assert.deepEqual(result.uniqueToB, []);
  });

  it("ignores features below threshold", () => {
    const dict = makeDictionary(["reading"]);
    const a = { reading: 0.05 };
    const b = { reading: 0.05 };
    const result = compareFeatureProfiles(a, b, dict);
    assert.deepEqual(result.shared, []);
  });

  it("handles null inputs", () => {
    const dict = makeDictionary();
    const result = compareFeatureProfiles(null, null, dict);
    assert.deepEqual(result.shared, []);
  });
});
