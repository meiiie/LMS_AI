import { describe, expect, it } from "vitest";
import {
  NEKO_CONTROL_PROTOCOL_VERSION,
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
