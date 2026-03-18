#!/usr/bin/env node
/**
 * Launch the pollen-allergy desensitization neural graph in the JARVIS 3D visualizer.
 *
 * Usage: node scripts/launch-medical-graph.js
 */

"use strict";

const { buildMedicalGraph } = require("./medical-graph-builder");
const { startUIServer, shutdownServer } = require("../mcp-server/server/http-server");
const { execSync } = require("child_process");

async function main() {
  const graph = buildMedicalGraph();

  console.log("╔══════════════════════════════════════════════════════════╗");
  console.log("║  J.A.R.V.I.S. — Medical Knowledge Graph                ║");
  console.log("║  Pollen → Antihistamine → Desensitization               ║");
  console.log("╚══════════════════════════════════════════════════════════╝");
  console.log("");
  console.log(`  Nodes:       ${graph.nodes.length}`);
  console.log(`  Edges:       ${graph.edges.length}`);
  console.log(`  Blind Spots: ${graph.blindSpotRegions.length}`);
  console.log("");

  const types = {};
  for (const n of graph.nodes) types[n.type] = (types[n.type] || 0) + 1;
  console.log("  Node breakdown:");
  console.log(`    System hubs (cyan):      ${types["domain"] || 0}`);
  console.log(`    Allergens (green):       ${types["entry-point"] || 0}`);
  console.log(`    Immune components (blue): ${types["recurring-pattern"] || 0}`);
  console.log(`    Drugs & protocols (amber): ${types["tool-preference"] || 0}`);
  console.log(`    Biomarkers (purple):     ${types["behavioral-feature"] || 0}`);
  console.log(`    Failure modes (gray):    ${types["blind-spot"] || 0}`);
  console.log("");

  const url = await startUIServer(graph);
  console.log(`  → Visualization: ${url}`);
  console.log("  → Auto-shutdown after 10 min idle");
  console.log("");

  try {
    execSync(`open "${url}"`, { stdio: "ignore" });
    console.log("  Browser opened.");
  } catch (_) {
    try {
      execSync(`xdg-open "${url}"`, { stdio: "ignore" });
    } catch (_) {
      console.log("  Open the URL above in your browser.");
    }
  }

  // Keep alive
  process.on("SIGINT", () => {
    shutdownServer();
    process.exit(0);
  });
}

main().catch((err) => {
  console.error("Error:", err.message);
  process.exit(1);
});
