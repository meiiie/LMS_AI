//! Tauri boundary for the in-process Neko Runtime Authority.
//!
//! The privileged WebView supplies provider/session intent only. Executable
//! resolution, launch arguments, process ownership, request idempotency and
//! durable lifecycle facts stay inside `NekoRuntime`.

use crate::neko::journal::{ReplayPage, SessionRecord};
use crate::neko::provider::{AgentInfo, AgentProfile};
use crate::neko::runtime::{
    NekoRuntime, SessionCancelRequest, SessionCancelResult, SessionStartRequest,
    SessionStartResult, SessionWriteRequest,
};
use tauri::{AppHandle, State};

#[tauri::command]
pub fn neko_control_provider_list(runtime: State<'_, NekoRuntime>) -> Vec<AgentInfo> {
    runtime.list_providers()
}

#[tauri::command]
pub fn neko_control_provider_profiles(
    runtime: State<'_, NekoRuntime>,
    provider_id: String,
    cwd: String,
) -> Result<Vec<AgentProfile>, String> {
    runtime.list_profiles(&provider_id, &cwd)
}

#[tauri::command]
pub fn neko_control_session_list(
    runtime: State<'_, NekoRuntime>,
    run_id: Option<String>,
) -> Result<Vec<SessionRecord>, String> {
    runtime.list_sessions(run_id.as_deref())
}

#[tauri::command]
pub fn neko_control_session_start(
    app: AppHandle,
    runtime: State<'_, NekoRuntime>,
    request: SessionStartRequest,
) -> Result<SessionStartResult, String> {
    runtime.start_session(app, request)
}

#[tauri::command]
pub fn neko_control_session_write(
    runtime: State<'_, NekoRuntime>,
    request: SessionWriteRequest,
) -> Result<(), String> {
    runtime.write_session(request)
}

#[tauri::command]
pub fn neko_control_session_cancel(
    app: AppHandle,
    runtime: State<'_, NekoRuntime>,
    request: SessionCancelRequest,
) -> Result<SessionCancelResult, String> {
    runtime.cancel_session(&app, request)
}

#[tauri::command]
pub fn neko_control_events_read(
    runtime: State<'_, NekoRuntime>,
    stream_id: String,
    after_seq: u64,
    limit: u32,
) -> Result<ReplayPage, String> {
    runtime.replay_events(&stream_id, after_seq, limit)
}
