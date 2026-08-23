import type { AdeRunState } from "./domain";

const TRANSITIONS: Readonly<Record<AdeRunState, readonly AdeRunState[]>> = {
  queued: ["starting", "cancelled"],
  starting: ["running", "failed", "cancelled", "unknown_outcome"],
  running: ["waiting", "verifying", "failed", "cancelled", "unknown_outcome"],
  waiting: ["running", "failed", "cancelled", "unknown_outcome"],
  verifying: ["running", "review", "failed", "cancelled", "unknown_outcome"],
  review: ["completed", "failed", "cancelled", "unknown_outcome"],
  completed: [],
  failed: [],
  cancelled: [],
  unknown_outcome: [],
};

export interface AdeRunTransitionDiagnostic {
  code: "invalid_run_transition";
  from: AdeRunState;
  to: AdeRunState;
}

/** Lifecycle correctness stays separate from graph/reference correctness. */
export function validateAdeRunTransition(
  from: AdeRunState,
  to: AdeRunState,
): AdeRunTransitionDiagnostic | null {
  if (from === to || TRANSITIONS[from].includes(to)) return null;
  return { code: "invalid_run_transition", from, to };
}
