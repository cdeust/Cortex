const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const { findBridges } = require("../../mcp-server/core/bridge-finder");

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeProfiles(domains = {}) {
  return { domains };
}

function makeDomain(overrides = {}) {
  return {
    projects: [],
    label: "test",
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// findBridges
// ---------------------------------------------------------------------------

describe("findBridges", () => {
  it("returns empty object for empty profiles", () => {
    const result = findBridges(makeProfiles(), {}, {});
    assert.deepEqual(result, {});
  });

  it("returns empty object when no cross-refs exist", () => {
    const profiles = makeProfiles({
      alpha: makeDomain({ projects: ["proj-a"] }),
      beta: makeDomain({ projects: ["proj-b"] }),
    });
    const brainIndex = {
      memories: {
        m1: { projectId: "proj-a", body: "no references here", crossRefs: [] },
        m2: { projectId: "proj-b", body: "no references here either", crossRefs: [] },
      },
      conversations: {},
    };
    const result = findBridges(profiles, brainIndex);
    assert.deepEqual(result, {});
  });

  it("detects structural bridges from cross-refs between domains", () => {
    const profiles = makeProfiles({
      alpha: makeDomain({ projects: ["proj-a"] }),
      beta: makeDomain({ projects: ["proj-b"] }),
    });
    const brainIndex = {
      memories: {
        m1: { projectId: "proj-a", body: "alpha content", crossRefs: ["m2"] },
        m2: { projectId: "proj-b", body: "beta content", crossRefs: [] },
      },
      conversations: {},
    };
    const result = findBridges(profiles, brainIndex);

    // Should have edges for both alpha and beta
    assert.ok(result.alpha, "alpha should have bridges");
    assert.ok(result.beta, "beta should have bridges");

    const alphaBridge = result.alpha.find((b) => b.pattern === "structural-edge");
    assert.ok(alphaBridge, "alpha should have structural bridge");
    assert.equal(alphaBridge.toDomain, "beta");
    assert.ok(alphaBridge.weight > 0);
    assert.ok(alphaBridge.edgeCount >= 1);
  });

  it("creates bidirectional edges for structural bridges", () => {
    const profiles = makeProfiles({
      alpha: makeDomain({ projects: ["proj-a"] }),
      beta: makeDomain({ projects: ["proj-b"] }),
    });
    const brainIndex = {
      memories: {
        m1: { projectId: "proj-a", body: "", crossRefs: ["m2"] },
        m2: { projectId: "proj-b", body: "", crossRefs: [] },
      },
      conversations: {},
    };
    const result = findBridges(profiles, brainIndex);

    // Both directions should exist
    const alphaHasBeta = result.alpha?.some((b) => b.toDomain === "beta");
    const betaHasAlpha = result.beta?.some((b) => b.toDomain === "alpha");
    assert.ok(alphaHasBeta, "alpha should bridge to beta");
    assert.ok(betaHasAlpha, "beta should bridge to alpha");
  });

  it("ignores same-domain cross-refs", () => {
    const profiles = makeProfiles({
      alpha: makeDomain({ projects: ["proj-a"] }),
    });
    const brainIndex = {
      memories: {
        m1: { projectId: "proj-a", body: "", crossRefs: ["m2"] },
        m2: { projectId: "proj-a", body: "", crossRefs: [] },
      },
      conversations: {},
    };
    const result = findBridges(profiles, brainIndex);
    // Same domain refs should not create bridges
    assert.deepEqual(result, {});
  });

  it("detects analogical bridges from text with 'similar to'", () => {
    const profiles = makeProfiles({
      alpha: makeDomain({ projects: ["proj-a"] }),
    });
    const brainIndex = {
      memories: {
        m1: {
          projectId: "proj-a",
          body: "This approach is similar to the pattern used in microservices",
          crossRefs: [],
        },
      },
      conversations: {},
    };
    const result = findBridges(profiles, brainIndex);

    assert.ok(result.alpha, "alpha should have bridges");
    const analogyBridge = result.alpha.find((b) => b.toDomain === "text-analogy");
    assert.ok(analogyBridge, "should detect text analogy bridge");
    assert.equal(analogyBridge.pattern, "similar to");
    assert.ok(analogyBridge.examples.length > 0);
    assert.ok(analogyBridge.examples[0].targetConcept.includes("pattern used in microservices"));
  });

  it("detects analogical bridges with 'like' pattern", () => {
    const profiles = makeProfiles({
      beta: makeDomain({ projects: ["proj-b"] }),
    });
    const brainIndex = {
      memories: {
        m1: {
          projectId: "proj-b",
          body: "This works like a message queue for events",
          crossRefs: [],
        },
      },
      conversations: {},
    };
    const result = findBridges(profiles, brainIndex);
    assert.ok(result.beta);
    const bridge = result.beta.find((b) => b.pattern === "like");
    assert.ok(bridge, "should detect 'like' analogy");
  });

  it("detects analogical bridges with 'reminds me of' pattern", () => {
    const profiles = makeProfiles({
      gamma: makeDomain({ projects: ["proj-g"] }),
    });
    const brainIndex = {
      memories: {
        m1: {
          projectId: "proj-g",
          body: "This reminds me of the observer pattern implementation",
          crossRefs: [],
        },
      },
      conversations: {},
    };
    const result = findBridges(profiles, brainIndex);
    assert.ok(result.gamma);
    const bridge = result.gamma.find((b) => b.pattern === "reminds me of");
    assert.ok(bridge, "should detect 'reminds me of' analogy");
  });

  it("handles cross-refs as objects with id and weight", () => {
    const profiles = makeProfiles({
      alpha: makeDomain({ projects: ["proj-a"] }),
      beta: makeDomain({ projects: ["proj-b"] }),
    });
    const brainIndex = {
      memories: {
        m1: { projectId: "proj-a", body: "", crossRefs: [{ id: "m2", weight: 3 }] },
        m2: { projectId: "proj-b", body: "", crossRefs: [] },
      },
      conversations: {},
    };
    const result = findBridges(profiles, brainIndex);
    const alphaBridge = result.alpha.find((b) => b.pattern === "structural-edge");
    assert.equal(alphaBridge.weight, 3, "should use weight from crossRef object");
  });

  it("merges memories from brainIndex and separate memories param", () => {
    const profiles = makeProfiles({
      alpha: makeDomain({ projects: ["proj-a"] }),
      beta: makeDomain({ projects: ["proj-b"] }),
    });
    const brainIndex = {
      memories: {
        m1: { projectId: "proj-a", body: "", crossRefs: ["m2"] },
      },
      conversations: {},
    };
    const extraMemories = {
      m2: { projectId: "proj-b", body: "", crossRefs: [] },
    };
    const result = findBridges(profiles, brainIndex, extraMemories);
    assert.ok(result.alpha, "bridge should exist via merged memories");
  });

  it("handles null brainIndex gracefully", () => {
    const profiles = makeProfiles({
      alpha: makeDomain({ projects: ["proj-a"] }),
    });
    const result = findBridges(profiles, null, null);
    assert.deepEqual(result, {});
  });

  it("resolves domain from node.domainId fallback", () => {
    const profiles = makeProfiles({
      alpha: makeDomain({ projects: [] }),
      beta: makeDomain({ projects: [] }),
    });
    const brainIndex = {
      memories: {
        m1: { domainId: "alpha", body: "", crossRefs: ["m2"] },
        m2: { domainId: "beta", body: "", crossRefs: [] },
      },
      conversations: {},
    };
    const result = findBridges(profiles, brainIndex);
    assert.ok(result.alpha);
    assert.ok(result.beta);
  });

  it("collects examples up to 5 per structural pair", () => {
    const profiles = makeProfiles({
      alpha: makeDomain({ projects: ["proj-a"] }),
      beta: makeDomain({ projects: ["proj-b"] }),
    });
    const memories = {};
    for (let i = 0; i < 10; i++) {
      memories[`a${i}`] = { projectId: "proj-a", body: "", crossRefs: [`b${i}`] };
      memories[`b${i}`] = { projectId: "proj-b", body: "", crossRefs: [] };
    }
    const result = findBridges(profiles, { memories, conversations: {} });
    const alphaBridge = result.alpha.find((b) => b.pattern === "structural-edge");
    assert.ok(alphaBridge.examples.length <= 5, "examples capped at 5");
    assert.equal(alphaBridge.edgeCount, 10);
  });
});
