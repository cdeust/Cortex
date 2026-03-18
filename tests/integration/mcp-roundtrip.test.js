const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const { spawn } = require("node:child_process");
const path = require("node:path");

/**
 * Send a JSON-RPC message to the child process and collect the response.
 *
 * @param {import('child_process').ChildProcess} proc
 * @param {Object} message
 * @param {number} timeoutMs
 * @returns {Promise<Object>}
 */
function sendMessage(proc, message, timeoutMs = 5000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      reject(new Error(`Timeout waiting for response to method: ${message.method}`));
    }, timeoutMs);

    const onData = (chunk) => {
      const lines = chunk.toString().split("\n").filter((l) => l.trim());
      for (const line of lines) {
        try {
          const parsed = JSON.parse(line);
          if (parsed.id === message.id) {
            clearTimeout(timer);
            proc.stdout.removeListener("data", onData);
            resolve(parsed);
            return;
          }
        } catch (_) {
          // Not JSON, skip
        }
      }
    };

    proc.stdout.on("data", onData);
    proc.stdin.write(JSON.stringify(message) + "\n");
  });
}

describe("MCP roundtrip integration", () => {
  it("completes initialize -> tools/list -> tools/call roundtrip", async () => {
    const serverPath = path.join(__dirname, "../../mcp-server/index.js");

    const proc = spawn(process.execPath, [serverPath], {
      stdio: ["pipe", "pipe", "pipe"],
    });

    try {
      // Step 1: initialize
      const initResponse = await sendMessage(proc, {
        jsonrpc: "2.0",
        id: 1,
        method: "initialize",
        params: {},
      });

      assert.equal(initResponse.jsonrpc, "2.0");
      assert.equal(initResponse.id, 1);
      assert.ok(initResponse.result, "initialize should return result");
      assert.ok(initResponse.result.serverInfo, "should have serverInfo");
      assert.equal(initResponse.result.serverInfo.name, "methodology-agent");

      // Send initialized notification (no response expected)
      proc.stdin.write(
        JSON.stringify({
          jsonrpc: "2.0",
          method: "notifications/initialized",
        }) + "\n"
      );

      // Step 2: tools/list
      const listResponse = await sendMessage(proc, {
        jsonrpc: "2.0",
        id: 2,
        method: "tools/list",
        params: {},
      });

      assert.equal(listResponse.id, 2);
      assert.ok(listResponse.result, "tools/list should return result");
      assert.ok(Array.isArray(listResponse.result.tools), "tools should be an array");
      assert.ok(listResponse.result.tools.length > 0, "should have at least one tool");

      // Verify expected tools are present
      const toolNames = listResponse.result.tools.map((t) => t.name);
      assert.ok(toolNames.includes("query_methodology"), "should include query_methodology");
      assert.ok(toolNames.includes("list_domains"), "should include list_domains");

      // Step 3: tools/call (list_domains as a safe, read-only call)
      const callResponse = await sendMessage(proc, {
        jsonrpc: "2.0",
        id: 3,
        method: "tools/call",
        params: { name: "list_domains", arguments: {} },
      });

      assert.equal(callResponse.id, 3);
      assert.ok(callResponse.result, "tools/call should return result");
      assert.ok(callResponse.result.content, "should have content");
      assert.ok(Array.isArray(callResponse.result.content), "content should be an array");
      assert.equal(callResponse.result.content[0].type, "text");

      const callData = JSON.parse(callResponse.result.content[0].text);
      assert.ok("domains" in callData, "response should have domains");
      assert.ok("totalDomains" in callData, "response should have totalDomains");
    } finally {
      proc.kill("SIGTERM");
    }
  });
});
