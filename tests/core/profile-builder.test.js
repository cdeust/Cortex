const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const { buildDomainProfiles, applySessionUpdate } = require("../../mcp-server/core/profile-builder");

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeConversation(overrides = {}) {
  return {
    firstMessage: "Fix the authentication bug",
    allText: "Fix the authentication bug in the login endpoint",
    toolsUsed: ["Read", "Edit", "Bash"],
    turnCount: 8,
    duration: 300000,
    durationMinutes: 5,
    messageCount: 16,
    keywords: new Set(["authentication", "endpoint"]),
    startedAt: "2025-01-15T10:00:00Z",
    endedAt: "2025-01-15T10:05:00Z",
    ...overrides,
  };
}

function makeEmptyProfiles() {
  return { domains: {} };
}

function makeByProject(projectId, conversations) {
  return { [projectId]: conversations };
}

// ---------------------------------------------------------------------------
// buildDomainProfiles
// ---------------------------------------------------------------------------

describe("buildDomainProfiles", () => {
  it("creates a domain from conversations grouped by project", () => {
    const convs = [
      makeConversation(),
      makeConversation({ firstMessage: "Refactor the scanner module", allText: "Refactor the scanner module for clarity" }),
      makeConversation({ firstMessage: "Add new feature endpoint", allText: "Add new feature endpoint for the API" }),
    ];

    const result = buildDomainProfiles({
      existingProfiles: makeEmptyProfiles(),
      conversations: convs,
      memories: {},
      brainIndex: { memories: {}, conversations: {} },
      byProject: makeByProject("-Users-dev-jarvis", convs),
    });

    assert.ok(result.domains, "should have domains");
    const domainIds = Object.keys(result.domains);
    assert.ok(domainIds.length > 0, "should create at least one domain");

    const domain = result.domains[domainIds[0]];
    assert.equal(domain.sessionCount, 3);
    assert.ok(domain.label, "should have a label");
    assert.ok(Array.isArray(domain.projects));
    assert.ok(domain.projects.includes("-Users-dev-jarvis"));
    assert.ok(Array.isArray(domain.entryPoints));
    assert.ok(domain.toolPreferences, "should have tool preferences");
    assert.ok(domain.sessionShape, "should have session shape");
    assert.ok(domain.metacognitive, "should have metacognitive style");
    assert.ok(Array.isArray(domain.blindSpots));
    assert.ok(Array.isArray(domain.connectionBridges));
    assert.ok(domain.topKeywords, "should have top keywords");
    assert.ok(domain.categories, "should have categories");
  });

  it("computes confidence based on session count", () => {
    const fewConvs = [makeConversation()];
    const result1 = buildDomainProfiles({
      existingProfiles: makeEmptyProfiles(),
      conversations: fewConvs,
      memories: {},
      brainIndex: { memories: {}, conversations: {} },
      byProject: makeByProject("-Users-dev-proj", fewConvs),
    });

    const manyConvs = Array.from({ length: 50 }, () => makeConversation());
    const result2 = buildDomainProfiles({
      existingProfiles: makeEmptyProfiles(),
      conversations: manyConvs,
      memories: {},
      brainIndex: { memories: {}, conversations: {} },
      byProject: makeByProject("-Users-dev-proj2", manyConvs),
    });

    const domain1 = Object.values(result1.domains)[0];
    const domain2 = Object.values(result2.domains)[0];

    assert.ok(domain2.confidence > domain1.confidence,
      `50-session confidence (${domain2.confidence}) should exceed 1-session (${domain1.confidence})`);
  });

  it("sets global style weighted by session count", () => {
    const convs = Array.from({ length: 10 }, () => makeConversation());
    const result = buildDomainProfiles({
      existingProfiles: makeEmptyProfiles(),
      conversations: convs,
      memories: {},
      brainIndex: { memories: {}, conversations: {} },
      byProject: makeByProject("-Users-dev-proj", convs),
    });

    assert.ok(result.globalStyle, "should have globalStyle");
    assert.ok("activeReflective" in result.globalStyle);
    assert.ok("sensingIntuitive" in result.globalStyle);
    assert.ok("sequentialGlobal" in result.globalStyle);
    assert.ok("confidence" in result.globalStyle);
    assert.equal(result.globalStyle.sessionCount, 10);
  });

  it("preserves existing domains when building new ones", () => {
    const existing = {
      domains: {
        "existing-domain": {
          id: "existing-domain",
          label: "Existing",
          projects: ["-Users-dev-existing"],
          sessionCount: 5,
        },
      },
    };
    const newConvs = [makeConversation()];
    const result = buildDomainProfiles({
      existingProfiles: existing,
      conversations: newConvs,
      memories: {},
      brainIndex: { memories: {}, conversations: {} },
      byProject: makeByProject("-Users-dev-newproj", newConvs),
    });

    assert.ok(result.domains["existing-domain"], "existing domain should still be present");
    assert.ok(Object.keys(result.domains).length >= 2, "should have both domains");
  });

  it("respects targetDomain filter", () => {
    const convsA = [makeConversation()];
    const convsB = [makeConversation()];
    const existing = makeEmptyProfiles();

    // Pre-seed domains so targetDomain works
    existing.domains["jarvis"] = { projects: ["-Users-dev-jarvis"], sessionCount: 0 };
    existing.domains["other"] = { projects: ["-Users-dev-other"], sessionCount: 0 };

    const result = buildDomainProfiles({
      existingProfiles: existing,
      conversations: [...convsA, ...convsB],
      memories: {},
      brainIndex: { memories: {}, conversations: {} },
      byProject: {
        "-Users-dev-jarvis": convsA,
        "-Users-dev-other": convsB,
      },
      targetDomain: "jarvis",
    });

    // "jarvis" should be rebuilt (sessionCount=1), "other" should remain at 0
    assert.equal(result.domains.jarvis.sessionCount, 1);
    assert.equal(result.domains.other.sessionCount, 0);
  });

  it("handles empty byProject gracefully", () => {
    const result = buildDomainProfiles({
      existingProfiles: makeEmptyProfiles(),
      conversations: [],
      memories: {},
      brainIndex: { memories: {}, conversations: {} },
      byProject: {},
    });
    assert.deepEqual(result.domains, {});
  });

  it("records timestamps from conversations", () => {
    const convs = [
      makeConversation({ startedAt: "2025-01-10T00:00:00Z" }),
      makeConversation({ startedAt: "2025-01-20T00:00:00Z" }),
    ];
    const result = buildDomainProfiles({
      existingProfiles: makeEmptyProfiles(),
      conversations: convs,
      memories: {},
      brainIndex: { memories: {}, conversations: {} },
      byProject: makeByProject("-Users-dev-proj", convs),
    });

    const domain = Object.values(result.domains)[0];
    assert.equal(domain.firstSeen, "2025-01-10T00:00:00Z");
    assert.equal(domain.lastUpdated, "2025-01-20T00:00:00Z");
  });

  it("builds category distribution from allText", () => {
    const convs = Array.from({ length: 5 }, () =>
      makeConversation({ allText: "fix the bug in the broken code crash error regression" })
    );
    const result = buildDomainProfiles({
      existingProfiles: makeEmptyProfiles(),
      conversations: convs,
      memories: {},
      brainIndex: { memories: {}, conversations: {} },
      byProject: makeByProject("-Users-dev-proj", convs),
    });

    const domain = Object.values(result.domains)[0];
    assert.ok(domain.categories, "should have categories");
    assert.ok(Object.keys(domain.categories).length > 0, "should have non-empty categories");
  });
});

// ---------------------------------------------------------------------------
// applySessionUpdate
// ---------------------------------------------------------------------------

describe("applySessionUpdate", () => {
  function makeDomainProfile() {
    return {
      sessionCount: 10,
      confidence: 0.2,
      sessionShape: {
        avgDuration: 500000,
        avgTurns: 12,
        avgMessages: 24,
        burstRatio: 0.5,
        explorationRatio: 0.3,
        dominantMode: "mixed",
      },
      toolPreferences: {
        Read: { ratio: 0.8, avgPerSession: 5 },
        Edit: { ratio: 0.6, avgPerSession: 3 },
      },
      metacognitive: {
        activeReflective: 0.3,
        sensingIntuitive: -0.2,
        sequentialGlobal: 0.1,
        problemDecomposition: "top-down",
        explorationStyle: "depth-first",
        verificationBehavior: "test-after",
      },
    };
  }

  it("increments session count", () => {
    const dp = makeDomainProfile();
    const result = applySessionUpdate({
      domainProfile: dp,
      sessionData: { duration: 300000, tools_used: ["Read"], turn_count: 5 },
    });
    assert.equal(result.sessionCount, 11);
  });

  it("updates running average for session shape", () => {
    const dp = makeDomainProfile();
    const oldAvgDuration = dp.sessionShape.avgDuration;
    const newDuration = 200000;

    applySessionUpdate({
      domainProfile: dp,
      sessionData: { duration: newDuration, tools_used: [], turn_count: 5 },
    });

    // Running average: old + (new - old) / newCount
    const expected = oldAvgDuration + (newDuration - oldAvgDuration) / 11;
    assert.ok(Math.abs(dp.sessionShape.avgDuration - expected) < 1);
  });

  it("updates burst ratio for burst session", () => {
    const dp = makeDomainProfile();
    const oldBurstRatio = dp.sessionShape.burstRatio;

    applySessionUpdate({
      domainProfile: dp,
      sessionData: { duration: 300000, tools_used: [], turn_count: 5 },
    });

    // isBurst = true (300000 < 600000), so burstRatio increases
    const expected = oldBurstRatio + (1 - oldBurstRatio) / 11;
    assert.ok(Math.abs(dp.sessionShape.burstRatio - expected) < 0.001);
  });

  it("updates tool preferences for existing tools", () => {
    const dp = makeDomainProfile();
    applySessionUpdate({
      domainProfile: dp,
      sessionData: { duration: 300000, tools_used: ["Read", "Read", "Read"], turn_count: 5 },
    });

    // Read was in 0.8 * 10 = 8 sessions, now 9/11
    assert.ok(Math.abs(dp.toolPreferences.Read.ratio - 9 / 11) < 0.01);
  });

  it("adds new tool to preferences", () => {
    const dp = makeDomainProfile();
    applySessionUpdate({
      domainProfile: dp,
      sessionData: { duration: 300000, tools_used: ["Grep", "Grep"], turn_count: 5 },
    });

    assert.ok(dp.toolPreferences.Grep, "Grep should be added");
    assert.ok(Math.abs(dp.toolPreferences.Grep.ratio - 1 / 11) < 0.01);
    assert.equal(dp.toolPreferences.Grep.avgPerSession, 2);
  });

  it("decreases ratio for tools not used in this session", () => {
    const dp = makeDomainProfile();
    const oldEditRatio = dp.toolPreferences.Edit.ratio;
    applySessionUpdate({
      domainProfile: dp,
      sessionData: { duration: 300000, tools_used: ["Read"], turn_count: 5 },
    });

    // Edit not used: old sessions using = round(0.6 * 10) = 6, new ratio = 6/11
    assert.ok(dp.toolPreferences.Edit.ratio < oldEditRatio, "Edit ratio should decrease");
  });

  it("updates confidence based on new session count", () => {
    const dp = makeDomainProfile();
    applySessionUpdate({
      domainProfile: dp,
      sessionData: { duration: 300000, tools_used: [], turn_count: 5 },
    });

    // newCount=11, dataQuality = min(11/10, 1) = 1, conf = min(11/50, 1) * 1 = 0.22
    assert.equal(dp.confidence, 0.22);
  });

  it("sets lastUpdated to ISO string", () => {
    const dp = makeDomainProfile();
    applySessionUpdate({
      domainProfile: dp,
      sessionData: { duration: 300000, tools_used: [], turn_count: 5 },
    });

    assert.ok(dp.lastUpdated, "should set lastUpdated");
    assert.ok(dp.lastUpdated.match(/^\d{4}-\d{2}-\d{2}T/), "should be ISO format");
  });

  it("applies style EMA update from session signals", () => {
    const dp = makeDomainProfile();
    const oldAR = dp.metacognitive.activeReflective;
    applySessionUpdate({
      domainProfile: dp,
      sessionData: { duration: 300000, tools_used: ["Edit", "Edit", "Edit", "Write", "Read"], turn_count: 5 },
    });

    // Short duration (< 600000) → active signal, edit ratio > 0.4 → active signal
    // EMA with alpha=0.1 should nudge activeReflective slightly
    assert.notEqual(dp.metacognitive.activeReflective, oldAR, "style should update");
  });

  it("recalculates dominant mode after update", () => {
    const dp = makeDomainProfile();
    dp.sessionShape.burstRatio = 0.59; // just below burst threshold
    dp.sessionShape.explorationRatio = 0.1;
    dp.sessionCount = 1;

    applySessionUpdate({
      domainProfile: dp,
      sessionData: { duration: 100000, tools_used: [], turn_count: 3 },
    });

    // After adding a burst session, burstRatio should increase past 0.6
    // With count going from 1 to 2: burstRatio = 0.59 + (1 - 0.59)/2 = 0.795
    assert.equal(dp.sessionShape.dominantMode, "burst");
  });
});
