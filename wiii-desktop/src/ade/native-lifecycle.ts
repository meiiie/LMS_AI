import type { NekoNativeSessionRecord } from "@/neko/control-client";
import type { NekoSessionEvent } from "@/neko-chill/session-events";
import type { AdeRunState } from "./domain";

export type AdeNativeOutcome = "review" | "failed" | "cancelled" | "unknown_outcome";

interface NativeLifecycleFact {
  state: string;
  operationPhase: string;
  continuity: string;
}

function outcomeFromFact(fact: NativeLifecycleFact): AdeNativeOutcome | null {
  if (
    fact.state === "unknown_outcome" ||
    fact.operationPhase === "unknown_outcome" ||
    fact.continuity === "unknown_outcome"
  ) {
    return "unknown_outcome";
  }
  if (fact.state === "cancelled") return "cancelled";
  if (fact.state === "failed" || fact.operationPhase === "failed") return "failed";
  // Provider execution ending is evidence for human review, not proof that the
  // Wiii Task met its acceptance criteria.
  if (fact.state === "completed") return "review";
  return null;
}

export function deriveAdeOutcomeFromNativeRecord(
  record: NekoNativeSessionRecord,
): AdeNativeOutcome | null {
  return outcomeFromFact(record);
}

export function deriveAdeOutcomeFromSessionEvents(
  events: readonly NekoSessionEvent[],
  runId: string,
): AdeNativeOutcome | null {
  const cleanupResolved = new Set<string>();
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const data = events[index].data;
    if (!("runId" in data) || data.runId !== runId) continue;
    if (
      data.type === "native-runtime-cleanup-resolved" ||
      data.type === "native-runtime-retired"
    ) {
      cleanupResolved.add(data.agentSessionId);
      continue;
    }
    if (data.type === "native-runtime-cleanup-uncertain") {
      if (!cleanupResolved.has(data.agentSessionId)) return "unknown_outcome";
      continue;
    }
    if (data.type === "native-runtime-reconciled") return outcomeFromFact(data);
  }
  return null;
}

/** Legal ADE transitions required to project one authoritative native outcome. */
export function nativeOutcomeTransitionPath(
  from: AdeRunState,
  outcome: AdeNativeOutcome,
): AdeRunState[] {
  if (["completed", "failed", "cancelled", "unknown_outcome"].includes(from)) return [];
  if (from === outcome) return [];

  if (outcome !== "review") {
    return from === "queued" ? ["starting", outcome] : [outcome];
  }

  if (from === "review") return [];
  if (from === "queued") return ["starting", "running", "verifying", "review"];
  if (from === "starting") return ["running", "verifying", "review"];
  if (from === "waiting") return ["running", "verifying", "review"];
  if (from === "running") return ["verifying", "review"];
  if (from === "verifying") return ["review"];
  return [];
}
