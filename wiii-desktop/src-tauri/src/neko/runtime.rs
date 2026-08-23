use super::journal::{Journal, NewSession, ReplayPage, RequestDecision, SessionRecord};
use super::lifecycle::{OperationPhase, RunState};
use super::provider::{self, hidden, terminate_child_tree, AgentInfo, AgentProfile};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::fs::{File, OpenOptions};
use std::io::{self, BufRead, BufReader, Write};
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{channel, sync_channel, SyncSender, TrySendError};
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::Duration;
use tauri::{AppHandle, Emitter};

const WRITER_QUEUE_CAPACITY: usize = 32;
const WRITE_RESULT_TIMEOUT: Duration = Duration::from_secs(5);
const PROCESS_EXIT_POLL_INTERVAL: Duration = Duration::from_millis(100);

pub(crate) const UNKNOWN_OUTCOME_PREFIX: &str = "unknown_outcome:";

pub(crate) fn unknown_outcome_error(message: impl std::fmt::Display) -> String {
    format!("{UNKNOWN_OUTCOME_PREFIX} {message}")
}

struct WriteJob {
    line: String,
    result: std::sync::mpsc::Sender<io::Result<()>>,
}

struct AgentProc {
    child: Child,
    writer: SyncSender<WriteJob>,
}

enum ProcessPoll {
    Running,
    Released,
    Exited(Option<i32>),
}

struct RuntimeInner {
    journal: Journal,
    processes: Mutex<HashMap<String, AgentProc>>,
    operations: Mutex<()>,
    shutting_down: AtomicBool,
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
                shutting_down: AtomicBool::new(false),
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
        // Stable syntax participates in request identity and is safe to check
        // before replay. Workspace existence is volatile and must be checked
        // only after a prior completed/uncertain operation has been resolved.
        validate_start_identity(&request)?;
        let target = digest_target(&[
            &request.agent_session_id,
            &request.task_id,
            &request.run_id,
            &request.provider_id,
            &request.environment_id,
            &request.workspace_path,
            request.profile_id.as_deref().unwrap_or(""),
        ]);
        {
            let _operation = lock(&self.inner.operations);
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
                    return Err(unknown_outcome_error(
                        "session start cannot be replayed automatically",
                    ));
                }
                RequestDecision::Execute => {
                    if let Err(error) = self.ensure_accepting_starts() {
                        self.inner
                            .journal
                            .fail_request(&request.request_id, "runtime_shutting_down")?;
                        return Err(error);
                    }
                }
            }
        }

        if let Err(error) = validate_start_workspace(&request) {
            let _operation = lock(&self.inner.operations);
            return match self
                .inner
                .journal
                .fail_request(&request.request_id, "invalid_workspace")
            {
                Ok(()) => Err(error),
                Err(recording_error) => Err(format!(
                    "{error}; additionally failed to persist rejected start: {recording_error}"
                )),
            };
        }

        // Version/profile discovery can invoke a slow or broken provider shim.
        // The request identity is durable first, but this read-only probe must
        // not block lifecycle traffic for live agents.
        let resolved = match provider::resolve(&request.provider_id) {
            Ok(resolved) => resolved,
            Err(error) => {
                let _operation = lock(&self.inner.operations);
                return match self
                    .inner
                    .journal
                    .fail_request(&request.request_id, "provider_unavailable")
                {
                    Ok(()) => Err(error),
                    Err(recording_error) => Err(format!(
                        "{error}; additionally failed to persist rejected start: {recording_error}"
                    )),
                };
            }
        };
        let args = match resolved
            .definition
            .launch_args(request.profile_id.as_deref())
        {
            Ok(args) => args,
            Err(error) => {
                let _operation = lock(&self.inner.operations);
                return match self
                    .inner
                    .journal
                    .fail_request(&request.request_id, "invalid_request")
                {
                    Ok(()) => Err(error),
                    Err(recording_error) => Err(format!(
                        "{error}; additionally failed to persist rejected start: {recording_error}"
                    )),
                };
            }
        };
        let _operation = lock(&self.inner.operations);
        if let Err(error) = self.ensure_accepting_starts() {
            return match self
                .inner
                .journal
                .fail_request(&request.request_id, "runtime_shutting_down")
            {
                Ok(()) => Err(error),
                Err(recording_error) => Err(format!(
                    "{error}; additionally failed to persist rejected start: {recording_error}"
                )),
            };
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
                terminate_child_tree(&mut child);
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
                return Err(unknown_outcome_error(
                    "provider stdio became unavailable after spawn",
                ));
            }
        };
        let pid = child.id();
        let writer = match spawn_writer(stdin) {
            Ok(writer) => writer,
            Err(error) => {
                terminate_child_tree(&mut child);
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
                    json!({ "state": "unknown_outcome", "reason": "provider_writer_unavailable" }),
                );
                return Err(unknown_outcome_error(format!(
                    "provider writer thread could not start: {error}"
                )));
            }
        };
        lock(&self.inner.processes).insert(
            request.agent_session_id.clone(),
            AgentProc { child, writer },
        );

        let runtime = self.clone();
        let session_id = request.agent_session_id.clone();
        let reader_start = match spawn_reader(runtime, app.clone(), session_id, stdout) {
            Ok(reader_start) => reader_start,
            Err(error) => {
                if let Some(process) = lock(&self.inner.processes).remove(&request.agent_session_id)
                {
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
                    json!({ "state": "unknown_outcome", "reason": "provider_reader_unavailable" }),
                );
                return Err(unknown_outcome_error(format!(
                    "provider reader thread could not start: {error}"
                )));
            }
        };

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
            drop(reader_start);
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
            return Err(unknown_outcome_error(format!(
                "provider spawned but ownership commit failed: {error}"
            )));
        }
        // The reader exists before ownership becomes committed, but is gated
        // until the transaction succeeds so it cannot race a starting session
        // into terminal state. Failure paths drop the gate and kill ownership.
        let _ = reader_start.send(());

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
        // Starts release the lifecycle lock while probing providers. Mark the
        // authority closed before draining so a probe cannot spawn afterward.
        self.inner.shutting_down.store(true, Ordering::Release);
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

    fn ensure_accepting_starts(&self) -> Result<(), String> {
        if self.inner.shutting_down.load(Ordering::Acquire) {
            return Err("Neko runtime is shutting down; new sessions are rejected".to_string());
        }
        Ok(())
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

    fn poll_process_exit(&self, app: &AppHandle, agent_session_id: &str) -> ProcessPoll {
        let _operation = lock(&self.inner.operations);
        let code = {
            let mut processes = lock(&self.inner.processes);
            let Some(process) = processes.get_mut(agent_session_id) else {
                return ProcessPoll::Released;
            };
            match process.child.try_wait() {
                Ok(Some(status)) => {
                    let code = status.code();
                    processes.remove(agent_session_id);
                    code
                }
                Ok(None) | Err(_) => return ProcessPoll::Running,
            }
        };
        let Ok(Some(session)) = self.inner.journal.session(agent_session_id) else {
            return ProcessPoll::Exited(code);
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
        ProcessPoll::Exited(code)
    }
}

fn validate_start_identity(request: &SessionStartRequest) -> Result<(), String> {
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
    if !workspace.is_absolute() {
        return Err("workspace must be an absolute directory".into());
    }
    if let Some(profile_id) = request.profile_id.as_deref() {
        provider::validate_profile_id(profile_id)?;
    }
    Ok(())
}

fn validate_start_workspace(request: &SessionStartRequest) -> Result<(), String> {
    if !Path::new(&request.workspace_path).is_dir() {
        return Err("workspace must be an existing absolute directory".into());
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

fn spawn_writer(mut stdin: std::process::ChildStdin) -> io::Result<SyncSender<WriteJob>> {
    let (sender, receiver) = sync_channel::<WriteJob>(WRITER_QUEUE_CAPACITY);
    std::thread::Builder::new()
        .name("neko-provider-writer".into())
        .spawn(move || {
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
        })?;
    Ok(sender)
}

fn spawn_reader(
    runtime: NekoRuntime,
    app: AppHandle,
    session_id: String,
    stdout: std::process::ChildStdout,
) -> io::Result<std::sync::mpsc::Sender<()>> {
    let (start_sender, start_receiver) = channel::<()>();
    std::thread::Builder::new()
        .name("neko-provider-reader".into())
        .spawn(move || {
            if start_receiver.recv().is_err() {
                return;
            }
            for line in BufReader::new(stdout).lines() {
                match line {
                    Ok(line) => {
                        let _ = app.emit(&format!("neko-session://line/{session_id}"), line);
                    }
                    Err(_) => break,
                }
            }
            // EOF does not prove the process exited: a provider may redirect
            // stdout and remain alive. Poll without holding the lifecycle lock
            // across a blocking wait, retaining ownership so cancel still works.
            loop {
                match runtime.poll_process_exit(&app, &session_id) {
                    ProcessPoll::Running => std::thread::sleep(PROCESS_EXIT_POLL_INTERVAL),
                    ProcessPoll::Released => break,
                    ProcessPoll::Exited(code) => {
                        let _ = app.emit(&format!("neko-session://exit/{session_id}"), code);
                        break;
                    }
                }
            }
        })?;
    Ok(start_sender)
}

fn kill_proc(mut process: AgentProc) {
    terminate_child_tree(&mut process.child);
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
    fn volatile_workspace_availability_is_deferred_until_after_replay_lookup() {
        let missing =
            std::env::temp_dir().join(format!("wiii-missing-workspace-{}", uuid::Uuid::new_v4()));
        let request = SessionStartRequest {
            request_id: "request-1".into(),
            agent_session_id: "session-1".into(),
            task_id: "task-1".into(),
            run_id: "run-1".into(),
            provider_id: "neko".into(),
            environment_id: "environment-1".into(),
            workspace_path: missing.to_string_lossy().into_owned(),
            profile_id: None,
        };

        assert!(validate_start_identity(&request).is_ok());
        assert!(validate_start_workspace(&request).is_err());
    }

    #[test]
    fn shutdown_state_fail_closes_future_starts() {
        let path =
            std::env::temp_dir().join(format!("wiii-runtime-{}.sqlite3", uuid::Uuid::new_v4()));
        {
            let runtime = NekoRuntime::open(&path).unwrap();
            assert!(runtime.ensure_accepting_starts().is_ok());
            runtime.inner.shutting_down.store(true, Ordering::Release);
            assert!(runtime
                .ensure_accepting_starts()
                .unwrap_err()
                .contains("shutting down"));
        }
        let _ = std::fs::remove_file(&path);
        let _ = std::fs::remove_file(path.with_extension("sqlite3-wal"));
        let _ = std::fs::remove_file(path.with_extension("sqlite3-shm"));
        let _ = std::fs::remove_file(path.with_extension("sqlite3.lock"));
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
