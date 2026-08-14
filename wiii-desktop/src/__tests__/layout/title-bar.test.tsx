import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TitleBar } from "@/components/layout/TitleBar";
import { useUIStore } from "@/stores/ui-store";

const native = vi.hoisted(() => {
  const state: {
    maximized: boolean;
    resizeListener: (() => void) | null;
  } = { maximized: false, resizeListener: null };
  const unlisten = vi.fn();
  const appWindow = {
    minimize: vi.fn(async () => {}),
    toggleMaximize: vi.fn(async () => {
      state.maximized = !state.maximized;
    }),
    close: vi.fn(async () => {}),
    isMaximized: vi.fn(async () => state.maximized),
    onResized: vi.fn(async (listener: () => void) => {
      state.resizeListener = listener;
      return unlisten;
    }),
  };
  return { appWindow, state, unlisten };
});

vi.mock("@tauri-apps/api/window", () => ({
  getCurrentWindow: () => native.appWindow,
}));

describe("shared desktop titlebar", () => {
  beforeEach(() => {
    (window as typeof window & { __TAURI_INTERNALS__?: object }).__TAURI_INTERNALS__ = {};
    native.state.maximized = false;
    native.state.resizeListener = null;
    native.appWindow.minimize.mockReset().mockResolvedValue(undefined);
    native.appWindow.toggleMaximize.mockReset().mockImplementation(async () => {
      native.state.maximized = !native.state.maximized;
    });
    native.appWindow.close.mockReset().mockResolvedValue(undefined);
    native.appWindow.isMaximized.mockReset().mockImplementation(async () => native.state.maximized);
    native.appWindow.onResized.mockReset().mockImplementation(async (listener: () => void) => {
      native.state.resizeListener = listener;
      return native.unlisten;
    });
    native.unlisten.mockReset();
    useUIStore.setState({ commandPaletteOpen: false, sidebarOpen: true });
  });

  it("awaits minimize, maximize/restore, and close through the native window", async () => {
    render(<TitleBar minimal />);

    const minimize = await screen.findByRole("button", { name: "Thu nhỏ cửa sổ" });
    fireEvent.click(minimize);
    expect(native.appWindow.minimize).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Phóng to cửa sổ" }));
    await screen.findByRole("button", { name: "Khôi phục cửa sổ" });
    expect(native.appWindow.toggleMaximize).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Khôi phục cửa sổ" }));
    await screen.findByRole("button", { name: "Phóng to cửa sổ" });
    expect(native.appWindow.toggleMaximize).toHaveBeenCalledTimes(2);

    fireEvent.doubleClick(screen.getByTestId("titlebar-drag-region"));
    await screen.findByRole("button", { name: "Khôi phục cửa sổ" });
    expect(native.appWindow.toggleMaximize).toHaveBeenCalledTimes(3);

    fireEvent.click(screen.getByRole("button", { name: "Đóng cửa sổ" }));
    expect(native.appWindow.close).toHaveBeenCalledTimes(1);
  });

  it("synchronizes the restore action after a native resize", async () => {
    render(<TitleBar minimal />);
    await screen.findByRole("button", { name: "Phóng to cửa sổ" });

    native.state.maximized = true;
    await act(async () => {
      native.state.resizeListener?.();
    });

    expect(
      (await screen.findByRole("button", { name: "Khôi phục cửa sổ" })).getAttribute(
        "aria-pressed",
      ),
    ).toBe("true");
  });

  it("opens Wiii's existing command palette from the default titlebar", async () => {
    render(<TitleBar />);

    const commandCenter = await screen.findByRole("button", { name: "Tìm cuộc trò chuyện hoặc chạy lệnh" });
    fireEvent.click(commandCenter);
    expect(useUIStore.getState().commandPaletteOpen).toBe(true);
    useUIStore.getState().closeCommandPalette();
    fireEvent.doubleClick(commandCenter);
    expect(native.appWindow.toggleMaximize).not.toHaveBeenCalled();
  });

  it("supports Neko-owned leading, command-center, and trailing controls", async () => {
    const open = vi.fn();
    render(
      <TitleBar
        minimal
        leading={<span>Neko Chill</span>}
        commandCenter={{ label: "Tìm phiên hoặc chạy lệnh", onClick: open }}
        trailing={<button type="button">Ẩn phiên</button>}
      />,
    );

    expect(await screen.findByText("Neko Chill")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Tìm phiên hoặc chạy lệnh" }));
    expect(open).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Ẩn phiên" })).toBeTruthy();
  });

  it("reports native failures instead of swallowing them", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    native.appWindow.minimize.mockRejectedValueOnce(new Error("permission denied"));
    render(<TitleBar minimal />);

    fireEvent.click(await screen.findByRole("button", { name: "Thu nhỏ cửa sổ" }));

    await vi.waitFor(() => {
      expect(consoleError).toHaveBeenCalledWith(
        "[TitleBar] Không thể thu nhỏ cửa sổ",
        expect.any(Error),
      );
    });
    consoleError.mockRestore();
  });

  it("does not render desktop chrome in a browser", () => {
    delete (window as typeof window & { __TAURI_INTERNALS__?: object }).__TAURI_INTERNALS__;
    const { container } = render(<TitleBar />);
    expect(container.innerHTML).toBe("");
  });
});
