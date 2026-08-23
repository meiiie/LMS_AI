import { describe, expect, it } from "vitest";
import {
  appendSessionEvent,
  isNekoSessionEvent,
  type NekoSessionEvent,
} from "@/neko-chill/session-events";
import { createProviderCapabilitySnapshot } from "@/neko/provider-registry";

function event(data: NekoSessionEvent["data"]): NekoSessionEvent {
  const events: NekoSessionEvent[] = [];
  return appendSessionEvent(events, "model", data, 100);
}

describe("Neko session event validation", () => {
  const legacyProvider = {
    sessionId: "session-1",
    providerId: "neko",
    instanceId: "provider-1",
    kind: "acp" as const,
    backendSessionId: "backend-1",
    capabilities: ["prompt" as const],
    contextContinuity: "resumable" as const,
    workspaceIsolation: "advisory" as const,
  };

  it("round-trips a historical capability snapshot and accepts legacy events", () => {
    const legacy = event({ type: "runtime-attached", provider: legacyProvider });
    expect(isNekoSessionEvent(JSON.parse(JSON.stringify(legacy)))).toBe(true);

    const attached = event({
      type: "runtime-attached",
      provider: {
        ...legacyProvider,
        providerCapabilities: createProviderCapabilitySnapshot({
          providerId: "neko",
          providerVersion: "0.24.17",
          established: { resume: true, approvals: true },
        }),
      },
    });
    const restored = JSON.parse(JSON.stringify(attached));
    expect(isNekoSessionEvent(restored)).toBe(true);
    expect(restored.data.provider.providerCapabilities).toEqual(
      attached.data.type === "runtime-attached"
        ? attached.data.provider.providerCapabilities
        : undefined,
    );
  });

  it("rejects a malformed capability snapshot instead of ignoring it", () => {
    const attached = event({
      type: "runtime-attached",
      provider: {
        ...legacyProvider,
        providerCapabilities: createProviderCapabilitySnapshot({
          providerId: "neko",
          providerVersion: null,
        }),
      },
    });
    const malformed = JSON.parse(JSON.stringify(attached));
    malformed.data.provider.providerCapabilities.capabilities.resume = "yes";

    expect(isNekoSessionEvent(malformed)).toBe(false);
  });

  it("accepts complete discriminated payloads", () => {
    const appended = event({
      type: "model-input",
      source: "live",
      messageId: "m1",
      text: "xin chào",
      providerInstanceId: "provider-1",
    });
    expect(appended.eventId).toEqual(expect.any(String));
    expect(isNekoSessionEvent(appended)).toBe(true);
    expect(isNekoSessionEvent({ ...appended, eventId: undefined })).toBe(true);
    expect(isNekoSessionEvent({ ...appended, eventId: "" })).toBe(false);

    expect(isNekoSessionEvent(event({
      type: "dispatch-invoked",
      targetEventId: appended.eventId!,
      action: "prompt",
      providerInstanceId: "provider-1",
    }))).toBe(true);

    expect(isNekoSessionEvent(event({
      type: "knowledge-context",
      source: "wiii-knowledge",
      contextId: "context-1",
      query: "rule 15",
      renderedContext: "[1] evidence",
      sources: [{
        sourceId: "chunk-1",
        title: "COLREG",
        documentId: "colreg.pdf",
        pageNumber: 15,
        score: 0.9,
      }],
      providerInstanceId: "provider-1",
      delivery: "staged",
    }))).toBe(true);

    expect(isNekoSessionEvent(event({
      type: "native-runtime-reconciled",
      agentSessionId: "native-session-1",
      runId: "run-1",
      providerId: "neko",
      state: "unknown_outcome",
      operationPhase: "unknown_outcome",
      continuity: "unknown_outcome",
      replayedFromSeq: 2,
      replayedThroughSeq: 7,
      replayedEventCount: 5,
    }))).toBe(true);

    expect(isNekoSessionEvent(event({
      type: "native-runtime-retired",
      agentSessionId: "native-session-1",
      runId: "run-1",
      reason: "projection-pruned",
    }))).toBe(true);

    expect(isNekoSessionEvent(event({
      type: "native-runtime-cleanup-uncertain",
      agentSessionId: "native-session-1",
      runId: "run-1",
      providerId: "neko",
      reason: "unknown_outcome: cancellation response was lost",
    }))).toBe(true);
  });

  it.each([
    { type: "model-input", source: "live", messageId: "m1" },
    { type: "permission-decision", requestId: "p1", optionId: "allow" },
    { type: "runtime-command", action: "stop", providerInstanceId: "provider-1" },
    { type: "dispatch-invoked", targetEventId: "", action: "prompt", providerInstanceId: "provider-1" },
    { type: "dispatch-invoked", targetEventId: "event-1", action: "config", providerInstanceId: "provider-1" },
    { type: "model-input", source: "live", messageId: "m1", text: "x", providerInstanceId: "provider-1", delivery: "sent" },
    { type: "control-change", phase: "committed", optionId: "model" },
    { type: "runtime-attached", provider: { instanceId: "provider-1" } },
    { type: "runtime-detached", providerId: "neko", instanceId: "provider-1" },
    { type: "runtime-attach-failed", providerId: "neko" },
    {
      type: "native-runtime-reconciled",
      agentSessionId: "native-session-1",
      runId: "run-1",
      providerId: "neko",
      state: "running",
      operationPhase: "committed",
      continuity: "active",
      replayedFromSeq: 5,
      replayedThroughSeq: 4,
      replayedEventCount: 0,
    },
    {
      type: "native-runtime-retired",
      agentSessionId: "native-session-1",
      runId: "run-1",
      reason: "forgotten",
    },
    {
      type: "native-runtime-cleanup-uncertain",
      agentSessionId: "native-session-1",
      runId: "run-1",
      providerId: "neko",
      reason: "",
    },
  ])("rejects a malformed $type payload", (data) => {
    expect(isNekoSessionEvent({
      v: 1,
      seq: 1,
      at: 100,
      visibility: "model",
      data,
    })).toBe(false);
  });

  it.each([null, undefined, [], "model-input", 1])(
    "rejects a non-object event payload: %s",
    (data) => {
      expect(isNekoSessionEvent({
        v: 1,
        seq: 1,
        at: 100,
        visibility: "model",
        data,
      })).toBe(false);
    },
  );

  it("rejects inherited object keys as provider capabilities", () => {
    const attached = event({
      type: "runtime-attached",
      provider: {
        sessionId: "session-1",
        providerId: "neko",
        instanceId: "provider-1",
        kind: "acp",
        capabilities: ["toString" as "prompt"],
        contextContinuity: "process",
        workspaceIsolation: "advisory",
      },
    });

    expect(isNekoSessionEvent(attached)).toBe(false);
  });
});
