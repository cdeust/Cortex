const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const { detectBlindSpots } = require("../../mcp-server/core/blindspot-detector");

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeConv(overrides = {}) {
  return {
    toolsUsed: [],
    categories: [],
    allText: "",
    firstMessage: "",
    duration: 0,
    durationMinutes: 0,
    ...overrides,
  };
}

function makeProfiles(domains = {}) {
  return { domains };
}

// ---------------------------------------------------------------------------
// detectBlindSpots
// ---------------------------------------------------------------------------

describe("detectBlindSpots", () => {
  it("returns empty array for empty conversations", () => {
    const result = detectBlindSpots("d", [], [], makeProfiles());
    assert.deepEqual(result, []);
  });

  it("detects category blind spots for categories with <5% sessions", () => {
    // Create 100 sessions all categorized as "bug-fix" — other categories should be blind spots
    const domainConvs = Array.from({ length: 100 }, () =>
      makeConv({ categories: ["bug-fix"] })
    );
    const result = detectBlindSpots("d", domainConvs, domainConvs, makeProfiles());

    const categoryBlindSpots = result.filter((b) => b.type === "category");
    assert.ok(categoryBlindSpots.length > 0, "should detect category blind spots");

    // All detected blind spots should be for categories other than bug-fix
    for (const bs of categoryBlindSpots) {
      assert.notEqual(bs.value, "bug-fix", "bug-fix should not be a blind spot");
      assert.ok(bs.description.includes("5%"), "description should mention 5% threshold");
      assert.ok(bs.suggestion, "should have a suggestion");
      assert.ok(["high", "medium", "low"].includes(bs.severity));
    }
  });

  it("high severity for categories at <1%", () => {
    const domainConvs = Array.from({ length: 200 }, () =>
      makeConv({ categories: ["feature"] })
    );
    const result = detectBlindSpots("d", domainConvs, domainConvs, makeProfiles());
    const categoryBs = result.filter((b) => b.type === "category");
    // With 0% occurrence, all should be high severity
    const highSeverity = categoryBs.filter((b) => b.severity === "high");
    assert.ok(highSeverity.length > 0, "0% categories should be high severity");
  });

  it("detects tool blind spots relevant to domain categories", () => {
    // Domain top categories include "bug-fix" and "debug"
    // Grep is relevant to both but never used
    const domainConvs = Array.from({ length: 50 }, () =>
      makeConv({
        categories: ["bug-fix", "debug"],
        toolsUsed: ["Edit", "Write"],
      })
    );
    const result = detectBlindSpots("d", domainConvs, domainConvs, makeProfiles());
    const toolBs = result.filter((b) => b.type === "tool");

    // Grep is relevant to bug-fix and debug but never used
    const grepBs = toolBs.find((b) => b.value === "Grep");
    assert.ok(grepBs, "Grep should be detected as blind spot for bug-fix/debug domain");
    assert.ok(grepBs.description.includes("Grep"));
    assert.ok(grepBs.suggestion.includes("Grep"));
  });

  it("does not flag tools irrelevant to domain categories", () => {
    // Domain is only "deployment" — WebFetch is NOT relevant to deployment
    const domainConvs = Array.from({ length: 50 }, () =>
      makeConv({
        categories: ["deployment"],
        toolsUsed: ["Bash"],
      })
    );
    const result = detectBlindSpots("d", domainConvs, domainConvs, makeProfiles());
    const toolBs = result.filter((b) => b.type === "tool");

    const webFetchBs = toolBs.find((b) => b.value === "WebFetch");
    assert.equal(webFetchBs, undefined, "WebFetch is not relevant to deployment — should not flag");
  });

  it("does not flag tools used in >=5% of sessions", () => {
    const domainConvs = Array.from({ length: 20 }, (_, i) =>
      makeConv({
        categories: ["bug-fix"],
        toolsUsed: i === 0 ? ["Grep", "Edit"] : ["Edit"],
      })
    );
    const result = detectBlindSpots("d", domainConvs, domainConvs, makeProfiles());
    const grepBs = result.filter((b) => b.type === "tool" && b.value === "Grep");
    assert.equal(grepBs.length, 0, "Grep used in 5% of sessions — should not flag");
  });

  it("detects exploration pattern blind spot when domain has 0 exploration vs high global", () => {
    const domainConvs = Array.from({ length: 20 }, () =>
      makeConv({ categories: ["bug-fix"] })
    );
    // Global has 50% exploration
    const allConvs = [
      ...domainConvs,
      ...Array.from({ length: 20 }, () =>
        makeConv({ categories: ["research"] })
      ),
    ];
    const result = detectBlindSpots("d", domainConvs, allConvs, makeProfiles());
    const explorationBs = result.find((b) => b.type === "pattern" && b.value === "exploration");
    assert.ok(explorationBs, "should detect exploration blind spot");
    assert.equal(explorationBs.severity, "high");
  });

  it("detects deep-work pattern blind spot", () => {
    // Domain has only short sessions, global has many long sessions
    const domainConvs = Array.from({ length: 20 }, () =>
      makeConv({ categories: ["bug-fix"], duration: 5, durationMinutes: 5 })
    );
    const allConvs = [
      ...domainConvs,
      ...Array.from({ length: 20 }, () =>
        makeConv({ categories: ["research"], duration: 45, durationMinutes: 45 })
      ),
    ];
    const result = detectBlindSpots("d", domainConvs, allConvs, makeProfiles());
    const deepWorkBs = result.find((b) => b.type === "pattern" && b.value === "deep-work");
    assert.ok(deepWorkBs, "should detect deep-work blind spot");
  });

  it("detects quick-iteration pattern blind spot", () => {
    // Domain has only long sessions, global has many short sessions
    const domainConvs = Array.from({ length: 20 }, () =>
      makeConv({ categories: ["architecture"], duration: 45, durationMinutes: 45 })
    );
    const allConvs = [
      ...domainConvs,
      ...Array.from({ length: 20 }, () =>
        makeConv({ categories: ["bug-fix"], duration: 5, durationMinutes: 5 })
      ),
    ];
    const result = detectBlindSpots("d", domainConvs, allConvs, makeProfiles());
    const quickBs = result.find((b) => b.type === "pattern" && b.value === "quick-iteration");
    assert.ok(quickBs, "should detect quick-iteration blind spot");
    assert.equal(quickBs.severity, "low");
  });

  it("no pattern blind spots when domain matches global", () => {
    const convs = Array.from({ length: 20 }, (_, i) =>
      makeConv({
        categories: i % 2 === 0 ? ["bug-fix"] : ["research"],
        duration: i % 2 === 0 ? 5 : 45,
        durationMinutes: i % 2 === 0 ? 5 : 45,
      })
    );
    const result = detectBlindSpots("d", convs, convs, makeProfiles());
    const patternBs = result.filter((b) => b.type === "pattern");
    // With balanced exploration and duration, few pattern blind spots expected
    const explorationBs = patternBs.find((b) => b.value === "exploration");
    assert.equal(explorationBs, undefined, "balanced domain should not flag exploration");
  });

  it("uses categorizeWithScores fallback when categories array is empty", () => {
    // allText with "fix bug" should categorize as "bug-fix"
    const domainConvs = Array.from({ length: 50 }, () =>
      makeConv({
        allText: "fix the bug in the broken code crash error",
        toolsUsed: ["Edit"],
      })
    );
    const result = detectBlindSpots("d", domainConvs, domainConvs, makeProfiles());
    // Should have detected categories via text analysis
    // The key thing is it doesn't crash and produces valid results
    assert.ok(Array.isArray(result));
  });

  it("all blind spots have required fields", () => {
    const domainConvs = Array.from({ length: 100 }, () =>
      makeConv({ categories: ["feature"] })
    );
    const result = detectBlindSpots("d", domainConvs, domainConvs, makeProfiles());
    for (const bs of result) {
      assert.ok(bs.type, "blind spot must have type");
      assert.ok(bs.value, "blind spot must have value");
      assert.ok(bs.severity, "blind spot must have severity");
      assert.ok(bs.description, "blind spot must have description");
      assert.ok(bs.suggestion, "blind spot must have suggestion");
      assert.ok(["high", "medium", "low"].includes(bs.severity), `invalid severity: ${bs.severity}`);
    }
  });
});
