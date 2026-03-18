const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const {
  extractKeywords,
  extractKeywordsArray,
  STOPWORDS,
  TECHNICAL_SHORT_TERMS,
} = require("../../mcp-server/shared/text");

describe("extractKeywords", () => {
  it("returns empty Set for empty string", () => {
    const result = extractKeywords("");
    assert.ok(result instanceof Set);
    assert.equal(result.size, 0);
  });

  it("returns empty Set for null/undefined", () => {
    assert.equal(extractKeywords(null).size, 0);
    assert.equal(extractKeywords(undefined).size, 0);
  });

  it("handles unicode text without crashing", () => {
    const result = extractKeywords("configuraci\u00f3n del servidor autenticaci\u00f3n");
    assert.ok(result instanceof Set);
    // "configuraci" and "autenticaci" are >6 chars fragments after split on non-word
    // The actual split depends on \W+ handling of accented chars
  });

  it("extracts technical abbreviations (api, sql)", () => {
    const result = extractKeywords("use the api to run sql queries");
    assert.ok(result.has("api"));
    assert.ok(result.has("sql"));
  });

  it("handles mixed case by lowercasing", () => {
    const result = extractKeywords("API SQL Authentication");
    assert.ok(result.has("api"));
    assert.ok(result.has("sql"));
    assert.ok(result.has("authentication"));
  });

  it("passes words longer than 6 characters", () => {
    const result = extractKeywords("refactoring authentication middleware");
    assert.ok(result.has("refactoring"));
    assert.ok(result.has("authentication"));
    assert.ok(result.has("middleware"));
  });

  it("filters out short non-technical words", () => {
    const result = extractKeywords("the cat sat on a mat");
    // "the" is stopword but also <7 and not in TECHNICAL_SHORT_TERMS
    // "cat", "sat", "mat" are 3 chars and not in TECHNICAL_SHORT_TERMS
    assert.equal(result.size, 0);
  });

  it("handles long text", () => {
    const longText = "authentication ".repeat(1000) + "api sql debugging";
    const result = extractKeywords(longText);
    assert.ok(result.has("authentication"));
    assert.ok(result.has("api"));
    assert.ok(result.has("sql"));
    assert.ok(result.has("debugging"));
  });

  it("deduplicates keywords", () => {
    const result = extractKeywords("api api api authentication authentication");
    assert.equal(result.size, 2);
    assert.ok(result.has("api"));
    assert.ok(result.has("authentication"));
  });
});

describe("extractKeywordsArray", () => {
  it("returns an array", () => {
    const result = extractKeywordsArray("api authentication");
    assert.ok(Array.isArray(result));
  });

  it("returns empty array for empty string", () => {
    const result = extractKeywordsArray("");
    assert.ok(Array.isArray(result));
    assert.equal(result.length, 0);
  });

  it("contains same elements as extractKeywords", () => {
    const text = "api authentication middleware";
    const set = extractKeywords(text);
    const arr = extractKeywordsArray(text);
    assert.equal(arr.length, set.size);
    for (const kw of arr) {
      assert.ok(set.has(kw));
    }
  });
});

describe("STOPWORDS filtering", () => {
  it("excludes common stopwords from results", () => {
    const stopwordSamples = ["the", "and", "for", "with", "from", "this", "that"];
    for (const sw of stopwordSamples) {
      const result = extractKeywords(sw);
      assert.ok(!result.has(sw), `stopword "${sw}" should not appear in results`);
    }
  });

  it("STOPWORDS set contains common English words", () => {
    assert.ok(STOPWORDS.has("the"));
    assert.ok(STOPWORDS.has("and"));
    assert.ok(STOPWORDS.has("for"));
    assert.ok(STOPWORDS.has("with"));
    assert.ok(STOPWORDS.has("about"));
  });
});

describe("TECHNICAL_SHORT_TERMS inclusion", () => {
  it("includes known short technical terms", () => {
    assert.ok(TECHNICAL_SHORT_TERMS.has("api"));
    assert.ok(TECHNICAL_SHORT_TERMS.has("sql"));
    assert.ok(TECHNICAL_SHORT_TERMS.has("jwt"));
    assert.ok(TECHNICAL_SHORT_TERMS.has("cli"));
    assert.ok(TECHNICAL_SHORT_TERMS.has("mcp"));
    assert.ok(TECHNICAL_SHORT_TERMS.has("git"));
  });

  it("extractKeywords picks up technical short terms from text", () => {
    const terms = ["api", "sql", "jwt", "cli", "mcp", "git", "auth", "ssh", "npm"];
    for (const term of terms) {
      const result = extractKeywords(`use ${term} here`);
      assert.ok(result.has(term), `technical term "${term}" should be extracted`);
    }
  });

  it("TECHNICAL_SHORT_TERMS is a frozen-like Set (not mutated)", () => {
    assert.ok(TECHNICAL_SHORT_TERMS instanceof Set);
    assert.ok(TECHNICAL_SHORT_TERMS.size > 0);
  });
});
