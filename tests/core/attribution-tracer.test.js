const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const {
  traceAttribution,
  buildAttributionNodes,
  computeEdgeWeights,
} = require("../../mcp-server/core/attribution-tracer");
const { buildSeedDictionary } = require("../../mcp-server/core/sparse-dictionary");

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeConv(overrides = {}) {
  return {
    sessionId: "test",
    toolsUsed: ["Read", "Edit", "Grep"],
    allText: "fix the bug in auth module",
    firstMessage: "fix the auth bug",
    duration: 600000,
    turnCount: 10,
    ...overrides,
  };
}

function makeProfile(overrides = {}) {
  return {
    id: "test-domain",
    label: "Test",
    confidence: 0.7,
    sessionCount: 10,
    metacognitive: {
      activeReflective: 0.3,
      sensingIntuitive: -0.2,
      sequentialGlobal: 0.5,
      problemDecomposition: "top-down",
      explorationStyle: "depth-first",
      verificationBehavior: "test-after",
    },
    entryPoints: [],
    recurringPatterns: [],
    toolPreferences: {},
    sessionShape: { avgDuration: 600000, avgTurns: 10, avgMessages: 15, burstRatio: 0.5, explorationRatio: 0.3, dominantMode: "mixed" },
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("buildAttributionNodes", () => {
  it("creates nodes for all layers", () => {
    const dict = buildSeedDictionary();
    const nodes = buildAttributionNodes(makeProfile(), dict);
    const layers = new Set(nodes.map((n) => n.layer));
    assert.ok(layers.has("input"));
    assert.ok(layers.has("extractor"));
    assert.ok(layers.has("classifier"));
    assert.ok(layers.has("feature"));
    assert.ok(layers.has("aggregator"));
    assert.ok(layers.has("output"));
  });

  it("has 27 input nodes", () => {
    const dict = buildSeedDictionary();
    const nodes = buildAttributionNodes(makeProfile(), dict);
    const inputs = nodes.filter((n) => n.layer === "input");
    assert.equal(inputs.length, 27);
  });

  it("has 4 extractor nodes", () => {
    const dict = buildSeedDictionary();
    const nodes = buildAttributionNodes(makeProfile(), dict);
    const extractors = nodes.filter((n) => n.layer === "extractor");
    assert.equal(extractors.length, 4);
  });

  it("has 6 classifier nodes", () => {
    const dict = buildSeedDictionary();
    const nodes = buildAttributionNodes(makeProfile(), dict);
    const classifiers = nodes.filter((n) => n.layer === "classifier");
    assert.equal(classifiers.length, 6);
  });

  it("classifier nodes have activation from profile", () => {
    const dict = buildSeedDictionary();
    const nodes = buildAttributionNodes(makeProfile(), dict);
    const ar = nodes.find((n) => n.id === "classifier:activeReflective");
    assert.equal(ar.activation, 0.3);
  });

  it("feature nodes match dictionary size", () => {
    const dict = buildSeedDictionary();
    const nodes = buildAttributionNodes(makeProfile(), dict);
    const features = nodes.filter((n) => n.layer === "feature");
    assert.equal(features.length, dict.features.length);
  });

  it("handles null dictionary", () => {
    const nodes = buildAttributionNodes(makeProfile(), null);
    const features = nodes.filter((n) => n.layer === "feature");
    assert.equal(features.length, 0);
  });
});

describe("computeEdgeWeights", () => {
  it("produces edges between layers", () => {
    const dict = buildSeedDictionary();
    const edges = computeEdgeWeights([makeConv()], makeProfile(), dict);
    assert.ok(edges.length > 0);
  });

  it("all edge weights are non-negative", () => {
    const dict = buildSeedDictionary();
    const edges = computeEdgeWeights([makeConv()], makeProfile(), dict);
    for (const edge of edges) {
      assert.ok(edge.weight >= 0, `Edge ${edge.source} → ${edge.target}: ${edge.weight}`);
    }
  });

  it("includes aggregator → output edge", () => {
    const dict = buildSeedDictionary();
    const edges = computeEdgeWeights([makeConv()], makeProfile(), dict);
    const aggToOut = edges.find((e) => e.source === "aggregator:profile" && e.target === "output:context");
    assert.ok(aggToOut);
  });

  it("handles empty conversations", () => {
    const dict = buildSeedDictionary();
    const edges = computeEdgeWeights([], makeProfile(), dict);
    assert.ok(edges.length > 0); // structural edges still present
  });
});

describe("traceAttribution", () => {
  it("returns graph with nodes and edges", () => {
    const dict = buildSeedDictionary();
    const graph = traceAttribution([makeConv()], dict, makeProfile());
    assert.ok(graph.nodes.length > 0);
    assert.ok(graph.edges.length > 0);
  });

  it("returns empty graph for no conversations", () => {
    const dict = buildSeedDictionary();
    const graph = traceAttribution([], dict, makeProfile());
    assert.equal(graph.nodes.length, 0);
    assert.equal(graph.edges.length, 0);
  });

  it("returns empty graph for null profile", () => {
    const dict = buildSeedDictionary();
    const graph = traceAttribution([makeConv()], dict, null);
    assert.equal(graph.nodes.length, 0);
  });

  it("updates input node activations from conversations", () => {
    const dict = buildSeedDictionary();
    const graph = traceAttribution(
      [makeConv({ toolsUsed: ["Read", "Read", "Read"] })],
      dict,
      makeProfile(),
    );
    const readNode = graph.nodes.find((n) => n.id === "input:tool:Read");
    assert.ok(readNode);
    assert.ok(readNode.activation > 0);
  });

  it("samples at most 20 conversations", () => {
    const dict = buildSeedDictionary();
    const convs = Array.from({ length: 50 }, (_, i) => makeConv({ sessionId: `s-${i}` }));
    // Should not throw or be slow
    const graph = traceAttribution(convs, dict, makeProfile());
    assert.ok(graph.nodes.length > 0);
  });
});
