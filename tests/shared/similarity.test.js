const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const { jaccardSimilarity } = require("../../mcp-server/shared/similarity");

describe("jaccardSimilarity", () => {
  it("returns 0 for two empty sets", () => {
    assert.equal(jaccardSimilarity(new Set(), new Set()), 0);
  });

  it("returns 1 for identical sets", () => {
    const s = new Set(["a", "b", "c"]);
    assert.equal(jaccardSimilarity(s, s), 1);
  });

  it("returns 1 for equal but different set instances", () => {
    const a = new Set(["x", "y", "z"]);
    const b = new Set(["x", "y", "z"]);
    assert.equal(jaccardSimilarity(a, b), 1);
  });

  it("returns 0 for completely disjoint sets", () => {
    const a = new Set(["a", "b"]);
    const b = new Set(["c", "d"]);
    assert.equal(jaccardSimilarity(a, b), 0);
  });

  it("returns correct value for partial overlap", () => {
    const a = new Set(["a", "b", "c"]);
    const b = new Set(["b", "c", "d"]);
    // intersection = {b, c} = 2, union = {a, b, c, d} = 4
    assert.equal(jaccardSimilarity(a, b), 0.5);
  });

  it("handles single-element identical sets", () => {
    const a = new Set(["x"]);
    const b = new Set(["x"]);
    assert.equal(jaccardSimilarity(a, b), 1);
  });

  it("handles single-element disjoint sets", () => {
    const a = new Set(["x"]);
    const b = new Set(["y"]);
    assert.equal(jaccardSimilarity(a, b), 0);
  });

  it("returns 0 when one set is empty and other is not", () => {
    assert.equal(jaccardSimilarity(new Set(), new Set(["a"])), 0);
    assert.equal(jaccardSimilarity(new Set(["a"]), new Set()), 0);
  });

  it("is symmetric (A,B) == (B,A)", () => {
    const a = new Set(["a", "b", "c"]);
    const b = new Set(["c", "d", "e"]);
    assert.equal(jaccardSimilarity(a, b), jaccardSimilarity(b, a));
  });

  it("result is always between 0 and 1", () => {
    const a = new Set(["a", "b", "c", "d"]);
    const b = new Set(["c", "d", "e"]);
    const result = jaccardSimilarity(a, b);
    assert.ok(result >= 0);
    assert.ok(result <= 1);
  });
});
