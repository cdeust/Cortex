/**
 * subgraph.js — Public façade for the chain-panel.
 *
 * Spec: docs/02-sub-graph-drill-down.md
 *
 * boot.js calls openSubgraph() on node click.
 * All logic lives in chain-panel.js; this module is the thin wiring shim
 * that receives the getGraph factory from boot.js and forwards calls.
 */

import * as chainPanel from "./chain-panel.js";

/**
 * Initialise the chain panel module.
 * Must be called once from boot.js with the graphology graph accessor.
 * @param {{ getGraph: () => any|null }} options
 */
export function init(options) {
  chainPanel.init(options);
}

/**
 * Open the chain panel for a node (called by boot.js on node click).
 * @param {string} nodeId
 * @param {"causal"|"impact"|"call"} [tab]
 */
export function openSubgraph(nodeId, tab) {
  chainPanel.openNode(nodeId, tab);
}

/**
 * Close the chain panel.
 */
export function closeSubgraph() {
  chainPanel.closePanel();
}

/**
 * Switch tab on the current node without pushing to history.
 * @param {"causal"|"impact"|"call"} tab
 */
export function switchTab(tab) {
  chainPanel.switchTab(tab);
}

/**
 * Navigate back one step in the panel history.
 */
export function panelBack() {
  chainPanel.panelBack();
}

/**
 * Return the currently focused node ID, or null.
 * @returns {string|null}
 */
export function currentNodeId() {
  return chainPanel.currentNodeId();
}
