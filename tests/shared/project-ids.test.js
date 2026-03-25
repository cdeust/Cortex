const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const {
  cwdToProjectId,
  projectIdToLabel,
  domainIdFromLabel,
} = require("../../mcp-server/shared/project-ids");

describe("cwdToProjectId", () => {
  it("converts a normal path to project ID", () => {
    assert.equal(cwdToProjectId("/Users/dev/cortex"), "-Users-dev-cortex");
  });

  it("replaces all slashes with dashes", () => {
    assert.equal(
      cwdToProjectId("/Users/dev/Developments/my-project"),
      "-Users-dev-Developments-my-project"
    );
  });

  it("returns null for null input", () => {
    assert.equal(cwdToProjectId(null), null);
  });

  it("returns null for undefined input", () => {
    assert.equal(cwdToProjectId(undefined), null);
  });

  it("returns null for empty string", () => {
    assert.equal(cwdToProjectId(""), null);
  });
});

describe("projectIdToLabel", () => {
  it("strips Users prefix and returns project name", () => {
    const label = projectIdToLabel("-Users-dev-Developments-cortex");
    assert.equal(label, "cortex");
  });

  it("strips Users and Documents prefix", () => {
    const label = projectIdToLabel("-Users-dev-Documents-myproject");
    assert.equal(label, "myproject");
  });

  it('returns "Unknown" for null', () => {
    assert.equal(projectIdToLabel(null), "Unknown");
  });

  it('returns "Unknown" for undefined', () => {
    assert.equal(projectIdToLabel(undefined), "Unknown");
  });

  it('returns "Unknown" for empty string', () => {
    assert.equal(projectIdToLabel(""), "Unknown");
  });

  it("replaces dashes with spaces in remaining path", () => {
    const label = projectIdToLabel("-Users-dev-Developments-my-project");
    assert.equal(label, "my project");
  });
});

describe("domainIdFromLabel", () => {
  it("lowercases the label", () => {
    assert.equal(domainIdFromLabel("MyProject"), "myproject");
  });

  it("replaces non-alphanumeric characters with dashes", () => {
    assert.equal(domainIdFromLabel("My Project Name"), "my-project-name");
  });

  it("strips leading and trailing dashes", () => {
    assert.equal(domainIdFromLabel("  My Project  "), "my-project");
  });

  it('returns "" for empty string', () => {
    assert.equal(domainIdFromLabel(""), "");
  });

  it('returns "" for null', () => {
    assert.equal(domainIdFromLabel(null), "");
  });

  it('returns "" for undefined', () => {
    assert.equal(domainIdFromLabel(undefined), "");
  });

  it("handles special characters", () => {
    assert.equal(domainIdFromLabel("project@v2.0!"), "project-v2-0");
  });
});
