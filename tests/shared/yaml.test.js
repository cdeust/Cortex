const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const { parseYAMLFrontmatter } = require("../../mcp-server/shared/yaml");

describe("parseYAMLFrontmatter", () => {
  it("parses valid frontmatter with key-value pairs", () => {
    const content = "---\nname: test\ntype: user\n---\nBody text here";
    const result = parseYAMLFrontmatter(content);
    assert.deepEqual(result.meta, { name: "test", type: "user" });
    assert.equal(result.body, "Body text here");
  });

  it("returns body only when no frontmatter present", () => {
    const content = "No frontmatter here, just body text.";
    const result = parseYAMLFrontmatter(content);
    assert.deepEqual(result.meta, {});
    assert.equal(result.body, "No frontmatter here, just body text.");
  });

  it("returns empty meta and body for null input", () => {
    const result = parseYAMLFrontmatter(null);
    assert.deepEqual(result.meta, {});
    assert.equal(result.body, "");
  });

  it("returns empty meta and body for undefined input", () => {
    const result = parseYAMLFrontmatter(undefined);
    assert.deepEqual(result.meta, {});
    assert.equal(result.body, "");
  });

  it("returns empty meta and body for empty string", () => {
    const result = parseYAMLFrontmatter("");
    assert.deepEqual(result.meta, {});
    assert.equal(result.body, "");
  });

  it("handles nested colons in values", () => {
    const content = "---\nurl: http://example.com:8080/path\ntitle: My Title\n---\nBody";
    const result = parseYAMLFrontmatter(content);
    assert.equal(result.meta["url"], "http://example.com:8080/path");
    assert.equal(result.meta["title"], "My Title");
    assert.equal(result.body, "Body");
  });

  it("lowercases meta keys", () => {
    const content = "---\nName: test\nType: user\n---\nBody";
    const result = parseYAMLFrontmatter(content);
    assert.ok("name" in result.meta);
    assert.ok("type" in result.meta);
    assert.ok(!("Name" in result.meta));
  });

  it("trims whitespace from values", () => {
    const content = "---\nname:   spaced value   \n---\nBody";
    const result = parseYAMLFrontmatter(content);
    assert.equal(result.meta["name"], "spaced value");
  });

  it("trims body text", () => {
    const content = "---\nname: test\n---\n\n  Body with whitespace  \n\n";
    const result = parseYAMLFrontmatter(content);
    assert.equal(result.body, "Body with whitespace");
  });

  it("handles multiple key-value pairs", () => {
    const content = "---\na: 1\nb: 2\nc: 3\nd: 4\n---\nBody";
    const result = parseYAMLFrontmatter(content);
    assert.equal(Object.keys(result.meta).length, 4);
    assert.equal(result.meta["a"], "1");
    assert.equal(result.meta["d"], "4");
  });
});
