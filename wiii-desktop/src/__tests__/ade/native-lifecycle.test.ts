import { describe, expect, it } from "vitest";
import {
  deriveAdeOutcomeFromNativeRecord,
  deriveAdeOutcomeFromSessionEvents,
  nativeOutcomeTransitionPath,
} from "@/ade/native-lifecycle";
import type { NekoSessionEvent } from "@/neko-chill/session-events";

function reconciled(
  state: string,
  operationPhase = "completed",
  continuity = "active",
): NekoSessionEvent {
  return {
    v: 1,
    eventId: `event-${state}`,
    seq: 1,
    at: 1,
    visibility: "runtime",
    data: {
      type: "native-runtime-reconciled",
      agentSessionId: "agent-1",
      runId: "run-1",
      providerId: "codex",
      state,
      operationPhase,
      continuity,
      replayedFromSeq: 0,
      replayedThroughSeq: 1,
      replayedEventCount: 1,
    },
  };
}

describe("ADE projection of native Neko lifecycle", () => {
  it("sends provider completion to review instead of self-approving the Task", () => {
    expect(deriveAdeOutcomeFromSessionEvents([reconciled("completed")], "run-1"))
      .toBe("review");
    expect(nativeOutcomeTransitionPath("running", "review"))
      .toEqual(["verifying", "review"]);
  });

  it("preserves failed, cancelled and uncertain terminal truth", () => {
    expect(deriveAdeOutcomeFromNativeRecord({
      agentSessionId: "agent-1",
      taskId: "task-1",
      runId: "run-1",
      environmentId: "env-1",
      providerId: "codex",
      providerVersion: null,
      workspacePath: "C:\\src\\wiii",
      state: "failed",
      operationPhase: "failed",
      continuity: "active",
      pid: null,
      createdAt: "2026-08-24T00:00:00Z",
      updatedAt: "2026-08-24T00:01:00Z",
    })).toBe("failed");
    expect(deriveAdeOutcomeFromSessionEvents([reconciled("cancelled")], "run-1"))
      .toBe("cancelled");
    expect(deriveAdeOutcomeFromSessionEvents([
      reconciled("completed", "unknown_outcome", "unknown_outcome"),
    ], "run-1")).toBe("unknown_outcome");
  });

  it("treats unresolved cleanup as unknown but honors a later resolution", () => {
    const uncertain: NekoSessionEvent = {
      v: 1,
      eventId: "event-2",
      seq: 2,
      at: 2,
      visibility: "runtime",
      data: {
        type: "native-runtime-cleanup-uncertain",
        agentSessionId: "agent-1",
        runId: "run-1",
        providerId: "codex",
        reason: "termination was not proven",
      },
    };
    const resolved: NekoSessionEvent = {
      v: 1,
      eventId: "event-3",
      seq: 3,
      at: 3,
      visibility: "runtime",
      data: {
        type: "native-runtime-cleanup-resolved",
        agentSessionId: "agent-1",
        runId: "run-1",
        providerId: "codex",
      },
    };

    expect(deriveAdeOutcomeFromSessionEvents([reconciled("completed"), uncertain], "run-1"))
      .toBe("unknown_outcome");
    expect(deriveAdeOutcomeFromSessionEvents([
      reconciled("completed"),
      uncertain,
      resolved,
    ], "run-1")).toBe("review");
  });
});
