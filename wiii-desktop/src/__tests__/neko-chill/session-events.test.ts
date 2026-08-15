import { describe, expect, it } from "vitest";
import {
  appendSessionEvent,
  isNekoSessionEvent,
  type NekoSessionEvent,
} from "@/neko-chill/session-events";

function event(data: NekoSessionEvent["data"]): NekoSessionEvent {
  const events: NekoSessionEvent[] = [];
  return appendSessionEvent(events, "model", data, 100);
}

describe("Neko session event validation", () => {
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
