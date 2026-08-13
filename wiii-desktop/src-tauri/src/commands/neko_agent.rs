//! Neko Chill agent transport — a dumb, robust pipe (spec #886, plan § 1).
//!
//! Owns process lifecycle ONLY: detect, spawn, stdin writes, stdout line
//! events, kill. The ACP JSON-RPC protocol lives entirely in TypeScript
//! (`src/neko-chill/drivers/acp/`); Rust never parses agent payloads.
//!
//! Fail-closed discipline (FR-009): every spawned process is registered in
//! a global table; `kill_all` runs on app exit so no agent outlives Wiii.

use serde::Serialize;
use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex, MutexGuard, OnceLock};
use tauri::{AppHandle, Emitter};

struct AgentProc {
    child: Child,
    stdin: ChildStdin,
}

static NEXT_ID: AtomicU64 = AtomicU64::new(1);

fn table() -> &'static Mutex<HashMap<u64, AgentProc>> {
    static TABLE: OnceLock<Mutex<HashMap<u64, AgentProc>>> = OnceLock::new();
    TABLE.get_or_init(|| Mutex::new(HashMap::new()))
}

/// Lock that survives a poisoned mutex — `kill_all` runs on exit paths and
/// must never panic.
fn lock_table() -> MutexGuard<'static, HashMap<u64, AgentProc>> {
    table()
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

fn hidden(cmd: &mut Command) -> &mut Command {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    cmd
}

// ---------------------------------------------------------------------------
// Detection
// ---------------------------------------------------------------------------

#[derive(Serialize, Clone)]
pub struct AgentInfo {
    pub id: String,
    pub name: String,
    /// Binary that answered the probe (spawn target), empty when not found.
    pub binary: String,
    pub version: Option<String>,
    pub found: bool,
}

#[derive(Serialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct AgentProfile {
    pub id: String,
    pub provider: String,
    pub model: Option<String>,
    pub active: bool,
}

fn parse_neko_profiles(output: &str) -> Vec<AgentProfile> {
    output
        .lines()
        .filter_map(|line| {
            let trimmed = line.trim_start();
            let (active, body) = if let Some(rest) = trimmed.strip_prefix("* ") {
                (true, rest)
            } else {
                (false, trimmed)
            };
            let (id, details) = body.split_once(':')?;
            let id = id.trim();
            if id.is_empty()
                || id.eq_ignore_ascii_case(
                    "profiles (select with --profile name, neko_profile, or active_profile)",
                )
            {
                return None;
            }
            let mut provider = None;
            let mut model = None;
            for field in details.split_whitespace() {
                if let Some(value) = field.strip_prefix("provider=") {
                    if value != "?" && !value.is_empty() {
                        provider = Some(value.to_string());
                    }
                } else if let Some(value) = field.strip_prefix("model=") {
                    if value != "-" && !value.is_empty() {
                        model = Some(value.to_string());
                    }
                }
            }
            Some(AgentProfile {
                id: id.to_string(),
                provider: provider?,
                model,
                active,
            })
        })
        .collect()
}

/// Read Neko's config-first launch profiles for one selected workspace.
/// This is intentionally a read-only probe; selecting a profile later only
/// adds `--profile <id>` to that ACP process and never rewrites Neko config.
#[tauri::command]
pub fn neko_agent_profiles(program: String, cwd: String) -> Result<Vec<AgentProfile>, String> {
    let cwd_path = std::path::Path::new(&cwd);
    if !cwd_path.is_absolute() || !cwd_path.is_dir() {
        return Err("workspace must be an existing absolute directory".into());
    }
    let mut cmd = Command::new(&program);
    hidden(
        cmd.arg("profiles")
            .current_dir(cwd_path)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::null()),
    );
    let output = cmd
        .output()
        .map_err(|e| format!("profile probe '{program}' failed: {e}"))?;
    if !output.status.success() {
        return Err(format!(
            "profile probe '{program}' exited with {}",
            output.status
        ));
    }
    Ok(parse_neko_profiles(&String::from_utf8_lossy(
        &output.stdout,
    )))
}

/// Try candidate binary names in order; first probe that answers wins.
/// Windows npm shims resolve as `.cmd`, so both spellings are probed.
fn probe(id: &str, name: &str, candidates: &[&str], version_arg: &str) -> AgentInfo {
    for binary in candidates {
        let mut cmd = Command::new(binary);
        hidden(
            cmd.arg(version_arg)
                .stdin(Stdio::null())
                .stdout(Stdio::piped())
                .stderr(Stdio::null()),
        );
        if let Ok(out) = cmd.output() {
            if out.status.success() {
                let version = String::from_utf8_lossy(&out.stdout).trim().to_string();
                return AgentInfo {
                    id: id.into(),
                    name: name.into(),
                    binary: (*binary).into(),
                    version: (!version.is_empty()).then_some(version),
                    found: true,
                };
            }
        }
    }
    AgentInfo {
        id: id.into(),
        name: name.into(),
        binary: String::new(),
        version: None,
        found: false,
    }
}

/// v0 roster (spec FR-003): Gemini CLI is the acceptance reference;
/// `neko` is reserved for neko-core's upcoming `neko acp` server.
#[tauri::command]
pub fn neko_detect_agents() -> Vec<AgentInfo> {
    vec![
        probe(
            "gemini",
            "Gemini CLI",
            if cfg!(windows) {
                &["gemini.cmd", "gemini"]
            } else {
                &["gemini"]
            },
            "--version",
        ),
        probe(
            "neko",
            "Neko Core",
            if cfg!(windows) {
                &["neko.exe", "neko.cmd", "neko"]
            } else {
                &["neko"]
            },
            "--version",
        ),
    ]
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

/// Spawn an agent process. Raw stdout lines stream to the webview as
/// `neko-agent://line/{id}` events; process end emits `neko-agent://exit/{id}`
/// with the exit code (null when unknown).
#[tauri::command]
pub fn neko_spawn_agent(app: AppHandle, program: String, args: Vec<String>) -> Result<u64, String> {
    let mut cmd = Command::new(&program);
    hidden(
        cmd.args(&args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null()),
    );
    let mut child = cmd
        .spawn()
        .map_err(|e| format!("spawn '{program}' failed: {e}"))?;
    let stdin = child.stdin.take().ok_or("agent stdin unavailable")?;
    let stdout = child.stdout.take().ok_or("agent stdout unavailable")?;

    let id = NEXT_ID.fetch_add(1, Ordering::SeqCst);
    lock_table().insert(id, AgentProc { child, stdin });

    std::thread::spawn(move || {
        let reader = BufReader::new(stdout);
        for line in reader.lines() {
            match line {
                Ok(text) => {
                    let _ = app.emit(&format!("neko-agent://line/{id}"), text);
                }
                Err(_) => break,
            }
        }
        // stdout closed → reap the child and notify the webview.
        let code = match lock_table().remove(&id) {
            Some(mut proc_) => proc_.child.wait().ok().and_then(|s| s.code()),
            None => None, // already killed explicitly
        };
        let _ = app.emit(&format!("neko-agent://exit/{id}"), code);
    });

    Ok(id)
}

/// Write one line (a JSON-RPC frame) to the agent's stdin.
#[tauri::command]
pub fn neko_write_stdin(proc_id: u64, line: String) -> Result<(), String> {
    let mut t = lock_table();
    let proc_ = t.get_mut(&proc_id).ok_or("no such agent process")?;
    proc_
        .stdin
        .write_all(line.as_bytes())
        .and_then(|_| proc_.stdin.write_all(b"\n"))
        .and_then(|_| proc_.stdin.flush())
        .map_err(|e| format!("stdin write failed: {e}"))
}

/// Kill the whole process tree — agents spawn their own children
/// (plan § Complexity: Windows tree-kill via taskkill /T).
fn kill_proc(mut proc_: AgentProc) {
    #[cfg(windows)]
    {
        let pid = proc_.child.id();
        let mut cmd = Command::new("taskkill");
        hidden(
            cmd.args(["/T", "/F", "/PID", &pid.to_string()])
                .stdout(Stdio::null())
                .stderr(Stdio::null()),
        );
        let _ = cmd.status();
    }
    let _ = proc_.child.kill();
    let _ = proc_.child.wait();
}

#[tauri::command]
pub fn neko_kill_agent(proc_id: u64) -> Result<(), String> {
    match lock_table().remove(&proc_id) {
        Some(proc_) => {
            kill_proc(proc_);
            Ok(())
        }
        None => Ok(()), // idempotent: already gone
    }
}

#[tauri::command]
pub fn neko_kill_all_agents() {
    kill_all();
}

/// Called from the app-exit hook in `lib.rs` — must never panic (FR-009).
pub fn kill_all() {
    let procs: Vec<AgentProc> = {
        let mut t = lock_table();
        t.drain().map(|(_, p)| p).collect()
    };
    for proc_ in procs {
        kill_proc(proc_);
    }
}

#[cfg(test)]
mod tests {
    use super::parse_neko_profiles;

    #[test]
    fn parses_profile_provider_model_and_active_marker() {
        let output = r#"Profiles (select with --profile NAME, NEKO_PROFILE, or active_profile):
 * chatgpt: provider=chatgpt base_url=https://example.test model=gpt-5.6-luna
   local: provider=openai_compat base_url=http://127.0.0.1:8080/v1 model=local-model
   openrouter: provider=openai_compat base_url=https://openrouter.ai/api/v1 model=-
 malformed line
"#;
        let profiles = parse_neko_profiles(output);
        assert_eq!(profiles.len(), 3);
        assert_eq!(profiles[0].id, "chatgpt");
        assert_eq!(profiles[0].provider, "chatgpt");
        assert_eq!(profiles[0].model.as_deref(), Some("gpt-5.6-luna"));
        assert!(profiles[0].active);
        assert_eq!(profiles[2].model, None);
        assert!(!profiles[2].active);
    }
}
