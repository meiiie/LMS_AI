/**
 * T204 — ModeGate: entering Neko Chill mounts the local surface INSTEAD of
 * the cloud app (FR-001/FR-002). The no-login guarantee is structural:
 * WiiiCloudApp (and with it every cloud init effect) never mounts.
 */

import { render, screen, waitFor, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// jsdom does not implement matchMedia; the avatar hook (BootSplash) reads it
// on mount — same stub as login-screen-dev-login.test.tsx.
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

vi.mock("@/neko-chill/NekoChillApp", () => ({
  default: () => <div data-testid="neko-chill-root">neko</div>,
}));

// The animated avatar needs IntersectionObserver/canvas APIs jsdom lacks;
// the gate test only cares about which SURFACE mounts.
vi.mock("@/components/common/WiiiAvatar", () => ({
  WiiiAvatar: () => <span data-testid="avatar-stub" />,
}));

import { ModeGate } from "@/App";
import { useModeStore } from "@/neko-chill/stores/mode-store";

describe("ModeGate (App.tsx seam)", () => {
  beforeEach(() => {
    storage.clear();
    useModeStore.setState({ mode: "wiii", isLoaded: false });
  });
  afterEach(() => cleanup());

  it("mounts the Neko Chill surface instead of the cloud app", async () => {
    storage.set("neko-chill-mode.json:mode", "neko-chill");

    render(<ModeGate />);

    await waitFor(() =>
      expect(screen.getByTestId("neko-chill-root")).toBeTruthy(),
    );
    // Cloud markers absent: no login screen, no cloud boot splash text.
    expect(screen.queryByText(/đăng nhập/i)).toBeNull();
    expect(screen.queryByText(/không gian trò chuyện/i)).toBeNull();
  });

  it("shows the boot splash until the persisted mode is loaded", () => {
    // loadMode resolves async; before isLoaded the gate must not guess.
    storage.set("neko-chill-mode.json:mode", "neko-chill");
    render(<ModeGate />);
    expect(screen.queryByTestId("neko-chill-root")).toBeNull();
  });
});
