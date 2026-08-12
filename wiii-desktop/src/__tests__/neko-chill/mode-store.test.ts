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

  it("defaults to the cloud mode on first launch", async () => {
    await useModeStore.getState().loadMode();
    expect(useModeStore.getState().mode).toBe("wiii");
    expect(useModeStore.getState().isLoaded).toBe(true);
  });

  it("persists a selection across reloads", async () => {
    await useModeStore.getState().setMode("neko-chill");
    useModeStore.setState({ mode: "wiii", isLoaded: false });
    await useModeStore.getState().loadMode();
    expect(useModeStore.getState().mode).toBe("neko-chill");
  });

  it("falls back to cloud mode on corrupt stored values", async () => {
    storage.set("neko-chill-mode.json:mode", "banana");
    await useModeStore.getState().loadMode();
    expect(useModeStore.getState().mode).toBe("wiii");
    expect(useModeStore.getState().isLoaded).toBe(true);
  });
});
