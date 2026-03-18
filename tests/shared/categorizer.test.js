const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const {
  categorize,
  categorizeWithScores,
} = require("../../mcp-server/shared/categorizer");

describe("categorize", () => {
  it('classifies bug-fix text as "bug-fix"', () => {
    assert.equal(categorize("fix the broken login bug"), "bug-fix");
  });

  it('classifies feature text as "feature"', () => {
    assert.equal(categorize("add new user registration"), "feature");
  });

  it('classifies refactor text as "refactor"', () => {
    assert.equal(categorize("refactor the data layer and simplify"), "refactor");
  });

  it('classifies research text as "research"', () => {
    assert.equal(categorize("research and evaluate different frameworks"), "research");
  });

  it('classifies config text as "config"', () => {
    assert.equal(categorize("setup the environment config"), "config");
  });

  it('classifies docs text as "docs"', () => {
    assert.equal(categorize("document the API and update the readme"), "docs");
  });

  it('classifies debug text as "debug"', () => {
    assert.equal(categorize("debug the issue and inspect the log"), "debug");
  });

  it('classifies architecture text as "architecture"', () => {
    assert.equal(categorize("design the system architecture and module pattern"), "architecture");
  });

  it('classifies deployment text as "deployment"', () => {
    assert.equal(categorize("deploy to production with docker"), "deployment");
  });

  it('classifies testing text as "testing"', () => {
    assert.equal(categorize("write unit test with mock and assert"), "testing");
  });

  it("returns best match for ambiguous text", () => {
    const result = categorize("fix the broken test");
    // "fix" and "broken" → bug-fix (2.0), "test" → testing (1.0)
    assert.equal(result, "bug-fix");
  });

  it('returns "general" for empty text', () => {
    assert.equal(categorize(""), "general");
  });

  it('returns "general" for null', () => {
    assert.equal(categorize(null), "general");
  });

  it('returns "general" for undefined', () => {
    assert.equal(categorize(undefined), "general");
  });

  it('returns "general" for text with no matching signals', () => {
    assert.equal(categorize("hello world foo bar"), "general");
  });
});

describe("categorizeWithScores", () => {
  it("returns multiple category scores", () => {
    const scores = categorizeWithScores("implement new test for the API");
    // "implement" + "new" → feature: 2.0, "test" → testing: 1.0
    assert.ok(scores["feature"] !== undefined);
    assert.ok(scores["testing"] !== undefined);
  });

  it("returns empty object for empty text", () => {
    const scores = categorizeWithScores("");
    assert.deepEqual(scores, {});
  });

  it("returns empty object for null", () => {
    const scores = categorizeWithScores(null);
    assert.deepEqual(scores, {});
  });

  it("scores are positive numbers", () => {
    const scores = categorizeWithScores("fix the bug and refactor the code");
    for (const [, score] of Object.entries(scores)) {
      assert.ok(typeof score === "number");
      assert.ok(score > 0);
    }
  });

  it("multi-word phrases score 1.5", () => {
    // "unit test" is a multi-word signal for testing
    const scores = categorizeWithScores("write a unit test");
    assert.ok(scores["testing"] !== undefined);
    // "test" (1.0) + "unit test" (1.5) = 2.5
    assert.equal(scores["testing"], 2.5);
  });

  it("returns only non-zero categories", () => {
    const scores = categorizeWithScores("fix bug");
    const keys = Object.keys(scores);
    assert.ok(keys.includes("bug-fix"));
    for (const key of keys) {
      assert.ok(scores[key] > 0);
    }
  });
});
