// Cortex Native App — Tauri shell around the Cortex HTTP server.
// Spawns the existing Python server as a child process, waits for it
// to be ready, then loads it in the WebView. No IPC complexity.
// All tabs, all visualization, all functionality — wrapped as .app.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::{Child, Command};
use std::time::{Duration, Instant};
use std::thread;
use std::path::PathBuf;

const PORT: u16 = 3458;
const SERVER_URL: &str = "http://127.0.0.1:3458";

fn find_cortex_root() -> Option<PathBuf> {
    // Check common locations for the Cortex repo
    let home = dirs::home_dir().unwrap_or_default();
    let candidates = vec![
        home.join("Developments/Cortex"),
        home.join("Documents/Developments/Cortex"),
        home.join("Developer/Cortex"),
        home.join("Projects/Cortex"),
        std::env::current_dir().ok().unwrap_or_default(),
    ];
    candidates.into_iter().find(|p| p.join("mcp_server").is_dir())
}

fn find_uv() -> Option<PathBuf> {
    let home = dirs::home_dir().unwrap_or_default();
    let candidates = vec![
        PathBuf::from("/usr/local/bin/uv"),
        PathBuf::from("/opt/homebrew/bin/uv"),
        home.join(".cargo/bin/uv"),
        home.join(".local/bin/uv"),
    ];
    candidates.into_iter().find(|p| p.exists())
}

fn kill_existing_server() {
    // Kill any process holding port 3458
    let _ = Command::new("lsof")
        .args(["-ti", &format!(":{}", PORT)])
        .output()
        .map(|out| {
            let pids = String::from_utf8_lossy(&out.stdout);
            for pid in pids.split_whitespace() {
                if let Ok(p) = pid.trim().parse::<u32>() {
                    let _ = Command::new("kill").args(["-9", &p.to_string()]).status();
                }
            }
        });
    thread::sleep(Duration::from_millis(300));
}

fn spawn_server(cortex_root: &PathBuf) -> Option<Child> {
    let uv = find_uv()?;
    let server_script = cortex_root.join("mcp_server/server/http_standalone.py");
    if !server_script.exists() {
        eprintln!("[cortex] server script not found: {}", server_script.display());
        return None;
    }

    eprintln!("[cortex] spawning server: {} run python3 {} --type unified --port {}",
        uv.display(), server_script.display(), PORT);

    Command::new(&uv)
        .args(["run", "python3",
               server_script.to_str().unwrap(),
               "--type", "unified",
               "--port", &PORT.to_string()])
        .current_dir(cortex_root)
        .env("CORTEX_IDLE_TIMEOUT", "86400")  // 24h — never times out
        .spawn()
        .map_err(|e| eprintln!("[cortex] spawn error: {}", e))
        .ok()
}

fn wait_for_server(timeout_secs: u64) -> bool {
    let deadline = Instant::now() + Duration::from_secs(timeout_secs);
    while Instant::now() < deadline {
        if let Ok(resp) = ureq::get(SERVER_URL).call() {
            if resp.status() == 200 {
                eprintln!("[cortex] server ready at {}", SERVER_URL);
                return true;
            }
        }
        thread::sleep(Duration::from_millis(300));
    }
    false
}

fn main() {
    let cortex_root = match find_cortex_root() {
        Some(p) => { eprintln!("[cortex] root: {}", p.display()); p }
        None => {
            eprintln!("[cortex] ERROR: Cortex repo not found");
            // Still launch the app — it will show an error page
            tauri::Builder::default()
                .run(tauri::generate_context!())
                .expect("error running Cortex");
            return;
        }
    };

    kill_existing_server();
    let _child = spawn_server(&cortex_root);

    // Wait up to 30s for the server to be ready
    let ready = wait_for_server(30);
    if !ready {
        eprintln!("[cortex] WARNING: server did not start within 30s");
    }

    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error running Cortex");
}
