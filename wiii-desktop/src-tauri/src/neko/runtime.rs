use super::journal::{
    Journal, NewSession, ReplayPage, RequestDecision, SessionRecord, StartRequestDecision,
};
use super::lifecycle::{OperationPhase, RunState};
use super::provider::{
    self, spawn_owned, terminate_child_tree, AgentAvailability, AgentInfo, AgentProfile, OwnedChild,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};
use std::fs::{File, OpenOptions};
use std::io::{self, BufRead, BufReader, Write};
use std::path::Path;
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{channel, sync_channel, Receiver, SyncSender, TrySendError};
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::Duration;
use tauri::{AppHandle, Emitter};

const WRITER_QUEUE_CAPACITY: usize = 32;
const WRITE_RESULT_TIMEOUT: Duration = Duration::from_secs(5);
const PROCESS_EXIT_POLL_INTERVAL: Duration = Duration::from_millis(100);
const PROVIDER_READER_DRAIN_TIMEOUT: Duration = Duration::from_secs(1);
const MAX_PROVIDER_FRAME_BYTES: usize = 4 * 1024 * 1024;

pub(crate) const UNKNOWN_OUTCOME_PREFIX: &str = "unknown_outcome:";

pub(crate) fn unknown_outcome_error(message: impl std::fmt::Display) -> String {
    format!("{UNKNOWN_OUTCOME_PREFIX} {message}")
}

struct WriteJob {
    line: String,
    result: std::sync::mpsc::Sender<io::Result<()>>,
}

struct AgentProc {
    child: OwnedChild,
    writer: SyncSender<WriteJob>,
}

struct ReaderWorker {
    start: std::sync::mpsc::Sender<()>,
    finished: Receiver<()>,
}

enum ProcessPoll {
    Running,
    Released,
    Exited(ProcessExitNotice),
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct ProcessExitNotice {
    exit_code: Option<i32>,
    termination_proven: bool,
    terminal_state_persisted: bool,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct PendingRequestCompletion {
    request_id: String,
    result: Value,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
struct PendingTerminalFact {
    next_state: RunState,
    phase: OperationPhase,
    continuity: String,
    event_type: String,
    payload: Value,
    request_completion: Option<PendingRequestCompletion>,
}

struct RuntimeInner {
    journal: Journal,
    processes: Mutex<HashMap<String, AgentProc>>,
    exit_supervisions: Mutex<HashSet<String>>,
    pending_terminal_facts: Mutex<HashMap<String, PendingTerminalFact>>,
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
        let journal = Journal::open(path)?;
        let pending_terminal_facts = journal
            .pending_terminal_facts()?
            .into_iter()
            .map(|(agent_session_id, value)| {
                serde_json::from_value(value)
                    .map(|fact| (agent_session_id, fact))
                    .map_err(|error| format!("decode retained Neko terminal fact failed: {error}"))
            })
            .collect::<Result<HashMap<_, _>, _>>()?;
        Ok(Self {
            inner: Arc::new(RuntimeInner {
                journal,
                processes: Mutex::new(HashMap::new()),
                exit_supervisions: Mutex::new(HashSet::new()),
                pending_terminal_facts: Mutex::new(pending_terminal_facts),
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

    pub fn list_sessions(
        &self,
        app: &AppHandle,
        run_id: Option<&str>,
    ) -> Result<Vec<SessionRecord>, String> {
        let _operation = lock(&self.inner.operations);
        let pending = lock(&self.inner.pending_terminal_facts)
            .keys()
            .cloned()
            .collect::<Vec<_>>();
        for agent_session_id in pending {
            self.flush_pending_terminal_fact(app, &agent_session_id)
                .map_err(|error| {
                    unknown_outcome_error(format!(
                        "verified process exit is awaiting durable lifecycle commit; session hydration is blocked: {error}"
                    ))
                })?;
        }
        self.ensure_exit_supervision_complete(None, "session hydration")?;
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
        // Admit the request identity, listable projection, and creation event
        // in one transaction before any unlocked host I/O. A reconnect can
        // therefore never observe an Accepted start without its native owner.
        {
            let _operation = lock(&self.inner.operations);
            let accepting_new = !self.inner.shutting_down.load(Ordering::Acquire);
            match self.inner.journal.begin_start_request(
                &request.request_id,
                &target,
                NewSession {
                    agent_session_id: &request.agent_session_id,
                    task_id: &request.task_id,
                    run_id: &request.run_id,
                    environment_id: &request.environment_id,
                    provider_id: &request.provider_id,
                    workspace_path: &request.workspace_path,
                },
                accepting_new,
                "session.created",
                json!({ "providerId": request.provider_id }),
            )? {
                StartRequestDecision::Execute(event) => {
                    let _ = app.emit("neko-control://event", event);
                }
                StartRequestDecision::Replay(value) => {
                    return serde_json::from_value(value)
                        .map_err(|error| format!("decode recorded session start failed: {error}"));
                }
                StartRequestDecision::RecordedError(code) => {
                    return Err(format!("recorded session start failed: {code}"));
                }
                StartRequestDecision::UnknownOutcome => {
                    return Err(unknown_outcome_error(
                        "session start cannot be replayed automatically",
                    ));
                }
                StartRequestDecision::AdmissionClosed => {
                    return Err("Neko runtime is shutting down; new sessions are rejected".into());
                }
            }
        }

        if let Err(error) = validate_start_workspace(&request) {
            let _operation = lock(&self.inner.operations);
            return Err(self.reject_start_error(&app, &request, "invalid_workspace", None, error));
        }

        // Version/profile discovery can invoke a slow or broken provider shim.
        // The request and its Starting projection are durable first, but this
        // read-only probe must not block lifecycle traffic for live agents.
        let resolved = match provider::resolve(&request.provider_id) {
            Ok(resolved) => resolved,
            Err(error) => {
                let _operation = lock(&self.inner.operations);
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
                let _operation = lock(&self.inner.operations);
                return Err(self.reject_start_error(
                    &app,
                    &request,
                    "invalid_request",
                    resolved.version.as_deref(),
                    error,
                ));
            }
        };
        let _operation = lock(&self.inner.operations);
        if let Err(error) = self.ensure_accepting_starts() {
            return Err(self.reject_start_error(
                &app,
                &request,
                "runtime_shutting_down",
                resolved.version.as_deref(),
                error,
            ));
        }
        let current = self
            .inner
            .journal
            .session(&request.agent_session_id)?
            .ok_or_else(|| "accepted Neko session projection disappeared".to_string())?;
        if current.state != RunState::Starting
            || current.operation_phase != OperationPhase::Accepted
        {
            let error = "Neko session start was superseded before provider dispatch".to_string();
            return match self
                .inner
                .journal
                .fail_request(&request.request_id, "start_superseded")
            {
                Ok(()) => Err(error),
                Err(recording_error) => Err(format!(
                    "{error}; additionally failed to persist rejected start: {recording_error}"
                )),
            };
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
        command
            .args(&args)
            .current_dir(&request.workspace_path)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());
        let mut child = match spawn_owned(&mut command) {
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
        let stdin = child.child.stdin.take();
        let stdout = child.child.stdout.take();
        let (stdin, stdout) = match (stdin, stdout) {
            (Some(stdin), Some(stdout)) => (stdin, stdout),
            _ => {
                let termination = terminate_child_tree(&mut child).map_err(|error| {
                    format!(
                        "terminate provider process tree failed: {}",
                        bounded_error(&error)
                    )
                });
                return Err(self.classify_spawn_failure(
                    &app,
                    &request,
                    "provider_stdio_unavailable",
                    resolved.version.as_deref(),
                    "provider stdio became unavailable after spawn",
                    termination,
                ));
            }
        };
        let pid = child.child.id();
        let writer = match spawn_writer(stdin) {
            Ok(writer) => writer,
            Err(error) => {
                let termination = terminate_child_tree(&mut child).map_err(|cleanup| {
                    format!(
                        "terminate provider process tree failed: {}",
                        bounded_error(&cleanup)
                    )
                });
                return Err(self.classify_spawn_failure(
                    &app,
                    &request,
                    "provider_writer_unavailable",
                    resolved.version.as_deref(),
                    format!("provider writer thread could not start: {error}"),
                    termination,
                ));
            }
        };
        lock(&self.inner.processes).insert(
            request.agent_session_id.clone(),
            AgentProc { child, writer },
        );

        let runtime = self.clone();
        let session_id = request.agent_session_id.clone();
        let reader = match spawn_reader(runtime, app.clone(), session_id, stdout) {
            Ok(reader) => reader,
            Err(error) => {
                let termination = self.terminate_owned_process(&request.agent_session_id);
                return Err(self.classify_spawn_failure(
                    &app,
                    &request,
                    "provider_reader_unavailable",
                    resolved.version.as_deref(),
                    format!("provider reader thread could not start: {error}"),
                    termination,
                ));
            }
        };
        let runtime = self.clone();
        let session_id = request.agent_session_id.clone();
        let monitor_start = match spawn_monitor(runtime, app.clone(), session_id, reader.finished) {
            Ok(monitor_start) => monitor_start,
            Err(error) => {
                drop(reader.start);
                let termination = self.terminate_owned_process(&request.agent_session_id);
                return Err(self.classify_spawn_failure(
                    &app,
                    &request,
                    "provider_monitor_unavailable",
                    resolved.version.as_deref(),
                    format!("provider monitor thread could not start: {error}"),
                    termination,
                ));
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
                availability: AgentAvailability::Available,
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
            drop(reader.start);
            drop(monitor_start);
            let termination = self.terminate_owned_process(&request.agent_session_id);
            return Err(self.classify_spawn_failure(
                &app,
                &request,
                "ownership_commit_failed",
                resolved.version.as_deref(),
                format!("provider spawned but ownership commit failed: {error}"),
                termination,
            ));
        }
        // Reader and monitor exist before ownership becomes committed, but are
        // gated until the transaction succeeds so neither can race a starting
        // session into terminal state. The monitor owns exit observation;
        // stdout EOF is deliberately not part of process lifecycle truth.
        let _ = monitor_start.send(());
        let _ = reader.start.send(());

        Ok(result)
    }

    pub fn write_session(&self, request: SessionWriteRequest) -> Result<(), String> {
        validate_identity("requestId", &request.request_id)?;
        validate_identity("agentSessionId", &request.agent_session_id)?;
        validate_provider_frame(&request.line)?;
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
        if let Err(error) = self.flush_pending_terminal_fact(app, &request.agent_session_id) {
            return Err(unknown_outcome_error(format!(
                "verified process exit is awaiting durable lifecycle commit; cancellation is blocked: {error}"
            )));
        }
        self.ensure_exit_supervision_complete(
            Some(&request.agent_session_id),
            "session cancellation",
        )?;
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
        let accepted_without_process = process.is_none()
            && session.state == RunState::Starting
            && session.operation_phase == OperationPhase::Accepted;
        let termination_error = match process {
            Some(mut process) => kill_proc(&mut process).err(),
            None if !session.state.is_terminal() && !accepted_without_process => Some(
                "native process ownership disappeared before cancellation could prove termination"
                    .to_string(),
            ),
            None => None,
        };
        if let Some(error) = termination_error {
            return Err(self.mark_termination_unknown(
                app,
                &request.request_id,
                &request.agent_session_id,
                "cancel_termination_unproven",
                error,
            ));
        }
        let cancelled = !session.state.is_terminal();
        let result = SessionCancelResult {
            agent_session_id: request.agent_session_id.clone(),
            cancelled,
        };
        if cancelled {
            let fact = PendingTerminalFact {
                next_state: RunState::Cancelled,
                phase: OperationPhase::Completed,
                continuity: "active".into(),
                event_type: "run.state_changed".into(),
                payload: json!({ "state": "cancelled", "reason": "requested" }),
                request_completion: Some(PendingRequestCompletion {
                    request_id: request.request_id.clone(),
                    result: serde_json::to_value(&result)
                        .map_err(|error| format!("encode session cancel result failed: {error}"))?,
                }),
            };
            self.persist_terminal_fact(app, &request.agent_session_id, fact)?;
        } else {
            self.inner
                .journal
                .set_request_phase(&request.request_id, OperationPhase::Committed)?;
            self.inner.journal.complete_request(
                &request.request_id,
                &serde_json::to_value(&result)
                    .map_err(|error| format!("encode session cancel result failed: {error}"))?,
            )?;
        }
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
        for (agent_session_id, mut process) in processes {
            let termination = kill_proc(&mut process);
            let fact = match termination {
                Ok(()) => PendingTerminalFact {
                    next_state: RunState::Cancelled,
                    phase: OperationPhase::Completed,
                    continuity: "active".into(),
                    event_type: "run.state_changed".into(),
                    payload: json!({ "state": "cancelled", "reason": "application_exit" }),
                    request_completion: None,
                },
                Err(error) => PendingTerminalFact {
                    next_state: RunState::UnknownOutcome,
                    phase: OperationPhase::UnknownOutcome,
                    continuity: "unknown_outcome".into(),
                    event_type: "run.state_changed".into(),
                    payload: json!({
                        "state": "unknown_outcome",
                        "reason": "shutdown_termination_unproven",
                        "detail": bounded_error(&error),
                    }),
                    request_completion: None,
                },
            };
            match self.inner.journal.session(&agent_session_id) {
                Ok(Some(session)) if session.state.is_terminal() => {}
                Ok(None) => {}
                Ok(Some(_)) | Err(_) => {
                    let _ = self.persist_terminal_fact(app, &agent_session_id, fact);
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

    fn ensure_exit_supervision_complete(
        &self,
        agent_session_id: Option<&str>,
        operation: &str,
    ) -> Result<(), String> {
        let supervisions = lock(&self.inner.exit_supervisions);
        let blocked = agent_session_id
            .map(|id| supervisions.contains(id))
            .unwrap_or_else(|| !supervisions.is_empty());
        if blocked {
            return Err(unknown_outcome_error(format!(
                "native process exit supervision is still committing terminal state; retry {operation} after reconciliation"
            )));
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

    fn classify_spawn_failure(
        &self,
        app: &AppHandle,
        request: &SessionStartRequest,
        reason: &str,
        provider_version: Option<&str>,
        original: impl Into<String>,
        termination: Result<(), String>,
    ) -> String {
        let original = original.into();
        match termination {
            Ok(()) => self.reject_start_error(app, request, reason, provider_version, original),
            Err(error) => self.mark_termination_unknown(
                app,
                &request.request_id,
                &request.agent_session_id,
                reason,
                format!("{original}; {error}"),
            ),
        }
    }

    fn terminate_owned_process(&self, agent_session_id: &str) -> Result<(), String> {
        let process = { lock(&self.inner.processes).remove(agent_session_id) };
        let mut process = process
            .ok_or_else(|| "provider process ownership disappeared during cleanup".to_string())?;
        kill_proc(&mut process)
    }

    fn mark_termination_unknown(
        &self,
        app: &AppHandle,
        request_id: &str,
        agent_session_id: &str,
        reason: &str,
        error: String,
    ) -> String {
        let detail = bounded_error(&error);
        let mut recording_failures = Vec::new();
        if let Err(recording_error) = self.inner.journal.mark_request_unknown(request_id) {
            recording_failures.push(recording_error);
        }
        if let Err(recording_error) = self.transition_session_event(
            app,
            agent_session_id,
            RunState::UnknownOutcome,
            OperationPhase::UnknownOutcome,
            "unknown_outcome",
            None,
            None,
            "run.state_changed",
            json!({
                "state": "unknown_outcome",
                "reason": reason,
                "detail": detail,
            }),
        ) {
            recording_failures.push(recording_error);
        }
        let mut message = format!(
            "provider process tree termination could not be proven: {}",
            bounded_error(&error)
        );
        if !recording_failures.is_empty() {
            message.push_str("; additionally failed to persist part of the unknown outcome: ");
            message.push_str(&recording_failures.join("; "));
        }
        unknown_outcome_error(message)
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

    fn persist_terminal_fact(
        &self,
        app: &AppHandle,
        agent_session_id: &str,
        fact: PendingTerminalFact,
    ) -> Result<(), String> {
        // Persist the exact proven fact before the authoritative lifecycle
        // transaction. If the process crashes during that transaction, startup
        // recovery must see this record and preserve the session/request for
        // exact reconciliation instead of degrading it to unknown_outcome.
        let request_id = fact
            .request_completion
            .as_ref()
            .map(|completion| completion.request_id.as_str());
        let encoded = serde_json::to_value(&fact)
            .map_err(|error| format!("encode retained Neko terminal fact failed: {error}"))?;
        let retention =
            self.inner
                .journal
                .retain_terminal_fact(agent_session_id, request_id, &encoded);
        lock(&self.inner.pending_terminal_facts).insert(agent_session_id.to_string(), fact.clone());
        let result = if let Some(completion) = &fact.request_completion {
            self.inner
                .journal
                .complete_request_with_session_event(
                    agent_session_id,
                    fact.next_state,
                    fact.phase,
                    &fact.continuity,
                    &fact.event_type,
                    fact.payload.clone(),
                    &completion.request_id,
                    &completion.result,
                )
                .map(|event| {
                    let _ = app.emit("neko-control://event", event);
                })
        } else {
            self.transition_session_event(
                app,
                agent_session_id,
                fact.next_state,
                fact.phase,
                &fact.continuity,
                None,
                None,
                &fact.event_type,
                fact.payload.clone(),
            )
        };
        match result {
            Ok(()) => {
                lock(&self.inner.pending_terminal_facts).remove(agent_session_id);
                Ok(())
            }
            Err(error) => match retention {
                Ok(()) => Err(error),
                Err(retention) => Err(format!(
                    "{error}; retaining the verified terminal fact also failed: {retention}"
                )),
            },
        }
    }

    fn flush_pending_terminal_fact(
        &self,
        app: &AppHandle,
        agent_session_id: &str,
    ) -> Result<bool, String> {
        let fact = lock(&self.inner.pending_terminal_facts)
            .get(agent_session_id)
            .cloned();
        let Some(fact) = fact else {
            return Ok(false);
        };
        if self
            .inner
            .journal
            .session(agent_session_id)?
            .is_some_and(|session| session.state.is_terminal())
        {
            if let Some(completion) = &fact.request_completion {
                self.inner.journal.reconcile_terminal_request(
                    agent_session_id,
                    &completion.request_id,
                    &completion.result,
                )?;
            } else {
                self.inner.journal.remove_terminal_fact(agent_session_id)?;
            }
            lock(&self.inner.pending_terminal_facts).remove(agent_session_id);
            return Ok(true);
        }
        self.persist_terminal_fact(app, agent_session_id, fact)?;
        Ok(true)
    }

    fn poll_process_exit(
        &self,
        app: &AppHandle,
        agent_session_id: &str,
        reader_finished: &Receiver<()>,
    ) -> ProcessPoll {
        let (mut process, code, reason) = {
            let _operation = lock(&self.inner.operations);
            let mut processes = lock(&self.inner.processes);
            let Some(process) = processes.get_mut(agent_session_id) else {
                return ProcessPoll::Released;
            };
            let (code, reason) = match process.child.child.try_wait() {
                Ok(Some(status)) => (status.code(), "provider_process_exited"),
                Ok(None) => return ProcessPoll::Running,
                Err(_) => (None, "provider_process_status_unavailable"),
            };
            // Publish the hand-off before releasing lifecycle serialization.
            // Cancellation/listing must never interpret the temporarily empty
            // process map as missing ownership while the exact exit fact is
            // still being proven and committed.
            lock(&self.inner.exit_supervisions).insert(agent_session_id.to_string());
            let process = processes
                .remove(agent_session_id)
                .expect("process existed while polling its exit");
            (process, code, reason)
        };
        // The provider leader may exit while a descendant retains inherited
        // stdio. Tear down the isolated process tree so the reader cannot be
        // stranded and no orphan survives after lifecycle ownership ends.
        let termination =
            terminate_child_tree(&mut process.child).map_err(|error| bounded_error(&error));
        let fact = terminal_fact_for_termination(&termination, reason, "exit_termination_unproven");
        // Preserve the provider's final bounded frames before notifying the
        // renderer of exit. A broken descendant may still retain the pipe, so
        // draining is bounded and happens without the global lifecycle lock.
        let _ = reader_finished.recv_timeout(PROVIDER_READER_DRAIN_TIMEOUT);
        let _operation = lock(&self.inner.operations);
        let session = session_or_retain_terminal_fact(
            self.inner.journal.session(agent_session_id),
            &self.inner.pending_terminal_facts,
            agent_session_id,
            &fact,
        );
        let terminal_state_persisted = match session.as_ref() {
            Some(session) if session.state.is_terminal() => true,
            Some(_) => self
                .persist_terminal_fact(app, agent_session_id, fact)
                .is_ok(),
            None => false,
        };
        if let Some(session) = session {
            let _ = self.emit_control_event(
                app,
                &session.run_id,
                "process.exited",
                agent_session_id,
                json!({
                    "exitCode": code,
                    "terminationProven": termination.is_ok(),
                    "terminalStatePersisted": terminal_state_persisted,
                }),
            );
        }
        lock(&self.inner.exit_supervisions).remove(agent_session_id);
        ProcessPoll::Exited(ProcessExitNotice {
            exit_code: code,
            termination_proven: termination.is_ok(),
            terminal_state_persisted,
        })
    }

    fn fail_provider_protocol(&self, app: &AppHandle, agent_session_id: &str) {
        let _operation = lock(&self.inner.operations);
        let process = lock(&self.inner.processes).remove(agent_session_id);
        let Some(mut process) = process else {
            return;
        };
        let termination = kill_proc(&mut process);
        let fact = terminal_fact_for_termination(
            &termination,
            "provider_protocol_failure",
            "protocol_failure_termination_unproven",
        );
        let session = session_or_retain_terminal_fact(
            self.inner.journal.session(agent_session_id),
            &self.inner.pending_terminal_facts,
            agent_session_id,
            &fact,
        );
        let Some(session) = session else {
            let _ = app.emit(
                &format!("neko-session://exit/{agent_session_id}"),
                ProcessExitNotice {
                    exit_code: None,
                    termination_proven: termination.is_ok(),
                    terminal_state_persisted: false,
                },
            );
            return;
        };
        let terminal_state_persisted = if session.state.is_terminal() {
            true
        } else {
            self.persist_terminal_fact(app, agent_session_id, fact)
                .is_ok()
        };
        let _ = self.emit_control_event(
            app,
            &session.run_id,
            "process.exited",
            agent_session_id,
            json!({
                "exitCode": null,
                "reason": "provider_protocol_failure",
                "terminationProven": termination.is_ok(),
                "terminalStatePersisted": terminal_state_persisted,
            }),
        );
        let _ = app.emit(
            &format!("neko-session://exit/{agent_session_id}"),
            ProcessExitNotice {
                exit_code: None,
                termination_proven: termination.is_ok(),
                terminal_state_persisted,
            },
        );
    }
}

fn terminal_fact_for_termination(
    termination: &Result<(), String>,
    proven_reason: &'static str,
    unproven_reason: &'static str,
) -> PendingTerminalFact {
    match termination {
        Ok(()) => PendingTerminalFact {
            next_state: RunState::Failed,
            phase: OperationPhase::Failed,
            continuity: "continuity_lost".into(),
            event_type: "run.state_changed".into(),
            payload: json!({ "state": "failed", "reason": proven_reason }),
            request_completion: None,
        },
        Err(error) => PendingTerminalFact {
            next_state: RunState::UnknownOutcome,
            phase: OperationPhase::UnknownOutcome,
            continuity: "unknown_outcome".into(),
            event_type: "run.state_changed".into(),
            payload: json!({
                "state": "unknown_outcome",
                "reason": unproven_reason,
                "detail": bounded_error(error),
            }),
            request_completion: None,
        },
    }
}

fn session_or_retain_terminal_fact(
    session: Result<Option<SessionRecord>, String>,
    pending: &Mutex<HashMap<String, PendingTerminalFact>>,
    agent_session_id: &str,
    fact: &PendingTerminalFact,
) -> Option<SessionRecord> {
    match session {
        Ok(Some(session)) => Some(session),
        Ok(None) => None,
        Err(_) => {
            lock(pending).insert(agent_session_id.to_string(), fact.clone());
            None
        }
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

fn validate_provider_frame(frame: &str) -> Result<(), String> {
    if frame.is_empty() || frame.len() > 1024 * 1024 {
        return Err("provider frame must be between 1 byte and 1 MiB".into());
    }
    if frame.contains(['\r', '\n']) {
        return Err("provider frame must contain exactly one delimiter-free JSON-RPC line".into());
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
) -> io::Result<ReaderWorker> {
    let (start_sender, start_receiver) = channel::<()>();
    let (finished_sender, finished_receiver) = channel::<()>();
    std::thread::Builder::new()
        .name("neko-provider-reader".into())
        .spawn(move || {
            if start_receiver.recv().is_err() {
                return;
            }
            let mut reader = BufReader::new(stdout);
            let mut frame = Vec::new();
            loop {
                match read_bounded_frame(&mut reader, &mut frame, MAX_PROVIDER_FRAME_BYTES) {
                    Ok(Some(line)) => {
                        let _ = app.emit(&format!("neko-session://line/{session_id}"), line);
                    }
                    Ok(None) => break,
                    Err(_) => {
                        runtime.fail_provider_protocol(&app, &session_id);
                        break;
                    }
                }
            }
            let _ = finished_sender.send(());
        })?;
    Ok(ReaderWorker {
        start: start_sender,
        finished: finished_receiver,
    })
}

fn spawn_monitor(
    runtime: NekoRuntime,
    app: AppHandle,
    session_id: String,
    reader_finished: Receiver<()>,
) -> io::Result<std::sync::mpsc::Sender<()>> {
    let (start_sender, start_receiver) = channel::<()>();
    std::thread::Builder::new()
        .name("neko-provider-monitor".into())
        .spawn(move || {
            if start_receiver.recv().is_err() {
                return;
            }
            loop {
                match runtime.poll_process_exit(&app, &session_id, &reader_finished) {
                    ProcessPoll::Running => std::thread::sleep(PROCESS_EXIT_POLL_INTERVAL),
                    ProcessPoll::Released => break,
                    ProcessPoll::Exited(notice) => {
                        let _ = app.emit(&format!("neko-session://exit/{session_id}"), notice);
                        break;
                    }
                }
            }
        })?;
    Ok(start_sender)
}

fn read_bounded_frame<R: BufRead>(
    reader: &mut R,
    frame: &mut Vec<u8>,
    max_bytes: usize,
) -> io::Result<Option<String>> {
    frame.clear();
    loop {
        let available = reader.fill_buf()?;
        if available.is_empty() {
            if frame.is_empty() {
                return Ok(None);
            }
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "provider frame ended before its newline delimiter",
            ));
        }
        let newline = available.iter().position(|byte| *byte == b'\n');
        let take = newline.map_or(available.len(), |position| position + 1);
        let payload_bytes = newline.map_or(take, |position| position);
        if frame.len().saturating_add(payload_bytes) > max_bytes {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "provider frame exceeded the byte limit",
            ));
        }
        frame.extend_from_slice(&available[..take]);
        reader.consume(take);
        if newline.is_some() {
            break;
        }
    }
    if frame.last() == Some(&b'\n') {
        frame.pop();
    }
    if frame.last() == Some(&b'\r') {
        frame.pop();
    }
    String::from_utf8(frame.clone())
        .map(Some)
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))
}

fn kill_proc(process: &mut AgentProc) -> Result<(), String> {
    terminate_child_tree(&mut process.child).map_err(|error| {
        format!(
            "terminate provider process tree failed: {}",
            bounded_error(&error)
        )
    })
}

fn bounded_error(error: &impl std::fmt::Display) -> String {
    error.to_string().chars().take(4_096).collect()
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
    fn provider_write_rejects_embedded_frame_delimiters_before_dispatch() {
        assert!(validate_provider_frame(r#"{"jsonrpc":"2.0"}"#).is_ok());
        assert!(validate_provider_frame("first\nsecond").is_err());
        assert!(validate_provider_frame("first\rsecond").is_err());
        assert!(validate_provider_frame("first\r\nsecond").is_err());
    }

    #[test]
    fn terminal_fact_survives_a_projection_read_failure() {
        let pending = Mutex::new(HashMap::new());
        let fact = terminal_fact_for_termination(
            &Ok(()),
            "provider_process_exited",
            "exit_termination_unproven",
        );

        assert!(session_or_retain_terminal_fact(
            Err("journal unavailable".into()),
            &pending,
            "session-1",
            &fact,
        )
        .is_none());
        let retained = lock(&pending).get("session-1").cloned().unwrap();
        assert_eq!(retained.next_state, RunState::Failed);
        assert_eq!(retained.phase, OperationPhase::Failed);
        assert_eq!(
            retained.payload,
            json!({ "state": "failed", "reason": "provider_process_exited" })
        );
    }

    #[test]
    fn terminal_fact_is_not_retained_after_projection_removal() {
        let pending = Mutex::new(HashMap::new());
        let fact = terminal_fact_for_termination(
            &Ok(()),
            "provider_process_exited",
            "exit_termination_unproven",
        );

        assert!(session_or_retain_terminal_fact(Ok(None), &pending, "session-1", &fact,).is_none());
        assert!(lock(&pending).is_empty());
    }

    #[test]
    fn provider_frames_are_bounded_before_a_newline_or_eof() {
        let mut frame = Vec::new();
        let mut valid = BufReader::with_capacity(2, io::Cursor::new(b"1234\nnext\n"));
        assert_eq!(
            read_bounded_frame(&mut valid, &mut frame, 4).unwrap(),
            Some("1234".into())
        );
        assert_eq!(
            read_bounded_frame(&mut valid, &mut frame, 4).unwrap(),
            Some("next".into())
        );

        let mut oversized = BufReader::with_capacity(2, io::Cursor::new(b"12345\n"));
        let error = read_bounded_frame(&mut oversized, &mut frame, 4).unwrap_err();
        assert_eq!(error.kind(), io::ErrorKind::InvalidData);

        let mut unterminated = BufReader::with_capacity(2, io::Cursor::new(b"12345"));
        let error = read_bounded_frame(&mut unterminated, &mut frame, 4).unwrap_err();
        assert_eq!(error.kind(), io::ErrorKind::InvalidData);

        let mut short_unterminated = BufReader::with_capacity(2, io::Cursor::new(b"1234"));
        let error = read_bounded_frame(&mut short_unterminated, &mut frame, 4).unwrap_err();
        assert_eq!(error.kind(), io::ErrorKind::InvalidData);
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
    fn in_flight_exit_supervision_blocks_hydration_and_matching_cancellation() {
        let path =
            std::env::temp_dir().join(format!("wiii-runtime-{}.sqlite3", uuid::Uuid::new_v4()));
        {
            let runtime = NekoRuntime::open(&path).unwrap();
            lock(&runtime.inner.exit_supervisions).insert("session-1".into());
            assert!(runtime
                .ensure_exit_supervision_complete(None, "session hydration")
                .unwrap_err()
                .starts_with(UNKNOWN_OUTCOME_PREFIX));
            assert!(runtime
                .ensure_exit_supervision_complete(Some("session-1"), "session cancellation")
                .unwrap_err()
                .starts_with(UNKNOWN_OUTCOME_PREFIX));
            assert!(runtime
                .ensure_exit_supervision_complete(Some("session-2"), "session cancellation")
                .is_ok());
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
