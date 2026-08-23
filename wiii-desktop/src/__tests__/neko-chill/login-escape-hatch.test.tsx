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

describe("LoginScreen — optional Wiii Service gateway (#945)", () => {
  beforeEach(() => {
    cleanup();
    storage.clear();
  });

  it("delegates navigation to the Workbench boundary", async () => {
    const onOpenLocal = vi.fn();
    render(<LoginScreen onOpenLocal={onOpenLocal} />);
    expect(screen.getByRole("heading", { name: "Kết nối Wiii Service" })).toBeTruthy();
    expect(screen.getByText(/Agent và dự án cục bộ của Wiii vẫn hoạt động/i)).toBeTruthy();
    const escape = await screen.findByTestId("login-neko-chill-escape");
    expect(escape.textContent).toContain("Tiếp tục với Wiii cục bộ");

    fireEvent.click(escape);
    expect(onOpenLocal).toHaveBeenCalledTimes(1);
  });

  it("does not advertise local authority on hosted web", () => {
    render(<LoginScreen />);
    expect(screen.queryByTestId("login-neko-chill-escape")).toBeNull();
    expect(screen.getByText(/Bản web sử dụng Wiii Service/i)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Kết nối nâng cao/i }));
    expect(screen.getByText(/Bản web kết nối Wiii Service từ xa/i)).toBeTruthy();
  });
});
