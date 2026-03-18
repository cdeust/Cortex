const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const { simpleHash } = require("../../mcp-server/shared/hash");

describe("simpleHash", () => {
  it("is deterministic (same input produces same output)", () => {
    const input = "hello world";
    assert.equal(simpleHash(input), simpleHash(input));
  });

  it("produces same hash across multiple calls", () => {
    const hash1 = simpleHash("test string");
    const hash2 = simpleHash("test string");
    const hash3 = simpleHash("test string");
    assert.equal(hash1, hash2);
    assert.equal(hash2, hash3);
  });

  it("different inputs produce different outputs", () => {
    const a = simpleHash("hello");
    const b = simpleHash("world");
    assert.notEqual(a, b);
  });

  it("similar but distinct inputs produce different hashes", () => {
    const a = simpleHash("abc");
    const b = simpleHash("abd");
    assert.notEqual(a, b);
  });

  it("handles empty string input", () => {
    const result = simpleHash("");
    assert.ok(typeof result === "string");
    assert.ok(result.length > 0);
  });

  it("handles null input", () => {
    const result = simpleHash(null);
    assert.ok(typeof result === "string");
    assert.ok(result.length > 0);
    // null is coerced to "" internally, so should match empty string hash
    assert.equal(result, simpleHash(""));
  });

  it("handles undefined input", () => {
    const result = simpleHash(undefined);
    assert.ok(typeof result === "string");
    assert.equal(result, simpleHash(""));
  });

  it("returns a hexadecimal string", () => {
    const result = simpleHash("test");
    assert.match(result, /^[0-9a-f]+$/);
  });

  it("truncates to first 500 characters", () => {
    const base = "a".repeat(500);
    const extended = base + "b".repeat(100);
    // Both should hash the same since only first 500 chars are used
    assert.equal(simpleHash(base), simpleHash(extended));
  });
});
