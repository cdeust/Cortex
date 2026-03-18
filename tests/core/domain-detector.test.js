const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const { detectDomain, mapProjectToDomain } = require("../../mcp-server/core/domain-detector");

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeProfiles(domains = {}) {
  return { domains };
}

function makeDomain(overrides = {}) {
  return {
    projects: [],
    topKeywords: [],
    categoryDistribution: {},
    label: "test-domain",
    sessionCount: 5,
    confidence: 0.5,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// detectDomain
// ---------------------------------------------------------------------------

describe("detectDomain", () => {
  it("cold start — empty profiles returns coldStart=true, domain=null", () => {
    const result = detectDomain({ cwd: "/Users/dev/project" }, makeProfiles());
    assert.equal(result.coldStart, true);
    assert.equal(result.domain, null);
    assert.equal(result.confidence, 0);
    assert.equal(result.isNew, false);
    assert.deepEqual(result.alternativeDomains, []);
    assert.equal(typeof result.context, "string");
  });

  it("cold start — null profiles", () => {
    const result = detectDomain({ cwd: "/foo" }, null);
    assert.equal(result.coldStart, true);
    assert.equal(result.domain, null);
  });

  it("cold start — undefined profiles", () => {
    const result = detectDomain({}, undefined);
    assert.equal(result.coldStart, true);
  });

  it("confident match — project match scores >=0.6", () => {
    // project match gives 0.5 weight * 1.0 = 0.5, plus we need content or category
    // to push over 0.6. Use project + matching keywords.
    const profiles = makeProfiles({
      jarvis: makeDomain({
        projects: ["-Users-dev-jarvis"],
        topKeywords: ["scanner", "cognitive", "profiling"],
        categoryDistribution: { "architecture": 0.5, "feature": 0.5 },
      }),
    });

    const result = detectDomain(
      { cwd: "/Users/dev/jarvis", first_message: "fix the scanner cognitive profiling module" },
      profiles
    );
    assert.equal(result.coldStart, false);
    assert.equal(result.domain, "jarvis");
    assert.ok(result.confidence >= 0.6, `confidence ${result.confidence} should be >= 0.6`);
    assert.equal(result.isNew, false);
  });

  it("tentative match — score between 0.3 and 0.6", () => {
    // Only content match, no project match. Content similarity of ~0.3-0.6 range.
    const profiles = makeProfiles({
      backend: makeDomain({
        projects: ["-Users-other-backend"],
        topKeywords: ["authentication", "endpoint", "middleware"],
        categoryDistribution: {},
      }),
    });

    const result = detectDomain(
      { first_message: "fix the authentication endpoint middleware" },
      profiles
    );
    assert.equal(result.coldStart, false);
    // Content match only (w=0.3), so max possible = 0.3.
    // With keywords matching, score should be in tentative range.
    assert.equal(result.isNew, false);
    assert.ok(result.confidence >= 0.3, `confidence ${result.confidence} should be >= 0.3 for tentative`);
  });

  it("new domain — no match below tentative threshold", () => {
    const profiles = makeProfiles({
      jarvis: makeDomain({
        projects: ["-Users-dev-jarvis"],
        topKeywords: ["scanner", "cognitive"],
        categoryDistribution: {},
      }),
    });

    // Completely unrelated cwd and message
    const result = detectDomain(
      { cwd: "/totally/different/path" },
      profiles
    );
    assert.equal(result.coldStart, false);
    assert.equal(result.domain, null);
    assert.equal(result.isNew, true);
    assert.deepEqual(result.alternativeDomains, []);
  });

  it("project-only match — uses project context for scoring", () => {
    const profiles = makeProfiles({
      myapp: makeDomain({
        projects: ["-Users-dev-myapp"],
        topKeywords: [],
        categoryDistribution: {},
      }),
    });

    const result = detectDomain(
      { project: "-Users-dev-myapp" },
      profiles
    );
    assert.equal(result.coldStart, false);
    // Project match = 0.5 * 1.0 = 0.5 — just under confident threshold
    assert.ok(result.confidence >= 0.3, "project-only should be tentative or above");
  });

  it("alternatives are ordered by confidence descending", () => {
    const profiles = makeProfiles({
      alpha: makeDomain({
        projects: ["-Users-dev-alpha"],
        topKeywords: ["scanner", "profiling", "cognitive"],
        categoryDistribution: { "architecture": 0.8 },
      }),
      beta: makeDomain({
        projects: [],
        topKeywords: ["scanner", "profiling"],
        categoryDistribution: { "architecture": 0.6 },
      }),
      gamma: makeDomain({
        projects: [],
        topKeywords: ["scanner"],
        categoryDistribution: { "architecture": 0.3 },
      }),
    });

    const result = detectDomain(
      { cwd: "/Users/dev/alpha", first_message: "update the scanner profiling architecture" },
      profiles
    );
    assert.equal(result.domain, "alpha");
    // alternatives should be sorted descending
    for (let i = 1; i < result.alternativeDomains.length; i++) {
      assert.ok(
        result.alternativeDomains[i - 1].confidence >= result.alternativeDomains[i].confidence,
        "alternatives should be sorted descending"
      );
    }
  });

  it("uses cwd to derive projectId when project is not provided", () => {
    const profiles = makeProfiles({
      myproj: makeDomain({
        projects: ["-Users-dev-myproj"],
        topKeywords: [],
      }),
    });

    const result = detectDomain({ cwd: "/Users/dev/myproj" }, profiles);
    assert.equal(result.domain, "myproj");
  });

  it("handles empty context gracefully", () => {
    const profiles = makeProfiles({
      d: makeDomain({ projects: [], topKeywords: [] }),
    });
    const result = detectDomain({}, profiles);
    assert.equal(result.coldStart, false);
    assert.ok(result.confidence <= 0.3);
  });
});

// ---------------------------------------------------------------------------
// mapProjectToDomain
// ---------------------------------------------------------------------------

describe("mapProjectToDomain", () => {
  it("finds domain that owns the project", () => {
    const profiles = makeProfiles({
      jarvis: makeDomain({ projects: ["-Users-dev-jarvis", "-Users-dev-jarvis2"] }),
      other: makeDomain({ projects: ["-Users-dev-other"] }),
    });
    assert.equal(mapProjectToDomain("-Users-dev-jarvis", profiles), "jarvis");
    assert.equal(mapProjectToDomain("-Users-dev-other", profiles), "other");
  });

  it("returns null when project not found", () => {
    const profiles = makeProfiles({
      jarvis: makeDomain({ projects: ["-Users-dev-jarvis"] }),
    });
    assert.equal(mapProjectToDomain("-Users-dev-unknown", profiles), null);
  });

  it("returns null for null projectId", () => {
    assert.equal(mapProjectToDomain(null, makeProfiles()), null);
  });

  it("returns null for null profiles", () => {
    assert.equal(mapProjectToDomain("-foo", null), null);
  });

  it("returns null when profiles has no domains key", () => {
    assert.equal(mapProjectToDomain("-foo", {}), null);
  });
});
