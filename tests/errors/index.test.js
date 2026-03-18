const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const {
  MethodologyError,
  ValidationError,
  StorageError,
  AnalysisError,
  ConnectionError,
} = require("../../mcp-server/errors");

describe("MethodologyError", () => {
  it("has code, message, and details", () => {
    const err = new MethodologyError("something broke", -32000, { key: "val" });
    assert.equal(err.message, "something broke");
    assert.equal(err.code, -32000);
    assert.deepEqual(err.details, { key: "val" });
  });

  it("has name set to MethodologyError", () => {
    const err = new MethodologyError("test");
    assert.equal(err.name, "MethodologyError");
  });

  it("defaults code to -32000", () => {
    const err = new MethodologyError("test");
    assert.equal(err.code, -32000);
  });

  it("defaults details to undefined", () => {
    const err = new MethodologyError("test");
    assert.equal(err.details, undefined);
  });

  it("is an instance of Error", () => {
    const err = new MethodologyError("test");
    assert.ok(err instanceof Error);
  });

  it("is an instance of MethodologyError", () => {
    const err = new MethodologyError("test");
    assert.ok(err instanceof MethodologyError);
  });
});

describe("ValidationError", () => {
  it("is an instance of MethodologyError", () => {
    const err = new ValidationError("bad input");
    assert.ok(err instanceof MethodologyError);
  });

  it("is an instance of Error", () => {
    const err = new ValidationError("bad input");
    assert.ok(err instanceof Error);
  });

  it("has code -32602 (Invalid params)", () => {
    const err = new ValidationError("bad input");
    assert.equal(err.code, -32602);
  });

  it("has name set to ValidationError", () => {
    const err = new ValidationError("bad input");
    assert.equal(err.name, "ValidationError");
  });

  it("carries details", () => {
    const details = { field: "session_id", tool: "record_session_end" };
    const err = new ValidationError("missing field", details);
    assert.deepEqual(err.details, details);
  });

  it("has correct message", () => {
    const err = new ValidationError("field is required");
    assert.equal(err.message, "field is required");
  });
});

describe("StorageError", () => {
  it("is an instance of MethodologyError", () => {
    const err = new StorageError("disk full");
    assert.ok(err instanceof MethodologyError);
  });

  it("has code -32001", () => {
    const err = new StorageError("disk full");
    assert.equal(err.code, -32001);
  });

  it("has name set to StorageError", () => {
    const err = new StorageError("disk full");
    assert.equal(err.name, "StorageError");
  });

  it("carries details", () => {
    const err = new StorageError("write failed", { path: "/tmp/x" });
    assert.deepEqual(err.details, { path: "/tmp/x" });
  });
});

describe("AnalysisError", () => {
  it("is an instance of MethodologyError", () => {
    const err = new AnalysisError("analysis failed");
    assert.ok(err instanceof MethodologyError);
  });

  it("has code -32002", () => {
    const err = new AnalysisError("analysis failed");
    assert.equal(err.code, -32002);
  });

  it("has name set to AnalysisError", () => {
    const err = new AnalysisError("analysis failed");
    assert.equal(err.name, "AnalysisError");
  });

  it("carries details", () => {
    const err = new AnalysisError("no data", { domain: "web" });
    assert.deepEqual(err.details, { domain: "web" });
  });

  it("is an instance of Error", () => {
    const err = new AnalysisError("fail");
    assert.ok(err instanceof Error);
  });
});

describe("ConnectionError", () => {
  it("is an instance of MethodologyError", () => {
    const err = new ConnectionError("connection refused");
    assert.ok(err instanceof MethodologyError);
  });

  it("is an instance of Error", () => {
    const err = new ConnectionError("connection refused");
    assert.ok(err instanceof Error);
  });

  it("has code -32003", () => {
    const err = new ConnectionError("connection refused");
    assert.equal(err.code, -32003);
  });

  it("has name set to ConnectionError", () => {
    const err = new ConnectionError("connection refused");
    assert.equal(err.name, "ConnectionError");
  });

  it("carries details", () => {
    const err = new ConnectionError("timeout", { server: "ai-architect" });
    assert.deepEqual(err.details, { server: "ai-architect" });
  });
});
