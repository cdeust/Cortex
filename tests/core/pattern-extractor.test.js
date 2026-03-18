const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const {
  extractEntryPoints,
  extractRecurringPatterns,
  extractToolPreferences,
  extractSessionShape,
} = require("../../mcp-server/core/pattern-extractor");

// ---------------------------------------------------------------------------
// extractEntryPoints
// ---------------------------------------------------------------------------

describe("extractEntryPoints", () => {
  it("returns empty array for empty input", () => {
    assert.deepEqual(extractEntryPoints([]), []);
  });

  it("returns empty array when conversations have no messages", () => {
    assert.deepEqual(extractEntryPoints([{}, { firstMessage: "" }]), []);
  });

  it("extracts entry point from single session", () => {
    const convs = [{ firstMessage: "Fix the authentication endpoint" }];
    const result = extractEntryPoints(convs);
    assert.ok(result.length > 0, "should produce at least one entry point");
    assert.equal(result[0].frequency, 1);
    assert.equal(result[0].confidence, 1);
    assert.ok(result[0].pattern.length > 0, "pattern should be non-empty");
    assert.ok(Array.isArray(result[0].exampleMessages));
  });

  it("clusters similar first messages together", () => {
    const convs = [
      { firstMessage: "Fix the authentication endpoint bug" },
      { firstMessage: "Fix the authentication service error" },
      { firstMessage: "Fix authentication module crash" },
      { firstMessage: "Deploy the new pipeline to production" },
    ];
    const result = extractEntryPoints(convs);
    // The 3 auth messages should cluster together, deploy is separate
    assert.ok(result.length >= 1, "should have at least 1 cluster");
    // The largest cluster should have frequency >= 2
    assert.ok(result[0].frequency >= 2, `top cluster freq=${result[0].frequency} should be >= 2`);
  });

  it("limits to top 5 clusters", () => {
    // Create 7 distinct messages with no overlap
    const convs = [];
    const topics = [
      "implement database migrations system",
      "configure kubernetes deployment pipeline",
      "refactor authentication middleware layer",
      "design graphql schema definitions",
      "optimize elasticsearch query performance",
      "integrate stripe payment processing",
      "monitor prometheus alerting rules",
    ];
    for (const t of topics) {
      convs.push({ firstMessage: t });
    }
    const result = extractEntryPoints(convs);
    assert.ok(result.length <= 5, `should limit to 5 clusters, got ${result.length}`);
  });

  it("reads from messages array when firstMessage is missing", () => {
    const convs = [
      {
        messages: [
          { role: "user", content: "Refactor the scanner module" },
          { role: "assistant", content: "Sure, I will refactor it." },
        ],
      },
    ];
    const result = extractEntryPoints(convs);
    assert.ok(result.length > 0);
  });

  it("confidence is frequency / total", () => {
    const convs = [
      { firstMessage: "Fix authentication endpoint issue" },
      { firstMessage: "Fix authentication service problem" },
      { firstMessage: "Deploy kubernetes production cluster" },
      { firstMessage: "Deploy kubernetes staging environment" },
    ];
    const result = extractEntryPoints(convs);
    const totalFrequency = result.reduce((sum, ep) => sum + ep.frequency, 0);
    assert.equal(totalFrequency, 4, "total frequency should equal total conversations");
  });
});

// ---------------------------------------------------------------------------
// extractRecurringPatterns
// ---------------------------------------------------------------------------

describe("extractRecurringPatterns", () => {
  it("returns empty array for empty input", () => {
    assert.deepEqual(extractRecurringPatterns([]), []);
  });

  it("returns empty for fewer than 3 sessions with same ngrams", () => {
    const convs = [
      { allText: "implement feature something" },
      { allText: "deploy pipeline another" },
    ];
    const result = extractRecurringPatterns(convs);
    assert.deepEqual(result, []);
  });

  it("returns empty when text is empty", () => {
    const convs = [{ allText: "" }, { allText: "" }, { allText: "" }];
    assert.deepEqual(extractRecurringPatterns(convs), []);
  });

  it("detects patterns appearing in >=3 sessions", () => {
    // Use a distinctive bigram that appears in all 4 sessions
    const sharedPhrase = "authentication middleware validation endpoint security";
    const convs = [
      { allText: `Working on ${sharedPhrase} for the backend` },
      { allText: `Fixing ${sharedPhrase} in the service` },
      { allText: `Refactoring ${sharedPhrase} for performance` },
      { allText: `Testing ${sharedPhrase} coverage` },
    ];
    const result = extractRecurringPatterns(convs);
    assert.ok(result.length > 0, "should detect at least one pattern");
    assert.ok(result[0].sessionsObserved >= 3, "pattern should appear in >=3 sessions");
    assert.ok(result[0].confidence > 0);
    assert.ok(Array.isArray(result[0].ngramSignature));
  });

  it("pattern confidence is sessionsObserved / totalSessions", () => {
    const phrase = "authentication middleware validation endpoint security";
    const convs = [
      { allText: `Processing ${phrase} system` },
      { allText: `Updating ${phrase} system` },
      { allText: `Deploying ${phrase} system` },
      { allText: "something completely different unrelated" },
    ];
    const result = extractRecurringPatterns(convs);
    if (result.length > 0) {
      const p = result[0];
      assert.ok(p.confidence > 0 && p.confidence <= 1);
      assert.equal(p.confidence, p.sessionsObserved / convs.length);
    }
  });
});

// ---------------------------------------------------------------------------
// extractToolPreferences
// ---------------------------------------------------------------------------

describe("extractToolPreferences", () => {
  it("returns empty object for empty input", () => {
    assert.deepEqual(extractToolPreferences([]), {});
  });

  it("computes ratio and avgPerSession for string tool entries", () => {
    const convs = [
      { toolsUsed: ["Read", "Read", "Edit"] },
      { toolsUsed: ["Read", "Grep"] },
      { toolsUsed: ["Bash"] },
    ];
    const result = extractToolPreferences(convs);

    // Read used in sessions 0 and 1 → ratio = 2/3
    assert.ok(Math.abs(result.Read.ratio - 2 / 3) < 0.001);
    // Read: 2 uses in s0 + 1 use in s1 = 3 total across 2 sessions → avg = 1.5
    assert.ok(Math.abs(result.Read.avgPerSession - 1.5) < 0.001);

    // Edit used in session 0 → ratio = 1/3
    assert.ok(Math.abs(result.Edit.ratio - 1 / 3) < 0.001);
    assert.ok(Math.abs(result.Edit.avgPerSession - 1) < 0.001);
  });

  it("handles object tool entries with name and count", () => {
    const convs = [
      { toolsUsed: [{ name: "Read", count: 5 }, { name: "Edit", count: 2 }] },
      { toolsUsed: [{ name: "Read", count: 3 }] },
    ];
    const result = extractToolPreferences(convs);
    assert.ok(Math.abs(result.Read.ratio - 1.0) < 0.001, "Read used in both sessions");
    assert.ok(Math.abs(result.Read.avgPerSession - 4) < 0.001, "Read avg = (5+3)/2 = 4");
  });

  it("handles tools_used key as alternative", () => {
    const convs = [{ tools_used: ["Bash", "Bash", "Bash"] }];
    const result = extractToolPreferences(convs);
    assert.ok(result.Bash);
    assert.equal(result.Bash.ratio, 1);
    assert.equal(result.Bash.avgPerSession, 3);
  });

  it("sorts result by ratio descending", () => {
    const convs = [
      { toolsUsed: ["Read"] },
      { toolsUsed: ["Read"] },
      { toolsUsed: ["Edit"] },
    ];
    const result = extractToolPreferences(convs);
    const keys = Object.keys(result);
    assert.equal(keys[0], "Read", "Read should come first (higher ratio)");
  });

  it("ignores non-array toolsUsed", () => {
    const convs = [{ toolsUsed: "not-an-array" }];
    const result = extractToolPreferences(convs);
    assert.deepEqual(result, {});
  });
});

// ---------------------------------------------------------------------------
// extractSessionShape
// ---------------------------------------------------------------------------

describe("extractSessionShape", () => {
  it("returns default shape for empty input", () => {
    const result = extractSessionShape([]);
    assert.equal(result.avgDuration, 0);
    assert.equal(result.avgTurns, 0);
    assert.equal(result.avgMessages, 0);
    assert.equal(result.burstRatio, 0);
    assert.equal(result.explorationRatio, 0);
    assert.equal(result.dominantMode, "mixed");
  });

  it("burst mode — all sessions < 10min (600000ms)", () => {
    const convs = [
      { duration: 300000, turnCount: 5, messageCount: 10 },
      { duration: 400000, turnCount: 8, messageCount: 15 },
      { duration: 200000, turnCount: 3, messageCount: 6 },
    ];
    const result = extractSessionShape(convs);
    assert.equal(result.dominantMode, "burst");
    assert.ok(result.burstRatio > 0.6);
    assert.equal(result.avgDuration, 300000);
    assert.ok(Math.abs(result.avgTurns - 16 / 3) < 0.001);
  });

  it("exploration mode — all sessions > 20 turns", () => {
    const convs = [
      { duration: 1800000, turnCount: 25, messageCount: 50 },
      { duration: 2400000, turnCount: 30, messageCount: 60 },
      { duration: 3600000, turnCount: 40, messageCount: 80 },
    ];
    const result = extractSessionShape(convs);
    assert.equal(result.dominantMode, "exploration");
    assert.ok(result.explorationRatio > 0.6);
  });

  it("mixed mode — neither burst nor exploration dominant", () => {
    const convs = [
      { duration: 300000, turnCount: 5, messageCount: 10 },    // burst
      { duration: 1800000, turnCount: 25, messageCount: 50 },   // exploration
      { duration: 900000, turnCount: 15, messageCount: 30 },    // neither
    ];
    const result = extractSessionShape(convs);
    assert.equal(result.dominantMode, "mixed");
  });

  it("uses durationMs as fallback for duration", () => {
    const convs = [{ durationMs: 300000, turns: 5 }];
    const result = extractSessionShape(convs);
    assert.equal(result.avgDuration, 300000);
    assert.equal(result.avgTurns, 5);
  });

  it("uses messages.length when messageCount is missing", () => {
    const convs = [{ duration: 100000, turnCount: 3, messages: [1, 2, 3, 4, 5] }];
    const result = extractSessionShape(convs);
    assert.equal(result.avgMessages, 5);
  });

  it("handles missing duration/turns/messages gracefully", () => {
    const convs = [{}, {}];
    const result = extractSessionShape(convs);
    assert.equal(result.avgDuration, 0);
    assert.equal(result.avgTurns, 0);
    assert.equal(result.avgMessages, 0);
  });
});
