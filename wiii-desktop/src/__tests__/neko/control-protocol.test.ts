import { describe, expect, it } from "vitest";
import {
  NEKO_CONTROL_PROTOCOL_VERSION,
  isNekoControlEvent,
  isNekoControlReplayPage,
  isNekoControlResponse,
  parseNekoControlRequest,
} from "@/neko/control-protocol";

describe("Neko Control Protocol", () => {
  it("accepts a versioned provider discovery request", () => {
    expect(parseNekoControlRequest({
      v: NEKO_CONTROL_PROTOCOL_VERSION,
      requestId: "request-1",
      method: "provider/list",
      params: {},
    })).toEqual({
      ok: true,
      request: {
        v: 1,
        requestId: "request-1",
        method: "provider/list",
        params: {},
      },
    });
  });

  it("rejects an unknown protocol version before dispatch", () => {
    expect(parseNekoControlRequest({
      v: 2,
      requestId: "request-2",
      method: "provider/list",
      params: {},
    })).toEqual(expect.objectContaining({
      ok: false,
      error: expect.objectContaining({ code: "unsupported_version" }),
    }));
  });

  it("rejects unknown methods before side effects", () => {
    expect(parseNekoControlRequest({
      v: 1,
      requestId: "request-3",
      method: "provider/delete-everything",
      params: {},
    })).toEqual(expect.objectContaining({
      ok: false,
      error: expect.objectContaining({ code: "unsupported_method" }),
    }));
  });

  it("rejects incomplete session start identities", () => {
    expect(parseNekoControlRequest({
      v: 1,
      requestId: "request-4",
      method: "session/start",
      params: { providerId: "codex" },
    })).toEqual(expect.objectContaining({
      ok: false,
      error: expect.objectContaining({ code: "invalid_request" }),
    }));
  });

  it("rejects an unknown provider before session dispatch", () => {
    expect(parseNekoControlRequest({
      v: 1,
      requestId: "request-unknown-provider",
      method: "session/start",
      params: {
        agentSessionId: "session-1",
        taskId: "task-1",
        runId: "run-1",
        providerId: "unknown-provider",
        environmentId: "environment-1",
        workspacePath: "C:/project",
      },
    })).toEqual(expect.objectContaining({
      ok: false,
      error: expect.objectContaining({ code: "invalid_request" }),
    }));
  });

  it("defines ordering inside a durable run stream", () => {
    expect(isNekoControlEvent({
      v: 1,
      eventId: "event-1",
      streamId: "run-1",
      seq: 7,
      at: "2026-08-23T00:00:00Z",
      type: "session.started",
      runId: "run-1",
      agentSessionId: "session-1",
      payload: {},
    })).toBe(true);
    expect(isNekoControlEvent({
      v: 1,
      eventId: "event-1",
      seq: 7,
      at: "2026-08-23T00:00:00Z",
      type: "session.started",
      runId: "run-1",
      payload: {},
    })).toBe(false);
  });

  it("validates replay cursors and strictly ordered stream-local events", () => {
    const events = [7, 8].map((seq) => ({
      v: 1,
      eventId: `event-${seq}`,
      streamId: "run-1",
      seq,
      at: "2026-08-23T00:00:00Z",
      type: "run.state_changed",
      runId: "run-1",
      payload: { state: "running" },
    }));
    expect(isNekoControlReplayPage({
      streamId: "run-1",
      events,
      nextAfterSeq: 8,
      hasMore: true,
    }, "run-1", 6)).toBe(true);
    expect(isNekoControlReplayPage({
      streamId: "run-1",
      events: [events[1], events[0]],
      nextAfterSeq: 7,
      hasMore: false,
    }, "run-1", 6)).toBe(false);
    expect(isNekoControlReplayPage({
      streamId: "another-run",
      events: [],
      nextAfterSeq: 6,
      hasMore: false,
    }, "run-1", 6)).toBe(false);
  });

  it("rejects profile discovery for providers outside the registry", () => {
    expect(parseNekoControlRequest({
      v: 1,
      requestId: "request-profile",
      method: "provider/profiles",
      params: { providerId: "unknown", workspacePath: "C:/project" },
    })).toEqual(expect.objectContaining({
      ok: false,
      error: expect.objectContaining({ code: "invalid_request" }),
    }));
  });

  it("requires responses to contain exactly one result or typed error", () => {
    expect(isNekoControlResponse({
      v: 1,
      requestId: "request-5",
      result: { providers: [] },
    })).toBe(true);
    expect(isNekoControlResponse({
      v: 1,
      requestId: "request-5",
      result: null,
      error: { code: "internal_error", message: "ambiguous" },
    })).toBe(false);
    expect(isNekoControlResponse({
      v: 1,
      requestId: "request-5",
      error: { code: "made_up", message: "unknown" },
    })).toBe(false);
  });
});
