/**
 * #893/#923 — the desktop login wall must never be a dead end: the Workbench
 * boundary owns navigation back to the account-free local surface.
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

describe("LoginScreen — local Workbench escape hatch (#923)", () => {
  beforeEach(() => {
    cleanup();
    storage.clear();
  });

  it("delegates navigation to the Workbench boundary", async () => {
    const onOpenLocal = vi.fn();
    render(<LoginScreen onOpenLocal={onOpenLocal} />);
    const escape = await screen.findByTestId("login-neko-chill-escape");
    expect(escape.textContent).toContain("không gian cục bộ");

    fireEvent.click(escape);
    expect(onOpenLocal).toHaveBeenCalledTimes(1);
  });

  it("does not advertise local authority on hosted web", () => {
    render(<LoginScreen />);
    expect(screen.queryByTestId("login-neko-chill-escape")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /localhost:8000/i }));
    expect(screen.getByText(/Bản web kết nối Wiii Service từ xa/i)).toBeTruthy();
  });
});
