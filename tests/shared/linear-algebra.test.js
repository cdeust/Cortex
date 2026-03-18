const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const {
  dot,
  norm,
  normalize,
  cosineSimilarity,
  add,
  subtract,
  scale,
  project,
  clamp,
  zeros,
} = require("../../mcp-server/shared/linear-algebra");

describe("dot", () => {
  it("returns 0 for empty vectors", () => {
    assert.equal(dot([], []), 0);
  });

  it("computes dot product of equal-length vectors", () => {
    assert.equal(dot([1, 2, 3], [4, 5, 6]), 32);
  });

  it("handles unequal lengths by using shorter", () => {
    assert.equal(dot([1, 2], [3, 4, 5]), 11);
  });

  it("returns 0 for orthogonal vectors", () => {
    assert.equal(dot([1, 0], [0, 1]), 0);
  });
});

describe("norm", () => {
  it("returns 0 for empty vector", () => {
    assert.equal(norm([]), 0);
  });

  it("returns 0 for zero vector", () => {
    assert.equal(norm([0, 0, 0]), 0);
  });

  it("computes L2 norm", () => {
    assert.equal(norm([3, 4]), 5);
  });

  it("handles single element", () => {
    assert.equal(norm([7]), 7);
  });
});

describe("normalize", () => {
  it("returns zero vector for zero input", () => {
    assert.deepEqual(normalize([0, 0]), [0, 0]);
  });

  it("returns unit vector", () => {
    const result = normalize([3, 4]);
    assert.ok(Math.abs(result[0] - 0.6) < 1e-10);
    assert.ok(Math.abs(result[1] - 0.8) < 1e-10);
  });

  it("normalized vector has norm 1", () => {
    const result = normalize([1, 2, 3, 4]);
    assert.ok(Math.abs(norm(result) - 1) < 1e-10);
  });
});

describe("cosineSimilarity", () => {
  it("returns 0 when either vector is zero", () => {
    assert.equal(cosineSimilarity([0, 0], [1, 2]), 0);
    assert.equal(cosineSimilarity([1, 2], [0, 0]), 0);
  });

  it("returns 1 for identical directions", () => {
    assert.ok(Math.abs(cosineSimilarity([1, 2], [2, 4]) - 1) < 1e-10);
  });

  it("returns -1 for opposite directions", () => {
    assert.ok(Math.abs(cosineSimilarity([1, 0], [-1, 0]) - (-1)) < 1e-10);
  });

  it("returns 0 for orthogonal vectors", () => {
    assert.ok(Math.abs(cosineSimilarity([1, 0], [0, 1])) < 1e-10);
  });

  it("is symmetric", () => {
    const a = [1, 2, 3];
    const b = [4, 5, 6];
    assert.ok(Math.abs(cosineSimilarity(a, b) - cosineSimilarity(b, a)) < 1e-10);
  });

  it("result is in [-1, 1]", () => {
    const result = cosineSimilarity([1, -3, 2], [-4, 5, 1]);
    assert.ok(result >= -1 && result <= 1);
  });
});

describe("add", () => {
  it("adds equal-length vectors", () => {
    assert.deepEqual(add([1, 2], [3, 4]), [4, 6]);
  });

  it("handles unequal lengths", () => {
    assert.deepEqual(add([1], [2, 3]), [3, 3]);
  });

  it("handles empty vectors", () => {
    assert.deepEqual(add([], []), []);
  });
});

describe("subtract", () => {
  it("subtracts equal-length vectors", () => {
    assert.deepEqual(subtract([5, 3], [1, 2]), [4, 1]);
  });

  it("handles unequal lengths", () => {
    assert.deepEqual(subtract([1], [2, 3]), [-1, -3]);
  });
});

describe("scale", () => {
  it("multiplies by scalar", () => {
    assert.deepEqual(scale([1, 2, 3], 2), [2, 4, 6]);
  });

  it("scaling by 0 returns zero vector", () => {
    assert.deepEqual(scale([1, 2], 0), [0, 0]);
  });

  it("handles empty vector", () => {
    assert.deepEqual(scale([], 5), []);
  });
});

describe("project", () => {
  it("projects onto axis-aligned vector", () => {
    const result = project([3, 4], [1, 0]);
    assert.ok(Math.abs(result[0] - 3) < 1e-10);
    assert.ok(Math.abs(result[1] - 0) < 1e-10);
  });

  it("returns zero when projecting onto zero vector", () => {
    assert.deepEqual(project([1, 2], [0, 0]), [0, 0]);
  });

  it("projection onto itself returns same vector", () => {
    const v = [3, 4];
    const result = project(v, v);
    assert.ok(Math.abs(result[0] - 3) < 1e-10);
    assert.ok(Math.abs(result[1] - 4) < 1e-10);
  });
});

describe("clamp", () => {
  it("clamps values to range", () => {
    assert.deepEqual(clamp([-2, 0.5, 3], -1, 1), [-1, 0.5, 1]);
  });

  it("returns same values if already in range", () => {
    assert.deepEqual(clamp([0, 0.5, 1], 0, 1), [0, 0.5, 1]);
  });
});

describe("zeros", () => {
  it("creates zero vector of given dimension", () => {
    assert.deepEqual(zeros(3), [0, 0, 0]);
  });

  it("creates empty array for dim 0", () => {
    assert.deepEqual(zeros(0), []);
  });
});
