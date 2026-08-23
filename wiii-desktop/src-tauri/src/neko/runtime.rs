use super::journal::{Journal, NewSession, ReplayPage, RequestDecision, SessionRecord};
use super::lifecycle::{OperationPhase, RunState};
use super::provider::{self, hidden, AgentInfo, AgentProfile};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::fs::{File, OpenOptions};
use std::io::{self, BufRead, BufReader, Write};
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::mpsc::{channel, sync_channel, SyncSender, TrySendError};
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::Duration;
use tauri::{AppHandle, Emitter};

const WRITER_QUEUE_CAPACITY: usize = 32;
const WRITE_RESULT_TIMEOUT: Duration = Duration::from_secs(5);

struct WriteJob {
    line: String,
    result: std::sync::mpsc::Sender<io::Result<()>>,
}

struct AgentProc {
    child: Child,
    writer: SyncSender<WriteJob>,
}

struct RuntimeInner {
    journal: Journal,
    processes: Mutex<HashMap<String, AgentProc>>,
    operations: Mutex<()>,
    _lease: File,
}

#[derive(Clone)]
pub struct NekoRuntime {
    inner: Arc<RuntimeInner>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SessionStartRequest {
    pub request_id: String,
    pub agent_session_id: String,
    pub task_id: String,
    pub run_id: String,
    pub provider_id: String,
    pub environment_id: String,
    pub workspace_path: String,
    pub profile_id: Option<String>,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SessionStartResult {
    pub agent_session_id: String,
    pub run_id: String,
    pub provider: AgentInfo,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SessionWriteRequest {
    pub request_id: String,
    pub agent_session_id: String,
    pub line: String,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SessionCancelRequest {
    pub request_id: String,
    pub run_id: String,
    pub agent_session_id: String,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SessionCancelResult {
    pub agent_session_id: String,
    pub cancelled: bool,
}

impl NekoRuntime {
    pub fn open(path: &Path) -> Result<Self, String> {
        let lease_path = path.with_extension("sqlite3.lock");
        if let Some(parent) = lease_path.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|error| format!("create Neko data directory failed: {error}"))?;
        }
        let lease = OpenOptions::new()
            .create(true)
            .read(true)
            .write(true)
            .truncate(false)
            .open(&lease_path)
            .map_err(|error| format!("open Neko runtime lease failed: {error}"))?;
        lease
            .try_lock()
            .map_err(|_| "another Neko runtime already owns this local journal".to_string())?;
        Ok(Self {
            inner: Arc::new(RuntimeInner {
                journal: Journal::open(path)?,
                processes: Mutex::new(HashMap::new()),
                operations: Mutex::new(()),
                _lease: lease,
            }),
        })
    }

    pub fn list_providers(&self) -> Vec<AgentInfo> {
        provider::list()
    }

    pub fn list_profiles(&self, provider_id: &str, cwd: &str) -> Result<Vec<AgentProfile>, String> {
        provider::profiles(provider_id, cwd)
    }

    pub fn list_sessions(&self, run_id: Option<&str>) -> Result<Vec<SessionRecord>, String> {
        self.inner.journal.sessions(run_id)
    }

    pub fn replay_events(
        &self,
        stream_id: &str,
        after_seq: u64,
        limit: u32,
    ) -> Result<ReplayPage, String> {
        validate_identity("streamId", stream_id)?;
        if !(1..=500).contains(&limit) {
            return Err("Neko replay limit must be between 1 and 500".to_string());
        }
        if after_seq > i64::MAX as u64 {
            return Err("Neko replay cursor exceeds the durable sequence range".to_string());
        }
        self.inner.journal.replay(stream_id, after_seq, limit)
    }

    pub fn start_session(
        &self,
        app: AppHandle,
        request: SessionStartRequest,
    ) -> Result<SessionStartResult, String> {
        validate_start(&request)?;
        let _operation = lock(&self.inner.operations);
        let target = digest_target(&[
            &request.agent_session_id,
            &request.task_id,
            &request.run_id,
            &request.provider_id,
            &request.environment_id,
            &request.workspace_path,
            request.profile_id.as_deref().unwrap_or(""),
        ]);
        match self
            .inner
            .journal
            .begin_request(&request.request_id, "session/start", &target)?
        {
            RequestDecision::Replay(value) => {
                return serde_json::from_value(value)
                    .map_err(|error| format!("decode recorded session start failed: {error}"));
            }
            RequestDecision::RecordedError(code) => {
                return Err(format!("recorded session start failed: {code}"));
            }
            RequestDecision::UnknownOutcome => {
                return Err(
                    "session start has unknown_outcome; automatic replay is forbidden".into(),
                );
            }
            RequestDecision::Execute => {}
        }

        let created = self.inner.journal.insert_session_with_event(
            NewSession {
                agent_session_id: &request.agent_session_id,
                task_id: &request.task_id,
                run_id: &request.run_id,
                environment_id: &request.environment_id,
                provider_id: &request.provider_id,
                workspace_path: &request.workspace_path,
            },
            "session.created",
            json!({ "providerId": request.provider_id }),
        );
        match created {
            Ok(event) => {
                let _ = app.emit("neko-control://event", event);
            }
            Err(error) => {
                let _ = self
                    .inner
                    .journal
                    .fail_request(&request.request_id, "invalid_state");
                return Err(error);
            }
        }

        if let Err(error) = self.advance_start_phase(&request, OperationPhase::Dispatched) {
            return Err(self.reject_start_error(&app, &request, "journal_error", None, error));
        }

        let resolved = match provider::resolve(&request.provider_id) {
            Ok(resolved) => resolved,
            Err(error) => {
                return Err(self.reject_start_error(
                    &app,
                    &request,
                    "provider_unavailable",
                    None,
                    error,
                ));
            }
        };
        let args = match resolved
            .definition
            .launch_args(request.profile_id.as_deref())
        {
            Ok(args) => args,
            Err(error) => {
                return Err(self.reject_start_error(
                    &app,
                    &request,
                    "invalid_request",
                    resolved.version.as_deref(),
                    error,
                ));
            }
        };

        if let Err(error) = self.advance_start_phase(&request, OperationPhase::SideEffectStarted) {
            return Err(self.reject_start_error(
                &app,
                &request,
                "journal_error",
                resolved.version.as_deref(),
                error,
            ));
        }

        let mut command = Command::new(&resolved.program);
        hidden(
            command
                .args(&args)
                .current_dir(&request.workspace_path)
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::null()),
        );
        let mut child = match command.spawn() {
            Ok(child) => child,
            Err(error) => {
                return Err(self.reject_start_error(
                    &app,
                    &request,
                    "provider_unavailable",
                    resolved.version.as_deref(),
                    format!("spawn approved provider failed: {error}"),
                ));
            }
        };
        let stdin = child.stdin.take();
        let stdout = child.stdout.take();
        let (stdin, stdout) = match (stdin, stdout) {
            (Some(stdin), Some(stdout)) => (stdin, stdout),
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                let _ = self.inner.journal.mark_request_unknown(&request.request_id);
                let _ = self.transition_session_event(
                    &app,
                    &request.agent_session_id,
                    RunState::UnknownOutcome,
                    OperationPhase::UnknownOutcome,
                    "unknown_outcome",
                    None,
                    resolved.version.as_deref(),
                    "run.state_changed",
                    json!({ "state": "unknown_outcome", "reason": "provider_stdio_unavailable" }),
                );
                return Err(
                    "provider stdio became unavailable after spawn; outcome is unknown".into(),
                );
            }
        };
        let pid = child.id();
        let writer = spawn_writer(stdin);
        lock(&self.inner.processes).insert(
            request.agent_session_id.clone(),
            AgentProc { child, writer },
        );

        let result = SessionStartResult {
            agent_session_id: request.agent_session_id.clone(),
            run_id: request.run_id.clone(),
            provider: AgentInfo {
                id: resolved.definition.id.to_string(),
                name: resolved.definition.name.to_string(),
                version: resolved.version.clone(),
                found: true,
                supports_profiles: resolved.definition.supports_profiles(),
            },
        };
        let ownership_commit = (|| -> Result<(), String> {
            self.transition_session_event(
                &app,
                &request.agent_session_id,
                RunState::Running,
                OperationPhase::Committed,
                "active",
                Some(pid),
                resolved.version.as_deref(),
                "run.state_changed",
                json!({ "state": "running" }),
            )?;
            self.inner
                .journal
                .set_request_phase(&request.request_id, OperationPhase::Committed)?;
            self.emit_control_event(
                &app,
                &request.run_id,
                "session.started",
                &request.agent_session_id,
                json!({ "providerId": result.provider.id, "providerVersion": result.provider.version }),
            )?;
            self.inner.journal.complete_request(
                &request.request_id,
                &serde_json::to_value(&result)
                    .map_err(|error| format!("encode session start result failed: {error}"))?,
            )?;
            Ok(())
        })();
        if let Err(error) = ownership_commit {
            if let Some(process) = lock(&self.inner.processes).remove(&request.agent_session_id) {
                kill_proc(process);
            }
            let _ = self.inner.journal.mark_request_unknown(&request.request_id);
            let _ = self.transition_session_event(
                &app,
                &request.agent_session_id,
                RunState::UnknownOutcome,
                OperationPhase::UnknownOutcome,
                "unknown_outcome",
                None,
                resolved.version.as_deref(),
                "run.state_changed",
                json!({ "state": "unknown_outcome", "reason": "ownership_commit_failed" }),
            );
            return Err(format!(
                "provider spawned but ownership commit failed: {error}"
            ));
        }

        let runtime = self.clone();
        let session_id = request.agent_session_id;
        std::thread::spawn(move || {
            for line in BufReader::new(stdout).lines() {
                match line {
                    Ok(line) => {
                        let _ = app.emit(&format!("neko-session://line/{session_id}"), line);
                    }
                    Err(_) => break,
                }
            }
            let code = runtime.finish_process(&app, &session_id);
            let _ = app.emit(&format!("neko-session://exit/{session_id}"), code);
        });

        Ok(result)
    }

    pub fn write_session(&self, request: SessionWriteRequest) -> Result<(), String> {
        validate_identity("requestId", &request.request_id)?;
        validate_identity("agentSessionId", &request.agent_session_id)?;
        if request.line.is_empty() || request.line.len() > 1024 * 1024 {
            return Err("provider frame must be between 1 byte and 1 MiB".into());
        }
        let target = digest_target(&[&request.agent_session_id, &request.line]);
        let writer = {
            let _operation = lock(&self.inner.operations);
            match self
                .inner
                .journal
                .begin_request(&request.request_id, "session/write", &target)?
            {
                RequestDecision::Replay(_) => return Ok(()),
                RequestDecision::RecordedError(code) => {
                    return Err(format!("recorded session write failed: {code}"));
                }
                RequestDecision::UnknownOutcome => {
                    return Err(
                        "session write has unknown_outcome; automatic replay is forbidden".into(),
                    );
                }
                RequestDecision::Execute => {}
            }
            self.inner
                .journal
                .set_request_phase(&request.request_id, OperationPhase::Dispatched)?;
            let writer = lock(&self.inner.processes)
                .get(&request.agent_session_id)
                .map(|process| process.writer.clone());
            let Some(writer) = writer else {
                self.inner
                    .journal
                    .fail_request(&request.request_id, "invalid_state")?;
                return Err("no live provider process for this agent session".into());
            };
            self.inner
                .journal
                .set_request_phase(&request.request_id, OperationPhase::SideEffectStarted)?;
            writer
        };

        // Never hold the global lifecycle lock during provider I/O. Each
        // session has a bounded writer queue, so one stalled provider cannot
        // freeze cancellation, shutdown, or unrelated sessions.
        let (result_tx, result_rx) = channel();
        match writer.try_send(WriteJob {
            line: request.line,
            result: result_tx,
        }) {
            Ok(()) => {}
            Err(TrySendError::Full(_)) => {
                let _operation = lock(&self.inner.operations);
                self.inner
                    .journal
                    .fail_request(&request.request_id, "provider_busy")?;
                return Err(
                    "provider_busy: provider stdin queue is full; retry with a new request identity"
                        .into(),
                );
            }
            Err(TrySendError::Disconnected(_)) => {
                let _operation = lock(&self.inner.operations);
                self.inner
                    .journal
                    .fail_request(&request.request_id, "invalid_state")?;
                return Err("provider stdin is no longer available".into());
            }
        }
        let result = result_rx.recv_timeout(WRITE_RESULT_TIMEOUT);
        let _operation = lock(&self.inner.operations);
        match result {
            Ok(Ok(())) => {}
            Ok(Err(error)) => {
                self.inner
                    .journal
                    .mark_request_unknown(&request.request_id)?;
                return Err(format!(
                    "provider stdin write failed after dispatch; outcome is unknown: {error}"
                ));
            }
            Err(error) => {
                self.inner
                    .journal
                    .mark_request_unknown(&request.request_id)?;
                return Err(format!(
                    "provider stdin acknowledgement was lost; outcome is unknown: {error}"
                ));
            }
        }
        self.inner
            .journal
            .set_request_phase(&request.request_id, OperationPhase::Committed)?;
        self.inner
            .journal
            .complete_request(&request.request_id, &json!({ "written": true }))?;
        Ok(())
    }

    pub fn cancel_session(
        &self,
        app: &AppHandle,
        request: SessionCancelRequest,
    ) -> Result<SessionCancelResult, String> {
        validate_identity("requestId", &request.request_id)?;
        validate_identity("runId", &request.run_id)?;
        validate_identity("agentSessionId", &request.agent_session_id)?;
        let _operation = lock(&self.inner.operations);
        let target = digest_target(&[&request.run_id, &request.agent_session_id]);
        match self
            .inner
            .journal
            .begin_request(&request.request_id, "session/cancel", &target)?
        {
            RequestDecision::Replay(value) => {
                return serde_json::from_value(value)
                    .map_err(|error| format!("decode recorded session cancel failed: {error}"));
            }
            RequestDecision::RecordedError(code) => {
                return Err(format!("recorded session cancel failed: {code}"));
            }
            RequestDecision::UnknownOutcome => {
                return Err(
                    "session cancellation has unknown_outcome; automatic replay is forbidden"
                        .into(),
                );
            }
            RequestDecision::Execute => {}
        }
        let session = match self.inner.journal.session(&request.agent_session_id)? {
            Some(session) => session,
            None => {
                self.inner
                    .journal
                    .fail_request(&request.request_id, "invalid_state")?;
                return Err("no such Neko agent session".to_string());
            }
        };
        if session.run_id != request.run_id {
            self.inner
                .journal
                .fail_request(&request.request_id, "invalid_request")?;
            return Err("agent session does not belong to the requested run".into());
        }
        self.inner
            .journal
            .set_request_phase(&request.request_id, OperationPhase::Dispatched)?;
        self.inner
            .journal
            .set_request_phase(&request.request_id, OperationPhase::SideEffectStarted)?;
        let process = lock(&self.inner.processes).remove(&request.agent_session_id);
        if let Some(process) = process {
            kill_proc(process);
        }
        self.inner
            .journal
            .set_request_phase(&request.request_id, OperationPhase::Committed)?;
        let cancelled = !session.state.is_terminal();
        if cancelled {
            self.transition_session_event(
                app,
                &request.agent_session_id,
                RunState::Cancelled,
                OperationPhase::Completed,
                "active",
                None,
                None,
                "run.state_changed",
                json!({ "state": "cancelled", "reason": "requested" }),
            )?;
        }
        let result = SessionCancelResult {
            agent_session_id: request.agent_session_id,
            cancelled,
        };
        self.inner.journal.complete_request(
            &request.request_id,
            &serde_json::to_value(&result)
                .map_err(|error| format!("encode session cancel result failed: {error}"))?,
        )?;
        Ok(result)
    }

    pub fn kill_all(&self, app: &AppHandle) {
        let _operation = lock(&self.inner.operations);
        let processes = {
            let mut processes = lock(&self.inner.processes);
            processes.drain().collect::<Vec<_>>()
        };
        for (agent_session_id, process) in processes {
            kill_proc(process);
            if let Ok(Some(session)) = self.inner.journal.session(&agent_session_id) {
                if !session.state.is_terminal() {
                    let _ = self.transition_session_event(
                        app,
                        &agent_session_id,
                        RunState::Cancelled,
                        OperationPhase::Completed,
                        "active",
                        None,
                        None,
                        "run.state_changed",
                        json!({ "state": "cancelled", "reason": "application_exit" }),
                    );
                }
            }
        }
    }

    fn emit_control_event(
        &self,
        app: &AppHandle,
        stream_id: &str,
        event_type: &str,
        agent_session_id: &str,
        payload: Value,
    ) -> Result<(), String> {
        let event = self.inner.journal.append_event(
            stream_id,
            event_type,
            stream_id,
            Some(agent_session_id),
            payload,
        )?;
        // The journal is authoritative. A temporarily unavailable WebView can
        // replay later, so renderer delivery must not roll back native truth.
        let _ = app.emit("neko-control://event", event);
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    fn transition_session_event(
        &self,
        app: &AppHandle,
        agent_session_id: &str,
        next_state: RunState,
        phase: OperationPhase,
        continuity: &str,
        pid: Option<u32>,
        provider_version: Option<&str>,
        event_type: &str,
        payload: Value,
    ) -> Result<(), String> {
        let event = self.inner.journal.update_session_with_event(
            agent_session_id,
            next_state,
            phase,
            continuity,
            pid,
            provider_version,
            event_type,
            payload,
        )?;
        let _ = app.emit("neko-control://event", event);
        Ok(())
    }

    fn reject_start(
        &self,
        app: &AppHandle,
        request: &SessionStartRequest,
        reason: &str,
        provider_version: Option<&str>,
    ) -> Result<(), String> {
        let mut failures = Vec::new();
        if let Err(error) = self.inner.journal.fail_request(&request.request_id, reason) {
            failures.push(error);
        }
        if let Err(error) = self.transition_session_event(
            app,
            &request.agent_session_id,
            RunState::Failed,
            OperationPhase::Failed,
            "continuity_lost",
            None,
            provider_version,
            "run.state_changed",
            json!({ "state": "failed", "reason": reason }),
        ) {
            failures.push(error);
        }
        if failures.is_empty() {
            Ok(())
        } else {
            Err(failures.join("; "))
        }
    }

    fn reject_start_error(
        &self,
        app: &AppHandle,
        request: &SessionStartRequest,
        reason: &str,
        provider_version: Option<&str>,
        original: String,
    ) -> String {
        match self.reject_start(app, request, reason, provider_version) {
            Ok(()) => original,
            Err(recording_error) => format!(
                "{original}; additionally failed to persist rejected start: {recording_error}"
            ),
        }
    }

    fn advance_start_phase(
        &self,
        request: &SessionStartRequest,
        phase: OperationPhase,
    ) -> Result<(), String> {
        self.inner
            .journal
            .set_request_phase(&request.request_id, phase)?;
        self.inner
            .journal
            .set_session_phase(&request.agent_session_id, phase)
    }

    fn finish_process(&self, app: &AppHandle, agent_session_id: &str) -> Option<i32> {
        let _operation = lock(&self.inner.operations);
        let code = lock(&self.inner.processes)
            .remove(agent_session_id)
            .and_then(|mut process| process.child.wait().ok())
            .and_then(|status| status.code());
        let Ok(Some(session)) = self.inner.journal.session(agent_session_id) else {
            return code;
        };
        if !session.state.is_terminal() {
            let _ = self.transition_session_event(
                app,
                agent_session_id,
                RunState::Failed,
                OperationPhase::Failed,
                "continuity_lost",
                None,
                None,
                "run.state_changed",
                json!({ "state": "failed", "reason": "provider_process_exited" }),
            );
        }
        let _ = self.emit_control_event(
            app,
            &session.run_id,
            "process.exited",
            agent_session_id,
            json!({ "exitCode": code }),
        );
        code
    }
}

fn validate_start(request: &SessionStartRequest) -> Result<(), String> {
    for (name, value) in [
        ("requestId", request.request_id.as_str()),
        ("agentSessionId", request.agent_session_id.as_str()),
        ("taskId", request.task_id.as_str()),
        ("runId", request.run_id.as_str()),
        ("providerId", request.provider_id.as_str()),
        ("environmentId", request.environment_id.as_str()),
    ] {
        validate_identity(name, value)?;
    }
    validate_channel_identity("agentSessionId", &request.agent_session_id)?;
    if provider::definition(&request.provider_id).is_none() {
        return Err(format!("unknown Neko provider '{}'", request.provider_id));
    }
    let workspace = Path::new(&request.workspace_path);
    if !workspace.is_absolute() || !workspace.is_dir() {
        return Err("workspace must be an existing absolute directory".into());
    }
    if let Some(profile_id) = request.profile_id.as_deref() {
        provider::validate_profile_id(profile_id)?;
    }
    Ok(())
}

fn validate_identity(name: &str, value: &str) -> Result<(), String> {
    if value.is_empty() || value.len() > 256 || value.chars().any(char::is_control) {
        return Err(format!("invalid {name}"));
    }
    Ok(())
}

fn validate_channel_identity(name: &str, value: &str) -> Result<(), String> {
    if value.len() > 128
        || !value
            .bytes()
            .all(|item| item.is_ascii_alphanumeric() || matches!(item, b'-' | b'_' | b'.' | b':'))
    {
        return Err(format!("invalid {name} event-channel identity"));
    }
    Ok(())
}

fn digest_target(parts: &[&str]) -> String {
    let mut digest = Sha256::new();
    for part in parts {
        digest.update(part.len().to_le_bytes());
        digest.update(part.as_bytes());
    }
    format!("sha256:{:x}", digest.finalize())
}

fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

fn spawn_writer(mut stdin: std::process::ChildStdin) -> SyncSender<WriteJob> {
    let (sender, receiver) = sync_channel::<WriteJob>(WRITER_QUEUE_CAPACITY);
    std::thread::spawn(move || {
        for job in receiver {
            let result = stdin
                .write_all(job.line.as_bytes())
                .and_then(|_| stdin.write_all(b"\n"))
                .and_then(|_| stdin.flush());
            let failed = result.is_err();
            let _ = job.result.send(result);
            if failed {
                break;
            }
        }
    });
    sender
}

fn kill_proc(mut process: AgentProc) {
    #[cfg(windows)]
    {
        let pid = process.child.id();
        let mut command = Command::new("taskkill");
        hidden(
            command
                .args(["/T", "/F", "/PID", &pid.to_string()])
                .stdout(Stdio::null())
                .stderr(Stdio::null()),
        );
        let _ = command.status();
    }
    let _ = process.child.kill();
    let _ = process.child.wait();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn logical_target_hashes_frames_without_persisting_them() {
        let a = digest_target(&["session-1", "{\"token\":\"secret-a\"}"]);
        let b = digest_target(&["session-1", "{\"token\":\"secret-b\"}"]);
        assert_ne!(a, b);
        assert!(!a.contains("secret"));
        assert_eq!(a.len(), "sha256:".len() + 64);
    }

    #[test]
    fn identity_validation_is_bounded() {
        assert!(validate_identity("runId", "run-1").is_ok());
        assert!(validate_identity("runId", "").is_err());
        assert!(validate_identity("runId", &"x".repeat(257)).is_err());
        assert!(validate_identity("runId", "run\n1").is_err());
        assert!(validate_channel_identity("agentSessionId", "session-1").is_ok());
        assert!(validate_channel_identity("agentSessionId", "session/escape").is_err());
    }

    #[test]
    fn one_native_runtime_owns_the_local_journal() {
        let path =
            std::env::temp_dir().join(format!("wiii-runtime-{}.sqlite3", uuid::Uuid::new_v4()));
        {
            let first = NekoRuntime::open(&path).unwrap();
            assert!(NekoRuntime::open(&path).is_err());
            drop(first);
            assert!(NekoRuntime::open(&path).is_ok());
        }
        let _ = std::fs::remove_file(&path);
        let _ = std::fs::remove_file(path.with_extension("sqlite3-wal"));
        let _ = std::fs::remove_file(path.with_extension("sqlite3-shm"));
        let _ = std::fs::remove_file(path.with_extension("sqlite3.lock"));
    }
}
