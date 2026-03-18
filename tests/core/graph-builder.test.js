const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const { buildGraph } = require("../../mcp-server/core/graph-builder");

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeProfiles(domains = {}) {
  return { domains };
}

function makeDomainProfile(overrides = {}) {
  return {
    id: "test-domain",
    label: "Test Domain",
    projects: ["-Users-dev-test"],
    confidence: 0.75,
    sessionCount: 20,
    entryPoints: [
      { pattern: "fix / api / auth", frequency: 5, confidence: 0.8 },
      { pattern: "deploy / pipeline", frequency: 3, confidence: 0.4 },
    ],
    recurringPatterns: [
      { pattern: "read before edit", frequency: 8, confidence: 0.6 },
    ],
    toolPreferences: {
      Read: { ratio: 0.9, avgPerSession: 6 },
      Edit: { ratio: 0.7, avgPerSession: 4 },
      Grep: { ratio: 0.5, avgPerSession: 3 },
    },
    connectionBridges: [],
    blindSpots: [
      { type: "category", value: "testing", severity: "high", description: "No testing", suggestion: "Add tests" },
    ],
    metacognitive: {},
    sessionShape: {},
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// buildGraph
// ---------------------------------------------------------------------------

describe("buildGraph", () => {
  it("returns empty arrays for empty profiles", () => {
    const result = buildGraph(makeProfiles());
    assert.deepEqual(result.nodes, []);
    assert.deepEqual(result.edges, []);
    assert.deepEqual(result.blindSpotRegions, []);
  });

  it("creates a domain hub node", () => {
    const profiles = makeProfiles({
      alpha: makeDomainProfile({ label: "Alpha", sessionCount: 15, confidence: 0.6 }),
    });
    const result = buildGraph(profiles);

    const hubNodes = result.nodes.filter((n) => n.type === "domain");
    assert.equal(hubNodes.length, 1);
    assert.equal(hubNodes[0].label, "Alpha");
    assert.equal(hubNodes[0].domain, "alpha");
    assert.equal(hubNodes[0].confidence, 0.6);
    assert.equal(hubNodes[0].sessionCount, 15);
    assert.equal(hubNodes[0].color, "#6366f1");
    assert.ok(hubNodes[0].size >= 8);
  });

  it("creates entry-point nodes with edges to hub", () => {
    const profiles = makeProfiles({
      alpha: makeDomainProfile(),
    });
    const result = buildGraph(profiles);

    const epNodes = result.nodes.filter((n) => n.type === "entry-point");
    assert.equal(epNodes.length, 2);
    assert.equal(epNodes[0].label, "fix / api / auth");
    assert.equal(epNodes[0].domain, "alpha");
    assert.equal(epNodes[0].color, "#00d4ff");
    assert.ok(epNodes[0].frequency > 0);

    const epEdges = result.edges.filter((e) => e.type === "has-entry");
    assert.equal(epEdges.length, 2);
    // Each edge should connect hub to entry point
    const hub = result.nodes.find((n) => n.type === "domain");
    assert.ok(epEdges.every((e) => e.source === hub.id));
  });

  it("creates recurring-pattern nodes with edges to hub", () => {
    const profiles = makeProfiles({
      alpha: makeDomainProfile(),
    });
    const result = buildGraph(profiles);

    const patternNodes = result.nodes.filter((n) => n.type === "recurring-pattern");
    assert.equal(patternNodes.length, 1);
    assert.equal(patternNodes[0].label, "read before edit");
    assert.equal(patternNodes[0].color, "#10b981");

    const patternEdges = result.edges.filter((e) => e.type === "has-pattern");
    assert.equal(patternEdges.length, 1);
  });

  it("creates tool-preference nodes (top 5) with edges to hub", () => {
    const profiles = makeProfiles({
      alpha: makeDomainProfile(),
    });
    const result = buildGraph(profiles);

    const toolNodes = result.nodes.filter((n) => n.type === "tool-preference");
    assert.equal(toolNodes.length, 3); // Read, Edit, Grep
    assert.equal(toolNodes[0].color, "#f59e0b");
    assert.ok(toolNodes[0].ratio > 0);

    const toolEdges = result.edges.filter((e) => e.type === "uses-tool");
    assert.equal(toolEdges.length, 3);
  });

  it("limits tool nodes to top 5", () => {
    const tools = {};
    for (let i = 0; i < 8; i++) {
      tools[`Tool${i}`] = { ratio: (8 - i) / 10, avgPerSession: i + 1 };
    }
    const profiles = makeProfiles({
      alpha: makeDomainProfile({ toolPreferences: tools }),
    });
    const result = buildGraph(profiles);

    const toolNodes = result.nodes.filter((n) => n.type === "tool-preference");
    assert.equal(toolNodes.length, 5, "should limit to top 5 tools");
  });

  it("creates bridge edges between domains", () => {
    const profiles = makeProfiles({
      alpha: makeDomainProfile({
        connectionBridges: [{ toDomain: "beta", pattern: "structural-edge", weight: 2 }],
      }),
      beta: makeDomainProfile({
        connectionBridges: [{ toDomain: "alpha", pattern: "structural-edge", weight: 2 }],
      }),
    });
    const result = buildGraph(profiles);

    const bridgeEdges = result.edges.filter((e) => e.type === "bridge");
    assert.ok(bridgeEdges.length >= 1, "should have bridge edges");
    assert.ok(bridgeEdges[0].weight > 0);
    assert.ok(bridgeEdges[0].label);
  });

  it("collects blind spot regions", () => {
    const profiles = makeProfiles({
      alpha: makeDomainProfile({
        blindSpots: [
          { type: "category", value: "testing", severity: "high", description: "No testing", suggestion: "Add tests" },
          { type: "tool", value: "Grep", severity: "medium", description: "Low Grep usage", suggestion: "Use Grep" },
        ],
      }),
    });
    const result = buildGraph(profiles);

    assert.equal(result.blindSpotRegions.length, 2);
    assert.equal(result.blindSpotRegions[0].domain, "alpha");
    assert.equal(result.blindSpotRegions[0].type, "category");
    assert.equal(result.blindSpotRegions[0].value, "testing");
    assert.equal(result.blindSpotRegions[0].severity, "high");
    assert.ok(result.blindSpotRegions[0].description);
    assert.ok(result.blindSpotRegions[0].suggestion);
  });

  it("filterDomain limits output to one domain", () => {
    const profiles = makeProfiles({
      alpha: makeDomainProfile({ label: "Alpha" }),
      beta: makeDomainProfile({ label: "Beta" }),
    });
    const result = buildGraph(profiles, "alpha");

    // Only alpha nodes should be present
    const domains = result.nodes.filter((n) => n.type === "domain");
    assert.equal(domains.length, 1);
    assert.equal(domains[0].label, "Alpha");

    // All nodes should be in alpha domain
    for (const node of result.nodes) {
      assert.equal(node.domain, "alpha");
    }
  });

  it("filterDomain with non-existent domain returns empty", () => {
    const profiles = makeProfiles({
      alpha: makeDomainProfile(),
    });
    const result = buildGraph(profiles, "nonexistent");

    assert.deepEqual(result.nodes, []);
    assert.deepEqual(result.edges, []);
    assert.deepEqual(result.blindSpotRegions, []);
  });

  it("node IDs are unique", () => {
    const profiles = makeProfiles({
      alpha: makeDomainProfile(),
      beta: makeDomainProfile(),
    });
    const result = buildGraph(profiles);

    const ids = result.nodes.map((n) => n.id);
    const uniqueIds = new Set(ids);
    assert.equal(ids.length, uniqueIds.size, "all node IDs should be unique");
  });

  it("handles domain with no entry points, patterns, tools, bridges, or blind spots", () => {
    const profiles = makeProfiles({
      empty: makeDomainProfile({
        entryPoints: [],
        recurringPatterns: [],
        toolPreferences: {},
        connectionBridges: [],
        blindSpots: [],
      }),
    });
    const result = buildGraph(profiles);

    // Should still have the hub node
    assert.equal(result.nodes.length, 1);
    assert.equal(result.nodes[0].type, "domain");
    assert.deepEqual(result.blindSpotRegions, []);
  });

  it("multiple domains produce distinct hub nodes", () => {
    const profiles = makeProfiles({
      alpha: makeDomainProfile({ label: "Alpha" }),
      beta: makeDomainProfile({ label: "Beta" }),
      gamma: makeDomainProfile({ label: "Gamma" }),
    });
    const result = buildGraph(profiles);

    const hubs = result.nodes.filter((n) => n.type === "domain");
    assert.equal(hubs.length, 3);
    const labels = hubs.map((h) => h.label).sort();
    assert.deepEqual(labels, ["Alpha", "Beta", "Gamma"]);
  });

  it("hub node size scales with sessionCount", () => {
    const profiles = makeProfiles({
      small: makeDomainProfile({ sessionCount: 1 }),
      large: makeDomainProfile({ sessionCount: 50 }),
    });
    const result = buildGraph(profiles);

    const smallHub = result.nodes.find((n) => n.type === "domain" && n.sessionCount === 1);
    const largeHub = result.nodes.find((n) => n.type === "domain" && n.sessionCount === 50);
    assert.ok(largeHub.size > smallHub.size, "larger session count should produce larger node");
  });

  it("hub node size is clamped between 8 and 30", () => {
    const profiles = makeProfiles({
      tiny: makeDomainProfile({ sessionCount: 0 }),
      huge: makeDomainProfile({ sessionCount: 1000 }),
    });
    const result = buildGraph(profiles);

    for (const node of result.nodes.filter((n) => n.type === "domain")) {
      assert.ok(node.size >= 8, `size ${node.size} should be >= 8`);
      assert.ok(node.size <= 30, `size ${node.size} should be <= 30`);
    }
  });
});
