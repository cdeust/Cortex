const { describe, it, before, after } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");

const {
  readJSON,
  writeJSON,
  readTextFile,
  ensureDir,
  listDir,
} = require("../../mcp-server/infrastructure/file-io");

describe("file-io", () => {
  let tmpDir;

  before(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "file-io-test-"));
  });

  after(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  // ---------------------------------------------------------------------------
  // readJSON
  // ---------------------------------------------------------------------------

  describe("readJSON", () => {
    it("parses a valid JSON file", () => {
      const filePath = path.join(tmpDir, "valid.json");
      fs.writeFileSync(filePath, JSON.stringify({ foo: 42 }), "utf-8");

      const result = readJSON(filePath);
      assert.deepEqual(result, { foo: 42 });
    });

    it("returns null for a missing file", () => {
      const result = readJSON(path.join(tmpDir, "nonexistent.json"));
      assert.equal(result, null);
    });

    it("returns null for corrupt JSON", () => {
      const filePath = path.join(tmpDir, "corrupt.json");
      fs.writeFileSync(filePath, "{not valid json!!!", "utf-8");

      const result = readJSON(filePath);
      assert.equal(result, null);
    });
  });

  // ---------------------------------------------------------------------------
  // writeJSON
  // ---------------------------------------------------------------------------

  describe("writeJSON", () => {
    it("creates parent directories and writes valid JSON", () => {
      const filePath = path.join(tmpDir, "nested", "deep", "out.json");

      writeJSON(filePath, { hello: "world" });

      assert.ok(fs.existsSync(filePath));
      const content = JSON.parse(fs.readFileSync(filePath, "utf-8"));
      assert.deepEqual(content, { hello: "world" });
    });

    it("overwrites an existing file", () => {
      const filePath = path.join(tmpDir, "overwrite.json");
      writeJSON(filePath, { v: 1 });
      writeJSON(filePath, { v: 2 });

      const content = JSON.parse(fs.readFileSync(filePath, "utf-8"));
      assert.equal(content.v, 2);
    });
  });

  // ---------------------------------------------------------------------------
  // ensureDir
  // ---------------------------------------------------------------------------

  describe("ensureDir", () => {
    it("creates nested directories", () => {
      const dirPath = path.join(tmpDir, "a", "b", "c");
      ensureDir(dirPath);

      assert.ok(fs.existsSync(dirPath));
      assert.ok(fs.statSync(dirPath).isDirectory());
    });

    it("does not throw if directory already exists", () => {
      const dirPath = path.join(tmpDir, "already-exists");
      fs.mkdirSync(dirPath, { recursive: true });

      assert.doesNotThrow(() => ensureDir(dirPath));
    });
  });

  // ---------------------------------------------------------------------------
  // readTextFile
  // ---------------------------------------------------------------------------

  describe("readTextFile", () => {
    it("reads a UTF-8 text file", () => {
      const filePath = path.join(tmpDir, "hello.txt");
      fs.writeFileSync(filePath, "hello world", "utf-8");

      const result = readTextFile(filePath);
      assert.equal(result, "hello world");
    });

    it("returns null for a missing file", () => {
      const result = readTextFile(path.join(tmpDir, "missing.txt"));
      assert.equal(result, null);
    });
  });

  // ---------------------------------------------------------------------------
  // listDir
  // ---------------------------------------------------------------------------

  describe("listDir", () => {
    it("lists files in a directory", () => {
      const dirPath = path.join(tmpDir, "listdir-test");
      fs.mkdirSync(dirPath, { recursive: true });
      fs.writeFileSync(path.join(dirPath, "a.txt"), "a");
      fs.writeFileSync(path.join(dirPath, "b.txt"), "b");

      const result = listDir(dirPath);
      assert.ok(Array.isArray(result));
      assert.ok(result.includes("a.txt"));
      assert.ok(result.includes("b.txt"));
    });

    it("returns null for a missing directory", () => {
      const result = listDir(path.join(tmpDir, "no-such-dir"));
      assert.equal(result, null);
    });
  });
});
