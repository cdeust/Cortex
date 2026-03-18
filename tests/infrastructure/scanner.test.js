const { describe, it, before, after } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");

const {
  readHeadTail,
  groupByProject,
  discoverAllMemories,
  discoverConversations,
} = require("../../mcp-server/infrastructure/scanner");

describe("scanner", () => {
  let tmpDir;

  before(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "scanner-test-"));
  });

  after(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  // ---------------------------------------------------------------------------
  // readHeadTail
  // ---------------------------------------------------------------------------

  describe("readHeadTail", () => {
    it("reads records from a small JSONL file", () => {
      const filePath = path.join(tmpDir, "test.jsonl");
      const lines = [
        JSON.stringify({ type: "user", message: "hello" }),
        JSON.stringify({ type: "assistant", message: "hi" }),
        JSON.stringify({ type: "user", message: "bye" }),
      ];
      fs.writeFileSync(filePath, lines.join("\n") + "\n", "utf-8");

      const records = readHeadTail(filePath);

      assert.ok(Array.isArray(records), "should return an array");
      assert.equal(records.length, 3, "should parse all 3 records");
      assert.equal(records[0].type, "user");
      assert.equal(records[1].type, "assistant");
    });

    it("returns empty array for missing file", () => {
      const records = readHeadTail(path.join(tmpDir, "nope.jsonl"));
      assert.ok(Array.isArray(records));
      assert.equal(records.length, 0);
    });

    it("skips invalid JSON lines gracefully", () => {
      const filePath = path.join(tmpDir, "mixed.jsonl");
      const content = [
        JSON.stringify({ valid: true }),
        "not valid json {{{",
        JSON.stringify({ also: "valid" }),
      ].join("\n") + "\n";
      fs.writeFileSync(filePath, content, "utf-8");

      const records = readHeadTail(filePath);
      assert.equal(records.length, 2, "should skip invalid lines");
    });
  });

  // ---------------------------------------------------------------------------
  // groupByProject
  // ---------------------------------------------------------------------------

  describe("groupByProject", () => {
    it("groups conversations by project", () => {
      const conversations = [
        { sessionId: "a", project: "proj-1" },
        { sessionId: "b", project: "proj-2" },
        { sessionId: "c", project: "proj-1" },
      ];

      const groups = groupByProject(conversations);

      assert.ok(groups["proj-1"], "should have proj-1 group");
      assert.ok(groups["proj-2"], "should have proj-2 group");
      assert.equal(groups["proj-1"].length, 2);
      assert.equal(groups["proj-2"].length, 1);
    });

    it("returns empty object for empty input", () => {
      const groups = groupByProject([]);
      assert.deepEqual(groups, {});
    });
  });

  // ---------------------------------------------------------------------------
  // discoverAllMemories / discoverConversations
  // ---------------------------------------------------------------------------

  describe("discoverAllMemories", () => {
    it("returns an array", () => {
      const memories = discoverAllMemories();
      assert.ok(Array.isArray(memories), "should return an array");
    });
  });

  describe("discoverConversations", () => {
    it("returns an array", () => {
      const conversations = discoverConversations();
      assert.ok(Array.isArray(conversations), "should return an array");
    });
  });
});
