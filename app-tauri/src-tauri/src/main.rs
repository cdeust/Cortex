// Cortex Native Graph — Tauri + Rust
// Reads CXGB binary snapshot directly from disk. No HTTP server.
// File path: ~/.cache/cortex/graph-snapshot.bin
// Data → IPC → WebView (force-graph D3 renderer, same as browser version)

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]


use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;


use serde::{Deserialize, Serialize};


// ── CXGB format constants (must match graph_snapshot.js) ──────────────────

const MAGIC: [u8; 4] = [0x43, 0x58, 0x47, 0x42]; // "CXGB"
const VERSION: u16 = 1;
const HEADER_SIZE: usize = 64;
const NODE_SIZE: usize = 24;
const EDGE_SIZE: usize = 12;

// Kind byte → string (must match graph_snapshot.js _nodeKind / _edgeKind)
fn node_kind(b: u8) -> &'static str {
    match b {
        1 => "domain",
        2 => "skill",
        3 => "command",
        4 => "hook",
        5 => "agent",
        6 => "mcp",
        7 => "tool_hub",
        8 => "file",
        9 => "discussion",
        10 => "memory",
        11 => "symbol",
        12 => "entity",
        _ => "node",
    }
}

fn edge_kind(b: u8) -> &'static str {
    match b {
        1 => "in_domain",
        2 => "tool_used_file",
        3 => "invoked_skill",
        4 => "triggered_hook",
        5 => "spawned_agent",
        6 => "about_entity",
        7 => "calls",
        8 => "defined_in",
        9 => "imports",
        10 => "member_of",
        11 => "cross_domain",
        _ => "link",
    }
}

fn kind_color(kind: &str) -> &'static str {
    match kind {
        "domain" => "#FCD34D",
        "skill" => "#FB923C",
        "hook" => "#A855F7",
        "agent" => "#EC4899",
        "command" => "#FACC15",
        "mcp" => "#6366F1",
        "tool_hub" => "#F97316",
        "file" => "#06B6D4",
        "discussion" => "#EF4444",
        "memory" => "#10B981",
        "symbol" => "#64748B",
        "entity" => "#50B0C8",
        _ => "#94A3B8",
    }
}

// ── Data types ─────────────────────────────────────────────────────────────

#[derive(Serialize, Clone)]
pub struct GraphNode {
    pub id: String,
    pub kind: String,
    #[serde(rename = "type")]
    pub node_type: String,
    pub label: String,
    pub color: String,
    #[serde(rename = "domain_id")]
    pub domain_id: String,
    pub x: f32,
    pub y: f32,
    pub size: f32,
}

#[derive(Serialize, Clone)]
pub struct GraphEdge {
    pub source: String,
    pub target: String,
    pub kind: String,
    #[serde(rename = "type")]
    pub edge_type: String,
}

#[derive(Serialize)]
pub struct GraphData {
    pub nodes: Vec<GraphNode>,
    pub edges: Vec<GraphEdge>,
    pub node_count: usize,
    pub edge_count: usize,
    pub source: String,
}

// ── CXGB decoder ──────────────────────────────────────────────────────────

fn read_u16_le(data: &[u8], off: usize) -> u16 {
    u16::from_le_bytes([data[off], data[off + 1]])
}

fn read_u32_le(data: &[u8], off: usize) -> u32 {
    u32::from_le_bytes([data[off], data[off + 1], data[off + 2], data[off + 3]])
}

fn read_f32_le(data: &[u8], off: usize) -> f32 {
    f32::from_le_bytes([data[off], data[off + 1], data[off + 2], data[off + 3]])
}

fn read_string(data: &[u8], pool_off: usize, str_off: usize) -> String {
    let abs = pool_off + str_off;
    if abs + 2 > data.len() {
        return String::new();
    }
    let len = read_u16_le(data, abs) as usize;
    if abs + 2 + len > data.len() {
        return String::new();
    }
    String::from_utf8_lossy(&data[abs + 2..abs + 2 + len]).into_owned()
}

fn decode_cxgb(data: &[u8]) -> Result<GraphData, String> {
    if data.len() < HEADER_SIZE {
        return Err(format!("snapshot too small: {} bytes", data.len()));
    }
    if &data[0..4] != &MAGIC {
        return Err("bad magic — not a CXGB snapshot".to_string());
    }
    let ver = read_u16_le(data, 4);
    if ver != VERSION {
        return Err(format!("unsupported version: {}", ver));
    }

    let node_count = read_u32_le(data, 8) as usize;
    let edge_count = read_u32_le(data, 12) as usize;
    let pool_off = read_u32_le(data, 16) as usize;

    let mut nodes = Vec::with_capacity(node_count);
    for ni in 0..node_count {
        let base = HEADER_SIZE + ni * NODE_SIZE;
        let id_off = read_u32_le(data, base) as usize;
        let kind_b = data[base + 4];
        let dom_off = read_u32_le(data, base + 8) as usize;
        let x = read_f32_le(data, base + 12);
        let y = read_f32_le(data, base + 16);
        let size = read_f32_le(data, base + 20);

        let id = read_string(data, pool_off, id_off);
        let kind = node_kind(kind_b).to_string();
        let domain_id = read_string(data, pool_off, dom_off);

        // Derive label from id (strip prefix)
        let label = id.split(':').last().unwrap_or(&id).to_string();
        let color = kind_color(&kind).to_string();

        // Skip global sentinel
        if id == "domain:__global__" {
            continue;
        }

        nodes.push(GraphNode {
            id,
            node_type: kind.clone(),
            kind,
            label,
            color,
            domain_id,
            x,
            y,
            size: if size <= 0.0 { 5.0 } else { size },
        });
    }

    let edge_base = HEADER_SIZE + node_count * NODE_SIZE;
    let mut edges = Vec::with_capacity(edge_count);
    for ei in 0..edge_count {
        let base = edge_base + ei * EDGE_SIZE;
        let src_off = read_u32_le(data, base) as usize;
        let tgt_off = read_u32_le(data, base + 4) as usize;
        let ek = data[base + 8];

        let source = read_string(data, pool_off, src_off);
        let target = read_string(data, pool_off, tgt_off);
        let kind = edge_kind(ek).to_string();

        edges.push(GraphEdge {
            source,
            target,
            edge_type: kind.clone(),
            kind,
        });
    }

    let n = nodes.len();
    let e = edges.len();
    Ok(GraphData {
        nodes,
        edges,
        node_count: n,
        edge_count: e,
        source: "CXGB snapshot (direct disk read)".to_string(),
    })
}

// ── Snapshot path discovery ────────────────────────────────────────────────

fn snapshot_paths() -> Vec<PathBuf> {
    let home = dirs::home_dir().unwrap_or_default();
    vec![
        home.join(".cache/cortex/graph-snapshot.bin"),
        home.join("Library/Caches/cortex/graph-snapshot.bin"),
        PathBuf::from("/tmp/cortex-graph-snapshot.bin"),
    ]
}

// ── Tauri commands ─────────────────────────────────────────────────────────

#[tauri::command]
fn load_graph() -> Result<GraphData, String> {
    for path in snapshot_paths() {
        if path.exists() {
            let data = fs::read(&path)
                .map_err(|e| format!("read {}: {}", path.display(), e))?;
            let result = decode_cxgb(&data)
                .map_err(|e| format!("decode {}: {}", path.display(), e))?;
            eprintln!(
                "[cortex] Loaded {} nodes, {} edges from {}",
                result.node_count,
                result.edge_count,
                path.display()
            );
            return Ok(result);
        }
    }
    Err(format!(
        "No snapshot found. Run the Cortex MCP server once to build it.\nLooked in: {:?}",
        snapshot_paths()
    ))
}

#[tauri::command]
fn get_snapshot_info() -> HashMap<String, String> {
    let mut info = HashMap::new();
    for path in snapshot_paths() {
        if path.exists() {
            if let Ok(meta) = fs::metadata(&path) {
                info.insert("path".to_string(), path.display().to_string());
                info.insert("size_bytes".to_string(), meta.len().to_string());
                info.insert("exists".to_string(), "true".to_string());
                return info;
            }
        }
    }
    info.insert("exists".to_string(), "false".to_string());
    info
}

// ── Main ───────────────────────────────────────────────────────────────────

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![load_graph, get_snapshot_info])
        .run(tauri::generate_context!())
        .expect("error while running Cortex");
}
