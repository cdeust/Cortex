#!/usr/bin/env node
/**
 * Direct invocation of Cortex run_pipeline handler.
 * Usage: node scripts/run-tv-pipeline.js
 */
"use strict";

const path = require("path");

// Resolve handler from mcp-server
const runPipeline = require(path.join(__dirname, "..", "mcp-server", "handlers", "run-pipeline"));

// Override compound threshold for this TechnicalVeil run — findings are research
// papers with low lexical overlap but potential architectural relevance.
// Verification stage (5) still gates on quality.
const origHandler = runPipeline.handler;

async function main() {
  // Temporarily patch the Jaccard filter and compound threshold via env
  process.env.PIPELINE_COMPOUND_THRESHOLD = "0.15";
  process.env.PIPELINE_JACCARD_MIN = "0.005";

  const args = {
    codebase_path: "/Users/cdeust/Developments/ai-architect-prd-builder",
    task_path: path.join(
      process.env.HOME,
      "Downloads/technicalVeil/2026-03-19/findings_curated.json"
    ),
    github_repo: "cdeust/ai-architect-prd-builder",
    server: "ai-architect",
    max_findings: 5,
  };

  process.stderr.write(`[cortex] Pipeline start: ${JSON.stringify(args, null, 2)}\n`);

  try {
    const result = await runPipeline.handler(args);
    process.stdout.write(JSON.stringify(result, null, 2) + "\n");

    if (result.status === "error") {
      process.stderr.write(`\n[cortex] FAILED at stage "${result.failed_stage}": ${result.error}\n`);
      process.exit(1);
    }

    process.stderr.write(`\n[cortex] DELIVERED — PR: ${result.pr}\n`);
    process.stderr.write(`  Branch: ${result.branch}\n`);
    process.stderr.write(`  Files: ${result.implemented_files} source, ${result.prd_files} PRD\n`);
    process.stderr.write(`  HOR: ${result.hor}\n`);
    process.stderr.write(`  Audit: ${result.audit?.rules} rules, ${result.audit?.flags} flags\n`);
    process.stderr.write(`  Tool calls: ${result.tool_calls}\n`);
  } catch (err) {
    process.stderr.write(`\n[cortex] FATAL: ${err.message}\n${err.stack}\n`);
    process.exit(2);
  }
}

main();
