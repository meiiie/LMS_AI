/**
 * #893 — the login wall must never be a dead end: the escape hatch switches
 * the shell mode to Neko Chill (no account required).
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";

if (typeof window !== "undefined" && !window.matchMedia) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

const storage = new Map<string, unknown>();
vi.mock("@/lib/storage", () => ({
  loadStore: vi.fn(async (store: string, key: string, dflt: unknown) => {
    const hit = storage.get(`${store}:${key}`);
    return hit === undefined ? dflt : hit;
  }),
  saveStore: vi.fn(async (store: string, key: string, value: unknown) => {
    storage.set(`${store}:${key}`, value);
  }),
  deleteStore: vi.fn(async () => {}),
  clearStore: vi.fn(async () => {}),
}));

vi.mock("@/components/common/WiiiAvatar", () => ({
  WiiiAvatar: () => <span data-testid="avatar-stub" />,
}));

import { LoginScreen } from "@/components/auth/LoginScreen";
import { useModeStore } from "@/neko-chill/stores/mode-store";

describe("LoginScreen — Neko Chill escape hatch (#893)", () => {
  beforeEach(() => {
    cleanup();
    storage.clear();
    useModeStore.setState({ mode: "wiii", isLoaded: true });
  });

  it("switches the shell mode to neko-chill and persists it", async () => {
    render(<LoginScreen />);
    const escape = await screen.findByTestId("login-neko-chill-escape");
    expect(escape.textContent).toContain("Neko Chill");

    fireEvent.click(escape);

    expect(useModeStore.getState().mode).toBe("neko-chill");
    // The selection persists so the next launch lands there directly.
    await vi.waitFor(() => {
      expect(storage.get("neko-chill-mode.json:mode")).toBe("neko-chill");
    });
  });
});
