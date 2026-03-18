const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const {
  sparseDot,
  sparseNorm,
  sparseAdd,
  sparseScale,
  sparseTopK,
  sparseCosine,
  denseToSparse,
  sparseToDense,
} = require("../../mcp-server/shared/sparse");

describe("sparseDot", () => {
  it("returns 0 for empty maps", () => {
    assert.equal(sparseDot(new Map(), new Map()), 0);
  });

  it("returns 0 for disjoint keys", () => {
    const a = new Map([["x", 1]]);
    const b = new Map([["y", 2]]);
    assert.equal(sparseDot(a, b), 0);
  });

  it("computes dot product of overlapping keys", () => {
    const a = new Map([["x", 2], ["y", 3]]);
    const b = new Map([["x", 4], ["y", 5], ["z", 6]]);
    assert.equal(sparseDot(a, b), 23); // 2*4 + 3*5
  });

  it("is symmetric", () => {
    const a = new Map([["a", 1], ["b", 2]]);
    const b = new Map([["b", 3], ["c", 4]]);
    assert.equal(sparseDot(a, b), sparseDot(b, a));
  });
});

describe("sparseNorm", () => {
  it("returns 0 for empty map", () => {
    assert.equal(sparseNorm(new Map()), 0);
  });

  it("computes L2 norm", () => {
    const v = new Map([["x", 3], ["y", 4]]);
    assert.equal(sparseNorm(v), 5);
  });
});

describe("sparseAdd", () => {
  it("adds two sparse vectors", () => {
    const a = new Map([["x", 1], ["y", 2]]);
    const b = new Map([["y", 3], ["z", 4]]);
    const result = sparseAdd(a, b);
    assert.equal(result.get("x"), 1);
    assert.equal(result.get("y"), 5);
    assert.equal(result.get("z"), 4);
  });

  it("removes entries that sum to zero", () => {
    const a = new Map([["x", 5]]);
    const b = new Map([["x", -5]]);
    const result = sparseAdd(a, b);
    assert.equal(result.has("x"), false);
  });

  it("handles empty maps", () => {
    const a = new Map([["x", 1]]);
    const result = sparseAdd(a, new Map());
    assert.equal(result.get("x"), 1);
  });
});

describe("sparseScale", () => {
  it("scales by scalar", () => {
    const v = new Map([["x", 2], ["y", 3]]);
    const result = sparseScale(v, 3);
    assert.equal(result.get("x"), 6);
    assert.equal(result.get("y"), 9);
  });

  it("returns empty map when scaled by 0", () => {
    const v = new Map([["x", 1]]);
    const result = sparseScale(v, 0);
    assert.equal(result.size, 0);
  });
});

describe("sparseTopK", () => {
  it("returns top K by absolute value", () => {
    const v = new Map([["a", 1], ["b", -5], ["c", 3], ["d", -2]]);
    const result = sparseTopK(v, 2);
    assert.equal(result.size, 2);
    assert.equal(result.has("b"), true);
    assert.equal(result.has("c"), true);
  });

  it("returns all if K >= size", () => {
    const v = new Map([["a", 1], ["b", 2]]);
    const result = sparseTopK(v, 5);
    assert.equal(result.size, 2);
  });

  it("handles empty map", () => {
    const result = sparseTopK(new Map(), 3);
    assert.equal(result.size, 0);
  });
});

describe("sparseCosine", () => {
  it("returns 0 for empty vectors", () => {
    assert.equal(sparseCosine(new Map(), new Map()), 0);
  });

  it("returns 1 for identical vectors", () => {
    const v = new Map([["x", 1], ["y", 2]]);
    assert.ok(Math.abs(sparseCosine(v, v) - 1) < 1e-10);
  });

  it("returns 0 for orthogonal vectors", () => {
    const a = new Map([["x", 1]]);
    const b = new Map([["y", 1]]);
    assert.equal(sparseCosine(a, b), 0);
  });

  it("result is in [-1, 1]", () => {
    const a = new Map([["x", 1], ["y", -3]]);
    const b = new Map([["x", -2], ["y", 4]]);
    const result = sparseCosine(a, b);
    assert.ok(result >= -1 && result <= 1);
  });
});

describe("denseToSparse", () => {
  it("converts dense to sparse with labels", () => {
    const result = denseToSparse([1, 0, 3], ["a", "b", "c"]);
    assert.equal(result.get("a"), 1);
    assert.equal(result.has("b"), false);
    assert.equal(result.get("c"), 3);
  });

  it("respects threshold", () => {
    const result = denseToSparse([0.001, 0.1], ["a", "b"], 0.01);
    assert.equal(result.has("a"), false);
    assert.equal(result.get("b"), 0.1);
  });

  it("handles empty arrays", () => {
    const result = denseToSparse([], []);
    assert.equal(result.size, 0);
  });
});

describe("sparseToDense", () => {
  it("converts sparse to dense with labels", () => {
    const sparse = new Map([["b", 5], ["c", 3]]);
    const result = sparseToDense(sparse, ["a", "b", "c"]);
    assert.deepEqual(result, [0, 5, 3]);
  });

  it("returns zeros for empty sparse", () => {
    const result = sparseToDense(new Map(), ["a", "b"]);
    assert.deepEqual(result, [0, 0]);
  });
});
