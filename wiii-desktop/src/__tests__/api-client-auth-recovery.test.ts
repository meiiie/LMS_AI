import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiHttpError, WiiiClient } from "@/api/client";

function jsonResponse(status: number, body: Record<string, unknown>) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function streamResponse() {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode("event: done\ndata: {}\n\n"));
        controller.close();
      },
    }),
    { status: 200 },
  );
}

describe("WiiiClient auth recovery", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("retries stream requests after recoverable organization-context 403", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse(403, {
          detail: "Active organization does not match authenticated organization.",
        }),
      )
      .mockResolvedValueOnce(streamResponse());
    vi.stubGlobal("fetch", fetchMock);

    const client = new WiiiClient("https://wiii.example");
    const recover = vi.fn().mockResolvedValue(true);
    client.setOnUnauthorized(recover);

    const stream = await client.postStream("/api/v1/chat/stream/v3", {
      message: "xin chao",
    });

    expect(stream).toBeTruthy();
    expect(recover).toHaveBeenCalledWith(
      expect.objectContaining({
        status: 403,
        detail: "Active organization does not match authenticated organization.",
      }),
    );
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("does not treat ordinary authorization 403 as stale auth", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(403, { detail: "Admin access required" }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new WiiiClient("https://wiii.example");
    const recover = vi.fn().mockResolvedValue(true);
    client.setOnUnauthorized(recover);

    await expect(client.get("/api/v1/admin/domains")).rejects.toMatchObject({
      name: "ApiHttpError",
      status: 403,
      message: "Admin access required",
    } satisfies Partial<ApiHttpError>);
    expect(recover).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("keeps existing 401 refresh-and-retry behavior", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(401, { detail: "Invalid or expired token" }))
      .mockResolvedValueOnce(jsonResponse(200, { ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new WiiiClient("https://wiii.example");
    const recover = vi.fn().mockResolvedValue(true);
    client.setOnUnauthorized(recover);

    const result = await client.get<{ ok: boolean }>("/api/v1/context/info");

    expect(result.ok).toBe(true);
    expect(recover).toHaveBeenCalledWith(
      expect.objectContaining({
        status: 401,
        detail: "Invalid or expired token",
      }),
    );
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
