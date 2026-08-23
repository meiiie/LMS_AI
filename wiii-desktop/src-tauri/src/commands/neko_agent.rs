//! Tauri boundary for the in-process Neko Runtime Authority.
//!
//! The privileged WebView supplies provider/session intent only. Executable
//! resolution, launch arguments, process ownership, request idempotency and
//! durable lifecycle facts stay inside `NekoRuntime`.

use crate::neko::journal::{ReplayPage, SessionRecord};
use crate::neko::provider::{AgentInfo, AgentProfile};
use crate::neko::runtime::{
    unknown_outcome_error, NekoRuntime, SessionCancelRequest, SessionCancelResult,
    SessionStartRequest, SessionStartResult, SessionWriteRequest,
};
use tauri::{AppHandle, State};

#[tauri::command]
pub async fn neko_control_provider_list(
    runtime: State<'_, NekoRuntime>,
) -> Result<Vec<AgentInfo>, String> {
    let runtime = runtime.inner().clone();
    tauri::async_runtime::spawn_blocking(move || runtime.list_providers())
        .await
        .map_err(|error| format!("Neko provider discovery task failed: {error}"))
}

#[tauri::command]
pub async fn neko_control_provider_profiles(
    runtime: State<'_, NekoRuntime>,
    provider_id: String,
    cwd: String,
) -> Result<Vec<AgentProfile>, String> {
    let runtime = runtime.inner().clone();
    tauri::async_runtime::spawn_blocking(move || runtime.list_profiles(&provider_id, &cwd))
        .await
        .map_err(|error| format!("Neko provider profile task failed: {error}"))?
}

#[tauri::command]
pub async fn neko_control_session_list(
    app: AppHandle,
    runtime: State<'_, NekoRuntime>,
    run_id: Option<String>,
) -> Result<Vec<SessionRecord>, String> {
    let runtime = runtime.inner().clone();
    tauri::async_runtime::spawn_blocking(move || runtime.list_sessions(&app, run_id.as_deref()))
        .await
        .map_err(|error| format!("Neko session list task failed: {error}"))?
}

#[tauri::command]
pub async fn neko_control_session_start(
    app: AppHandle,
    runtime: State<'_, NekoRuntime>,
    request: SessionStartRequest,
) -> Result<SessionStartResult, String> {
    let runtime = runtime.inner().clone();
    tauri::async_runtime::spawn_blocking(move || runtime.start_session(app, request))
        .await
        .map_err(|error| {
            unknown_outcome_error(format!("Neko session start task failed: {error}"))
        })?
}

#[tauri::command]
pub async fn neko_control_session_write(
    runtime: State<'_, NekoRuntime>,
    request: SessionWriteRequest,
) -> Result<(), String> {
    let runtime = runtime.inner().clone();
    tauri::async_runtime::spawn_blocking(move || runtime.write_session(request))
        .await
        .map_err(|error| format!("Neko session write task failed: {error}"))?
}

#[tauri::command]
pub async fn neko_control_session_cancel(
    app: AppHandle,
    runtime: State<'_, NekoRuntime>,
    request: SessionCancelRequest,
) -> Result<SessionCancelResult, String> {
    let runtime = runtime.inner().clone();
    tauri::async_runtime::spawn_blocking(move || runtime.cancel_session(&app, request))
        .await
        .map_err(|error| format!("Neko session cancel task failed: {error}"))?
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
