use super::lifecycle::{
    can_advance_operation, can_transition, recovery_disposition, OperationPhase,
    RecoveryDisposition, RunState,
};
use chrono::{SecondsFormat, Utc};
use rusqlite::{params, Connection, OptionalExtension, TransactionBehavior};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::path::Path;
use std::sync::{Arc, Mutex, MutexGuard};
use uuid::Uuid;

const MAX_EVENT_PAYLOAD_BYTES: usize = 4 * 1024;
const MAX_REPLAY_LIMIT: u32 = 500;

#[derive(Clone)]
pub struct Journal {
    connection: Arc<Mutex<Connection>>,
}

fn now() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Millis, true)
}

fn lock(connection: &Mutex<Connection>) -> MutexGuard<'_, Connection> {
    connection
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SessionRecord {
    pub agent_session_id: String,
    pub task_id: String,
    pub run_id: String,
    pub environment_id: String,
    pub provider_id: String,
    pub provider_version: Option<String>,
    pub workspace_path: String,
    pub state: RunState,
    pub operation_phase: OperationPhase,
    pub continuity: String,
    pub pid: Option<u32>,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Clone, Debug)]
pub struct NewSession<'a> {
    pub agent_session_id: &'a str,
    pub task_id: &'a str,
    pub run_id: &'a str,
    pub environment_id: &'a str,
    pub provider_id: &'a str,
    pub workspace_path: &'a str,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ControlEvent {
    pub v: u8,
    pub event_id: String,
    pub stream_id: String,
    pub seq: u64,
    pub at: String,
    #[serde(rename = "type")]
    pub event_type: String,
    pub run_id: String,
    pub agent_session_id: Option<String>,
    pub payload: Value,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ReplayPage {
    pub stream_id: String,
    pub events: Vec<ControlEvent>,
    pub next_after_seq: u64,
    pub has_more: bool,
}

#[derive(Debug, PartialEq)]
pub enum RequestDecision {
    Execute,
    Replay(Value),
    RecordedError(String),
    UnknownOutcome,
}

impl Journal {
    pub fn open(path: &Path) -> Result<Self, String> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|error| format!("create Neko data directory failed: {error}"))?;
        }
        let connection = Connection::open(path)
            .map_err(|error| format!("open Neko runtime journal failed: {error}"))?;
        let journal = Self::from_connection(connection)?;
        journal.recover_incomplete()?;
        Ok(journal)
    }

    #[cfg(test)]
    fn in_memory() -> Self {
        Self::from_connection(Connection::open_in_memory().unwrap()).unwrap()
    }

    fn from_connection(connection: Connection) -> Result<Self, String> {
        connection
            .execute_batch(
                "PRAGMA journal_mode=WAL;
                 PRAGMA foreign_keys=ON;
                 PRAGMA busy_timeout=5000;
                 CREATE TABLE IF NOT EXISTS runtime_sessions (
                   agent_session_id TEXT PRIMARY KEY,
                   task_id TEXT NOT NULL,
                   run_id TEXT NOT NULL,
                   environment_id TEXT NOT NULL,
                   provider_id TEXT NOT NULL,
                   provider_version TEXT,
                   workspace_path TEXT NOT NULL,
                   state TEXT NOT NULL,
                   operation_phase TEXT NOT NULL,
                   continuity TEXT NOT NULL,
                   pid INTEGER,
                   created_at TEXT NOT NULL,
                   updated_at TEXT NOT NULL
                 );
                 CREATE INDEX IF NOT EXISTS idx_runtime_sessions_run
                   ON runtime_sessions(run_id, created_at);
                 CREATE TABLE IF NOT EXISTS control_requests (
                   request_id TEXT PRIMARY KEY,
                   method TEXT NOT NULL,
                   target_id TEXT NOT NULL,
                   phase TEXT NOT NULL,
                   result_json TEXT,
                   error_code TEXT,
                   created_at TEXT NOT NULL,
                   updated_at TEXT NOT NULL
                 );
                 CREATE TABLE IF NOT EXISTS control_events (
                   event_id TEXT PRIMARY KEY,
                   stream_id TEXT NOT NULL,
                   seq INTEGER NOT NULL CHECK(seq > 0),
                   at TEXT NOT NULL,
                   event_type TEXT NOT NULL,
                   run_id TEXT NOT NULL,
                   agent_session_id TEXT REFERENCES runtime_sessions(agent_session_id)
                     ON DELETE SET NULL,
                   payload_json TEXT NOT NULL,
                   UNIQUE(stream_id, seq)
                 );
                 CREATE INDEX IF NOT EXISTS idx_control_events_replay
                   ON control_events(stream_id, seq);",
            )
            .map_err(|error| format!("initialize Neko runtime journal failed: {error}"))?;
        Ok(Self {
            connection: Arc::new(Mutex::new(connection)),
        })
    }

    #[cfg(test)]
    fn journal_mode(&self) -> Result<String, String> {
        lock(&self.connection)
            .query_row("PRAGMA journal_mode", [], |row| row.get(0))
            .map_err(|error| format!("read Neko journal mode failed: {error}"))
    }

    pub fn begin_request(
        &self,
        request_id: &str,
        method: &str,
        target_id: &str,
    ) -> Result<RequestDecision, String> {
        let timestamp = now();
        let connection = lock(&self.connection);
        let existing = connection
            .query_row(
                "SELECT method, target_id, phase, result_json, error_code
                   FROM control_requests WHERE request_id = ?1",
                [request_id],
                |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, String>(2)?,
                        row.get::<_, Option<String>>(3)?,
                        row.get::<_, Option<String>>(4)?,
                    ))
                },
            )
            .optional()
            .map_err(|error| format!("read Neko request identity failed: {error}"))?;

        if let Some((stored_method, stored_target, phase, result, error_code)) = existing {
            if stored_method != method || stored_target != target_id {
                return Err("request identity was already used for another operation".to_string());
            }
            return match OperationPhase::parse(&phase) {
                Some(OperationPhase::Completed) => {
                    let value = result
                        .as_deref()
                        .map(serde_json::from_str)
                        .transpose()
                        .map_err(|error| format!("decode recorded Neko result failed: {error}"))?
                        .unwrap_or(Value::Null);
                    Ok(RequestDecision::Replay(value))
                }
                Some(OperationPhase::Failed) => Ok(RequestDecision::RecordedError(
                    error_code.unwrap_or_else(|| "internal_error".to_string()),
                )),
                Some(OperationPhase::UnknownOutcome)
                | Some(OperationPhase::SideEffectStarted)
                | Some(OperationPhase::Committed) => Ok(RequestDecision::UnknownOutcome),
                Some(OperationPhase::Accepted) | Some(OperationPhase::Dispatched) => Ok(
                    RequestDecision::RecordedError("continuity_lost".to_string()),
                ),
                None => Err("recorded Neko request has an invalid phase".to_string()),
            };
        }

        connection
            .execute(
                "INSERT INTO control_requests
                   (request_id, method, target_id, phase, created_at, updated_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?5)",
                params![
                    request_id,
                    method,
                    target_id,
                    OperationPhase::Accepted.as_str(),
                    timestamp
                ],
            )
            .map_err(|error| format!("record Neko request identity failed: {error}"))?;
        Ok(RequestDecision::Execute)
    }

    pub fn set_request_phase(&self, request_id: &str, next: OperationPhase) -> Result<(), String> {
        let connection = lock(&self.connection);
        let current: String = connection
            .query_row(
                "SELECT phase FROM control_requests WHERE request_id = ?1",
                [request_id],
                |row| row.get(0),
            )
            .map_err(|error| format!("read Neko request phase failed: {error}"))?;
        let current = OperationPhase::parse(&current)
            .ok_or_else(|| "recorded Neko request has an invalid phase".to_string())?;
        if !can_advance_operation(current, next) {
            return Err(format!(
                "invalid Neko operation transition {} -> {}",
                current.as_str(),
                next.as_str()
            ));
        }
        connection
            .execute(
                "UPDATE control_requests SET phase = ?2, updated_at = ?3
                   WHERE request_id = ?1",
                params![request_id, next.as_str(), now()],
            )
            .map_err(|error| format!("update Neko request phase failed: {error}"))?;
        Ok(())
    }

    pub fn complete_request(&self, request_id: &str, result: &Value) -> Result<(), String> {
        let encoded = serde_json::to_string(result)
            .map_err(|error| format!("encode Neko request result failed: {error}"))?;
        if encoded.len() > MAX_EVENT_PAYLOAD_BYTES {
            return Err("Neko request result exceeds the durable limit".to_string());
        }
        let mut connection = lock(&self.connection);
        let transaction = connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(|error| format!("begin Neko result transaction failed: {error}"))?;
        let current: String = transaction
            .query_row(
                "SELECT phase FROM control_requests WHERE request_id = ?1",
                [request_id],
                |row| row.get(0),
            )
            .map_err(|error| format!("read Neko request phase failed: {error}"))?;
        let current = OperationPhase::parse(&current)
            .ok_or_else(|| "recorded Neko request has an invalid phase".to_string())?;
        if !can_advance_operation(current, OperationPhase::Completed) {
            return Err(format!(
                "invalid Neko operation transition {} -> completed",
                current.as_str()
            ));
        }
        transaction
            .execute(
                "UPDATE control_requests SET phase = 'completed', result_json = ?2,
                        error_code = NULL, updated_at = ?3
                   WHERE request_id = ?1",
                params![request_id, encoded, now()],
            )
            .map_err(|error| format!("persist Neko request result failed: {error}"))?;
        transaction
            .commit()
            .map_err(|error| format!("commit Neko request result failed: {error}"))?;
        Ok(())
    }

    pub fn fail_request(&self, request_id: &str, error_code: &str) -> Result<(), String> {
        let mut connection = lock(&self.connection);
        let transaction = connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(|error| format!("begin Neko failure transaction failed: {error}"))?;
        let current: String = transaction
            .query_row(
                "SELECT phase FROM control_requests WHERE request_id = ?1",
                [request_id],
                |row| row.get(0),
            )
            .map_err(|error| format!("read Neko request phase failed: {error}"))?;
        let current = OperationPhase::parse(&current)
            .ok_or_else(|| "recorded Neko request has an invalid phase".to_string())?;
        if !can_advance_operation(current, OperationPhase::Failed) {
            return Err(format!(
                "invalid Neko operation transition {} -> failed",
                current.as_str()
            ));
        }
        transaction
            .execute(
                "UPDATE control_requests SET phase = 'failed', error_code = ?2,
                        result_json = NULL, updated_at = ?3
                   WHERE request_id = ?1",
                params![request_id, error_code, now()],
            )
            .map_err(|error| format!("persist Neko request failure failed: {error}"))?;
        transaction
            .commit()
            .map_err(|error| format!("commit Neko request failure failed: {error}"))?;
        Ok(())
    }

    pub fn mark_request_unknown(&self, request_id: &str) -> Result<(), String> {
        let mut connection = lock(&self.connection);
        let transaction = connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(|error| format!("begin unknown-outcome transaction failed: {error}"))?;
        let current: String = transaction
            .query_row(
                "SELECT phase FROM control_requests WHERE request_id = ?1",
                [request_id],
                |row| row.get(0),
            )
            .map_err(|error| format!("read Neko request phase failed: {error}"))?;
        let current = OperationPhase::parse(&current)
            .ok_or_else(|| "recorded Neko request has an invalid phase".to_string())?;
        if !can_advance_operation(current, OperationPhase::UnknownOutcome) {
            return Err(format!(
                "invalid Neko operation transition {} -> unknown_outcome",
                current.as_str()
            ));
        }
        transaction
            .execute(
                "UPDATE control_requests SET phase = 'unknown_outcome',
                   error_code = 'unknown_outcome', result_json = NULL,
                   updated_at = ?2 WHERE request_id = ?1",
                params![request_id, now()],
            )
            .map_err(|error| format!("persist unknown Neko outcome failed: {error}"))?;
        transaction
            .commit()
            .map_err(|error| format!("commit unknown Neko outcome failed: {error}"))?;
        Ok(())
    }

    pub fn insert_session(&self, session: NewSession<'_>) -> Result<(), String> {
        let timestamp = now();
        lock(&self.connection)
            .execute(
                "INSERT INTO runtime_sessions
                   (agent_session_id, task_id, run_id, environment_id, provider_id,
                    workspace_path, state, operation_phase, continuity, created_at, updated_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, 'active', ?9, ?9)",
                params![
                    session.agent_session_id,
                    session.task_id,
                    session.run_id,
                    session.environment_id,
                    session.provider_id,
                    session.workspace_path,
                    RunState::Starting.as_str(),
                    OperationPhase::Accepted.as_str(),
                    timestamp
                ],
            )
            .map_err(|error| format!("record Neko session failed: {error}"))?;
        Ok(())
    }

    pub fn set_session_phase(
        &self,
        agent_session_id: &str,
        phase: OperationPhase,
    ) -> Result<(), String> {
        let connection = lock(&self.connection);
        let current: String = connection
            .query_row(
                "SELECT operation_phase FROM runtime_sessions WHERE agent_session_id = ?1",
                [agent_session_id],
                |row| row.get(0),
            )
            .map_err(|error| format!("read Neko session phase failed: {error}"))?;
        let current = OperationPhase::parse(&current)
            .ok_or_else(|| "recorded Neko session has an invalid operation phase".to_string())?;
        if !can_advance_operation(current, phase) {
            return Err(format!(
                "invalid Neko session operation transition {} -> {}",
                current.as_str(),
                phase.as_str()
            ));
        }
        connection
            .execute(
                "UPDATE runtime_sessions SET operation_phase = ?2, updated_at = ?3
                   WHERE agent_session_id = ?1",
                params![agent_session_id, phase.as_str(), now()],
            )
            .map_err(|error| format!("update Neko session phase failed: {error}"))?;
        Ok(())
    }

    pub fn update_session(
        &self,
        agent_session_id: &str,
        next_state: RunState,
        phase: OperationPhase,
        continuity: &str,
        pid: Option<u32>,
        provider_version: Option<&str>,
    ) -> Result<(), String> {
        let connection = lock(&self.connection);
        let (current_state, current_phase): (String, String) = connection
            .query_row(
                "SELECT state, operation_phase FROM runtime_sessions
                  WHERE agent_session_id = ?1",
                [agent_session_id],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .map_err(|error| format!("read Neko session state failed: {error}"))?;
        let current_state = RunState::parse(&current_state)
            .ok_or_else(|| "recorded Neko session has an invalid state".to_string())?;
        let current_phase = OperationPhase::parse(&current_phase)
            .ok_or_else(|| "recorded Neko session has an invalid operation phase".to_string())?;
        if !can_transition(current_state, next_state) {
            return Err(format!(
                "invalid Neko run transition {} -> {}",
                current_state.as_str(),
                next_state.as_str()
            ));
        }
        if !can_advance_operation(current_phase, phase) {
            return Err(format!(
                "invalid Neko session operation transition {} -> {}",
                current_phase.as_str(),
                phase.as_str()
            ));
        }
        connection
            .execute(
                "UPDATE runtime_sessions
                    SET state = ?2, operation_phase = ?3, continuity = ?4, pid = ?5,
                        provider_version = COALESCE(?6, provider_version), updated_at = ?7
                  WHERE agent_session_id = ?1",
                params![
                    agent_session_id,
                    next_state.as_str(),
                    phase.as_str(),
                    continuity,
                    pid.map(i64::from),
                    provider_version,
                    now()
                ],
            )
            .map_err(|error| format!("update Neko session state failed: {error}"))?;
        Ok(())
    }

    pub fn session(&self, agent_session_id: &str) -> Result<Option<SessionRecord>, String> {
        lock(&self.connection)
            .query_row(
                "SELECT agent_session_id, task_id, run_id, environment_id, provider_id,
                        provider_version, workspace_path, state, operation_phase,
                        continuity, pid, created_at, updated_at
                   FROM runtime_sessions WHERE agent_session_id = ?1",
                [agent_session_id],
                session_from_row,
            )
            .optional()
            .map_err(|error| format!("read Neko session failed: {error}"))
    }

    pub fn sessions(&self, run_id: Option<&str>) -> Result<Vec<SessionRecord>, String> {
        let connection = lock(&self.connection);
        let mut records = Vec::new();
        if let Some(run_id) = run_id {
            let mut statement = connection
                .prepare(
                    "SELECT agent_session_id, task_id, run_id, environment_id, provider_id,
                            provider_version, workspace_path, state, operation_phase,
                            continuity, pid, created_at, updated_at
                       FROM runtime_sessions WHERE run_id = ?1 ORDER BY created_at, agent_session_id",
                )
                .map_err(|error| format!("prepare Neko session list failed: {error}"))?;
            let rows = statement
                .query_map([run_id], session_from_row)
                .map_err(|error| format!("list Neko sessions failed: {error}"))?;
            for row in rows {
                records.push(row.map_err(|error| format!("decode Neko session failed: {error}"))?);
            }
        } else {
            let mut statement = connection
                .prepare(
                    "SELECT agent_session_id, task_id, run_id, environment_id, provider_id,
                            provider_version, workspace_path, state, operation_phase,
                            continuity, pid, created_at, updated_at
                       FROM runtime_sessions ORDER BY created_at, agent_session_id",
                )
                .map_err(|error| format!("prepare Neko session list failed: {error}"))?;
            let rows = statement
                .query_map([], session_from_row)
                .map_err(|error| format!("list Neko sessions failed: {error}"))?;
            for row in rows {
                records.push(row.map_err(|error| format!("decode Neko session failed: {error}"))?);
            }
        }
        Ok(records)
    }

    pub fn append_event(
        &self,
        stream_id: &str,
        event_type: &str,
        run_id: &str,
        agent_session_id: Option<&str>,
        payload: Value,
    ) -> Result<ControlEvent, String> {
        validate_payload(&payload)?;
        let encoded = serde_json::to_string(&payload)
            .map_err(|error| format!("encode Neko control event failed: {error}"))?;
        let mut connection = lock(&self.connection);
        let transaction = connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(|error| format!("begin Neko event transaction failed: {error}"))?;
        let next: i64 = transaction
            .query_row(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM control_events WHERE stream_id = ?1",
                [stream_id],
                |row| row.get(0),
            )
            .map_err(|error| format!("allocate Neko event sequence failed: {error}"))?;
        let event = ControlEvent {
            v: 1,
            event_id: Uuid::new_v4().to_string(),
            stream_id: stream_id.to_string(),
            seq: next as u64,
            at: now(),
            event_type: event_type.to_string(),
            run_id: run_id.to_string(),
            agent_session_id: agent_session_id.map(str::to_string),
            payload,
        };
        transaction
            .execute(
                "INSERT INTO control_events
                   (event_id, stream_id, seq, at, event_type, run_id, agent_session_id, payload_json)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
                params![
                    event.event_id,
                    event.stream_id,
                    next,
                    event.at,
                    event.event_type,
                    event.run_id,
                    event.agent_session_id,
                    encoded
                ],
            )
            .map_err(|error| format!("append Neko control event failed: {error}"))?;
        transaction
            .commit()
            .map_err(|error| format!("commit Neko control event failed: {error}"))?;
        Ok(event)
    }

    pub fn replay(
        &self,
        stream_id: &str,
        after_seq: u64,
        limit: u32,
    ) -> Result<ReplayPage, String> {
        if !(1..=MAX_REPLAY_LIMIT).contains(&limit) {
            return Err(format!(
                "Neko replay limit must be between 1 and {MAX_REPLAY_LIMIT}"
            ));
        }
        if after_seq > i64::MAX as u64 {
            return Err("Neko replay cursor exceeds the durable sequence range".to_string());
        }
        let connection = lock(&self.connection);
        let mut statement = connection
            .prepare(
                "SELECT event_id, stream_id, seq, at, event_type, run_id,
                        agent_session_id, payload_json
                   FROM control_events
                  WHERE stream_id = ?1 AND seq > ?2
                  ORDER BY seq ASC LIMIT ?3",
            )
            .map_err(|error| format!("prepare Neko event replay failed: {error}"))?;
        let rows = statement
            .query_map(
                params![stream_id, after_seq as i64, i64::from(limit) + 1],
                |row| {
                    let payload: String = row.get(7)?;
                    Ok(ControlEvent {
                        v: 1,
                        event_id: row.get(0)?,
                        stream_id: row.get(1)?,
                        seq: row.get::<_, i64>(2)? as u64,
                        at: row.get(3)?,
                        event_type: row.get(4)?,
                        run_id: row.get(5)?,
                        agent_session_id: row.get(6)?,
                        payload: serde_json::from_str(&payload).map_err(|error| {
                            rusqlite::Error::FromSqlConversionFailure(
                                payload.len(),
                                rusqlite::types::Type::Text,
                                Box::new(error),
                            )
                        })?,
                    })
                },
            )
            .map_err(|error| format!("read Neko event replay failed: {error}"))?;
        let mut events = rows
            .collect::<Result<Vec<_>, _>>()
            .map_err(|error| format!("decode Neko event replay failed: {error}"))?;
        let has_more = events.len() > limit as usize;
        if has_more {
            events.pop();
        }
        let next_after_seq = events.last().map(|event| event.seq).unwrap_or(after_seq);
        Ok(ReplayPage {
            stream_id: stream_id.to_string(),
            events,
            next_after_seq,
            has_more,
        })
    }

    pub fn recover_incomplete(&self) -> Result<(), String> {
        let sessions = self.sessions(None)?;
        for session in sessions {
            if session.state.is_terminal() {
                continue;
            }
            let (state, phase, continuity, reason) =
                match recovery_disposition(session.operation_phase) {
                    RecoveryDisposition::ContinuityLost => (
                        RunState::Failed,
                        OperationPhase::Failed,
                        "continuity_lost",
                        "native_process_ownership_lost",
                    ),
                    RecoveryDisposition::UnknownOutcome => (
                        RunState::UnknownOutcome,
                        OperationPhase::UnknownOutcome,
                        "unknown_outcome",
                        "side_effect_outcome_unproven",
                    ),
                    RecoveryDisposition::Preserve => match session.operation_phase {
                        OperationPhase::Completed => (
                            RunState::Failed,
                            OperationPhase::Completed,
                            "continuity_lost",
                            "native_process_ownership_lost",
                        ),
                        OperationPhase::Failed => (
                            RunState::Failed,
                            OperationPhase::Failed,
                            "continuity_lost",
                            "recorded_failure",
                        ),
                        OperationPhase::UnknownOutcome => (
                            RunState::UnknownOutcome,
                            OperationPhase::UnknownOutcome,
                            "unknown_outcome",
                            "recorded_unknown_outcome",
                        ),
                        _ => unreachable!("non-terminal recovery disposition cannot be preserved"),
                    },
                };
            self.update_session(
                &session.agent_session_id,
                state,
                phase,
                continuity,
                None,
                None,
            )?;
            self.append_event(
                &session.run_id,
                "run.state_changed",
                &session.run_id,
                Some(&session.agent_session_id),
                json!({ "state": state.as_str(), "reason": reason }),
            )?;
        }

        let connection = lock(&self.connection);
        connection
            .execute(
                "UPDATE control_requests
                    SET phase = 'failed', error_code = 'continuity_lost', updated_at = ?1
                  WHERE phase IN ('accepted', 'dispatched')",
                [now()],
            )
            .map_err(|error| format!("recover safe Neko requests failed: {error}"))?;
        connection
            .execute(
                "UPDATE control_requests
                    SET phase = 'unknown_outcome', error_code = 'unknown_outcome', updated_at = ?1
                  WHERE phase IN ('side_effect_started', 'committed')",
                [now()],
            )
            .map_err(|error| format!("recover uncertain Neko requests failed: {error}"))?;
        Ok(())
    }
}

fn session_from_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<SessionRecord> {
    let state: String = row.get(7)?;
    let operation_phase: String = row.get(8)?;
    let pid = row.get::<_, Option<i64>>(10)?.map(|value| value as u32);
    Ok(SessionRecord {
        agent_session_id: row.get(0)?,
        task_id: row.get(1)?,
        run_id: row.get(2)?,
        environment_id: row.get(3)?,
        provider_id: row.get(4)?,
        provider_version: row.get(5)?,
        workspace_path: row.get(6)?,
        state: RunState::parse(&state).ok_or_else(|| {
            rusqlite::Error::FromSqlConversionFailure(
                state.len(),
                rusqlite::types::Type::Text,
                "invalid run state".into(),
            )
        })?,
        operation_phase: OperationPhase::parse(&operation_phase).ok_or_else(|| {
            rusqlite::Error::FromSqlConversionFailure(
                operation_phase.len(),
                rusqlite::types::Type::Text,
                "invalid operation phase".into(),
            )
        })?,
        continuity: row.get(9)?,
        pid,
        created_at: row.get(11)?,
        updated_at: row.get(12)?,
    })
}

fn validate_payload(value: &Value) -> Result<(), String> {
    fn visit(value: &Value, depth: usize) -> Result<(), String> {
        if depth > 4 {
            return Err("Neko control event payload is too deeply nested".to_string());
        }
        match value {
            Value::String(value) if value.len() > 512 => {
                return Err("Neko control event string exceeds the durable limit".to_string())
            }
            Value::Array(values) => {
                if values.len() > 32 {
                    return Err("Neko control event array exceeds the durable limit".to_string());
                }
                for value in values {
                    visit(value, depth + 1)?;
                }
            }
            Value::Object(values) => {
                if values.len() > 32 {
                    return Err("Neko control event object exceeds the durable limit".to_string());
                }
                for (key, value) in values {
                    let normalized = key.to_ascii_lowercase().replace(['-', '_'], "");
                    if [
                        "authorization",
                        "cookie",
                        "credential",
                        "password",
                        "secret",
                        "token",
                        "apikey",
                    ]
                    .iter()
                    .any(|needle| normalized.contains(needle))
                    {
                        return Err(
                            "secret-like Neko control event fields are forbidden".to_string()
                        );
                    }
                    visit(value, depth + 1)?;
                }
            }
            _ => {}
        }
        Ok(())
    }

    visit(value, 0)?;
    let encoded = serde_json::to_vec(value)
        .map_err(|error| format!("encode Neko control event failed: {error}"))?;
    if encoded.len() > MAX_EVENT_PAYLOAD_BYTES {
        return Err("Neko control event payload exceeds the durable limit".to_string());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn session<'a>(id: &'a str, run_id: &'a str) -> NewSession<'a> {
        NewSession {
            agent_session_id: id,
            task_id: "task-1",
            run_id,
            environment_id: "environment-1",
            provider_id: "codex",
            workspace_path: "C:/workspace",
        }
    }

    #[test]
    fn replays_one_stream_with_an_explicit_cursor() {
        let journal = Journal::in_memory();
        journal
            .insert_session(session("session-a", "run-a"))
            .unwrap();
        journal
            .insert_session(session("session-b", "run-b"))
            .unwrap();
        for index in 0..4 {
            let event = journal
                .append_event(
                    "run-a",
                    "run.state_changed",
                    "run-a",
                    Some("session-a"),
                    json!({ "index": index }),
                )
                .unwrap();
            assert_eq!(event.seq, index + 1);
            journal
                .append_event(
                    "run-b",
                    "run.state_changed",
                    "run-b",
                    Some("session-b"),
                    json!({ "index": index }),
                )
                .unwrap();
        }

        let page = journal.replay("run-a", 1, 2).unwrap();
        assert_eq!(
            page.events
                .iter()
                .map(|event| event.seq)
                .collect::<Vec<_>>(),
            [2, 3]
        );
        assert_eq!(page.next_after_seq, 3);
        assert!(page.has_more);
        assert!(page.events.iter().all(|event| event.stream_id == "run-a"));
    }

    #[test]
    fn request_identity_replays_results_and_rejects_collisions() {
        let journal = Journal::in_memory();
        assert_eq!(
            journal
                .begin_request("request-1", "session/start", "session-1")
                .unwrap(),
            RequestDecision::Execute
        );
        journal
            .set_request_phase("request-1", OperationPhase::Dispatched)
            .unwrap();
        journal
            .set_request_phase("request-1", OperationPhase::SideEffectStarted)
            .unwrap();
        journal
            .set_request_phase("request-1", OperationPhase::Committed)
            .unwrap();
        journal
            .complete_request("request-1", &json!({ "agentSessionId": "session-1" }))
            .unwrap();
        assert_eq!(
            journal
                .begin_request("request-1", "session/start", "session-1")
                .unwrap(),
            RequestDecision::Replay(json!({ "agentSessionId": "session-1" }))
        );
        assert!(journal
            .begin_request("request-1", "session/cancel", "session-1")
            .is_err());
    }

    #[test]
    fn recovery_marks_uncertain_side_effects_without_retrying() {
        let journal = Journal::in_memory();
        journal.insert_session(session("safe", "run-safe")).unwrap();
        journal
            .insert_session(session("uncertain", "run-uncertain"))
            .unwrap();
        journal
            .set_session_phase("safe", OperationPhase::Dispatched)
            .unwrap();
        journal
            .set_session_phase("uncertain", OperationPhase::Dispatched)
            .unwrap();
        journal
            .set_session_phase("uncertain", OperationPhase::SideEffectStarted)
            .unwrap();
        journal.recover_incomplete().unwrap();

        let safe = journal.session("safe").unwrap().unwrap();
        assert_eq!(safe.state, RunState::Failed);
        assert_eq!(safe.continuity, "continuity_lost");
        let uncertain = journal.session("uncertain").unwrap().unwrap();
        assert_eq!(uncertain.state, RunState::UnknownOutcome);
        assert_eq!(uncertain.continuity, "unknown_outcome");
    }

    #[test]
    fn session_updates_validate_state_and_operation_phase_independently() {
        let journal = Journal::in_memory();
        journal
            .insert_session(session("session-a", "run-a"))
            .unwrap();
        journal
            .set_session_phase("session-a", OperationPhase::Dispatched)
            .unwrap();
        journal
            .set_session_phase("session-a", OperationPhase::SideEffectStarted)
            .unwrap();
        journal
            .update_session(
                "session-a",
                RunState::Running,
                OperationPhase::Committed,
                "active",
                Some(42),
                Some("test-version"),
            )
            .unwrap();

        assert!(journal
            .update_session(
                "session-a",
                RunState::Starting,
                OperationPhase::Committed,
                "active",
                Some(42),
                None,
            )
            .is_err());
        assert!(journal
            .update_session(
                "session-a",
                RunState::Running,
                OperationPhase::Dispatched,
                "active",
                Some(42),
                None,
            )
            .is_err());
    }

    #[test]
    fn replay_rejects_invalid_limits_and_unrepresentable_cursors() {
        let journal = Journal::in_memory();
        assert!(journal.replay("run-a", 0, 0).is_err());
        assert!(journal.replay("run-a", 0, 501).is_err());
        assert!(journal.replay("run-a", i64::MAX as u64 + 1, 1).is_err());
    }

    #[test]
    fn durable_payload_rejects_secret_like_fields_and_unbounded_text() {
        let journal = Journal::in_memory();
        journal
            .insert_session(session("session-a", "run-a"))
            .unwrap();
        assert!(journal
            .append_event(
                "run-a",
                "session.started",
                "run-a",
                Some("session-a"),
                json!({ "apiToken": "do-not-store" }),
            )
            .is_err());
        assert!(journal
            .append_event(
                "run-a",
                "session.started",
                "run-a",
                Some("session-a"),
                json!({ "detail": "x".repeat(513) }),
            )
            .is_err());
    }

    #[test]
    fn file_database_uses_wal() {
        let path = std::env::temp_dir().join(format!("wiii-neko-{}.sqlite3", Uuid::new_v4()));
        {
            let journal = Journal::open(&path).unwrap();
            assert_eq!(journal.journal_mode().unwrap().to_ascii_lowercase(), "wal");
        }
        let _ = std::fs::remove_file(&path);
        let _ = std::fs::remove_file(path.with_extension("sqlite3-wal"));
        let _ = std::fs::remove_file(path.with_extension("sqlite3-shm"));
    }
}
