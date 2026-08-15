/**
 * T102 — mode-store: persisted shell-level mode selection (FR-001).
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

const storage = new Map<string, unknown>();

vi.mock("@/lib/storage", () => ({
  loadStore: vi.fn(async (store: string, key: string, dflt: unknown) => {
    const hit = storage.get(`${store}:${key}`);
    return hit === undefined ? dflt : hit;
  }),
  saveStore: vi.fn(async (store: string, key: string, value: unknown) => {
    storage.set(`${store}:${key}`, value);
  }),
}));

import { useModeStore } from "@/neko-chill/stores/mode-store";

describe("mode-store", () => {
  beforeEach(() => {
    storage.clear();
    useModeStore.setState({ mode: "wiii", isLoaded: false });
  });

  it("fresh install (no mode, no account) lands in Neko Chill (#893)", async () => {
    await useModeStore.getState().loadMode();
    expect(useModeStore.getState().mode).toBe("neko-chill");
    expect(useModeStore.getState().isLoaded).toBe(true);
  });

  it("no persisted mode but a stored account lands in the cloud app", async () => {
    storage.set("auth_state:data", { user: { id: "u1" }, authMode: "oauth" });
    await useModeStore.getState().loadMode();
    expect(useModeStore.getState().mode).toBe("wiii");
  });

  it("persists a selection across reloads and it beats the auth heuristic", async () => {
    storage.set("auth_state:data", { user: { id: "u1" }, authMode: "oauth" });
    await useModeStore.getState().setMode("neko-chill");
    useModeStore.setState({ mode: "wiii", isLoaded: false });
    await useModeStore.getState().loadMode();
    expect(useModeStore.getState().mode).toBe("neko-chill");
  });

  it("corrupt stored values resolve like a fresh install", async () => {
    storage.set("neko-chill-mode.json:mode", "banana");
    await useModeStore.getState().loadMode();
    expect(useModeStore.getState().mode).toBe("neko-chill");
    expect(useModeStore.getState().isLoaded).toBe(true);
  });
});
