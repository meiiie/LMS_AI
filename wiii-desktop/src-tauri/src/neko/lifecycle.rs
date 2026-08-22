use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RunState {
    Queued,
    Starting,
    Running,
    Waiting,
    Verifying,
    Review,
    Completed,
    Failed,
    Cancelled,
    UnknownOutcome,
}

impl RunState {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Queued => "queued",
            Self::Starting => "starting",
            Self::Running => "running",
            Self::Waiting => "waiting",
            Self::Verifying => "verifying",
            Self::Review => "review",
            Self::Completed => "completed",
            Self::Failed => "failed",
            Self::Cancelled => "cancelled",
            Self::UnknownOutcome => "unknown_outcome",
        }
    }

    pub fn parse(value: &str) -> Option<Self> {
        Some(match value {
            "queued" => Self::Queued,
            "starting" => Self::Starting,
            "running" => Self::Running,
            "waiting" => Self::Waiting,
            "verifying" => Self::Verifying,
            "review" => Self::Review,
            "completed" => Self::Completed,
            "failed" => Self::Failed,
            "cancelled" => Self::Cancelled,
            "unknown_outcome" => Self::UnknownOutcome,
            _ => return None,
        })
    }

    pub fn is_terminal(self) -> bool {
        matches!(
            self,
            Self::Completed | Self::Failed | Self::Cancelled | Self::UnknownOutcome
        )
    }
}

pub fn can_transition(from: RunState, to: RunState) -> bool {
    if from == to {
        return true;
    }
    matches!(
        (from, to),
        (RunState::Queued, RunState::Starting | RunState::Cancelled)
            | (
                RunState::Starting,
                RunState::Running
                    | RunState::Failed
                    | RunState::Cancelled
                    | RunState::UnknownOutcome
            )
            | (
                RunState::Running,
                RunState::Waiting
                    | RunState::Verifying
                    | RunState::Failed
                    | RunState::Cancelled
                    | RunState::UnknownOutcome
            )
            | (
                RunState::Waiting,
                RunState::Running
                    | RunState::Failed
                    | RunState::Cancelled
                    | RunState::UnknownOutcome
            )
            | (
                RunState::Verifying,
                RunState::Running
                    | RunState::Review
                    | RunState::Failed
                    | RunState::Cancelled
                    | RunState::UnknownOutcome
            )
            | (
                RunState::Review,
                RunState::Completed
                    | RunState::Failed
                    | RunState::Cancelled
                    | RunState::UnknownOutcome
            )
    )
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum OperationPhase {
    Accepted,
    Dispatched,
    SideEffectStarted,
    Committed,
    Completed,
    Failed,
    UnknownOutcome,
}

impl OperationPhase {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Accepted => "accepted",
            Self::Dispatched => "dispatched",
            Self::SideEffectStarted => "side_effect_started",
            Self::Committed => "committed",
            Self::Completed => "completed",
            Self::Failed => "failed",
            Self::UnknownOutcome => "unknown_outcome",
        }
    }

    pub fn parse(value: &str) -> Option<Self> {
        Some(match value {
            "accepted" => Self::Accepted,
            "dispatched" => Self::Dispatched,
            "side_effect_started" => Self::SideEffectStarted,
            "committed" => Self::Committed,
            "completed" => Self::Completed,
            "failed" => Self::Failed,
            "unknown_outcome" => Self::UnknownOutcome,
            _ => return None,
        })
    }
}

pub fn can_advance_operation(from: OperationPhase, to: OperationPhase) -> bool {
    if from == to {
        return true;
    }
    matches!(
        (from, to),
        (
            OperationPhase::Accepted,
            OperationPhase::Dispatched | OperationPhase::Failed
        ) | (
            OperationPhase::Dispatched,
            OperationPhase::SideEffectStarted | OperationPhase::Failed
        ) | (
            OperationPhase::SideEffectStarted,
            OperationPhase::Committed | OperationPhase::Failed | OperationPhase::UnknownOutcome
        ) | (
            OperationPhase::Committed,
            OperationPhase::Completed | OperationPhase::Failed | OperationPhase::UnknownOutcome
        )
    )
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RecoveryDisposition {
    Preserve,
    ContinuityLost,
    UnknownOutcome,
}

pub fn recovery_disposition(phase: OperationPhase) -> RecoveryDisposition {
    match phase {
        OperationPhase::Accepted | OperationPhase::Dispatched => {
            RecoveryDisposition::ContinuityLost
        }
        OperationPhase::SideEffectStarted | OperationPhase::Committed => {
            RecoveryDisposition::UnknownOutcome
        }
        OperationPhase::Completed | OperationPhase::Failed | OperationPhase::UnknownOutcome => {
            RecoveryDisposition::Preserve
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn terminal_runs_cannot_be_reopened() {
        for terminal in [
            RunState::Completed,
            RunState::Failed,
            RunState::Cancelled,
            RunState::UnknownOutcome,
        ] {
            assert!(!can_transition(terminal, RunState::Running));
        }
    }

    #[test]
    fn run_transition_matrix_keeps_retry_outside_the_run() {
        assert!(can_transition(RunState::Queued, RunState::Starting));
        assert!(can_transition(RunState::Running, RunState::Verifying));
        assert!(can_transition(RunState::Verifying, RunState::Review));
        assert!(can_transition(RunState::Review, RunState::Completed));
        assert!(!can_transition(RunState::Failed, RunState::Starting));
        assert!(!can_transition(RunState::Completed, RunState::Running));
    }

    #[test]
    fn recovery_never_replays_an_uncertain_side_effect() {
        assert_eq!(
            recovery_disposition(OperationPhase::Accepted),
            RecoveryDisposition::ContinuityLost
        );
        assert_eq!(
            recovery_disposition(OperationPhase::Dispatched),
            RecoveryDisposition::ContinuityLost
        );
        assert_eq!(
            recovery_disposition(OperationPhase::SideEffectStarted),
            RecoveryDisposition::UnknownOutcome
        );
        assert_eq!(
            recovery_disposition(OperationPhase::Committed),
            RecoveryDisposition::UnknownOutcome
        );
    }
}
