import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import NekoChillApp from "@/neko-chill/NekoChillApp";
import { useNekoAgentStore } from "@/neko-chill/stores/neko-agent-store";
import { useNekoSessionStore } from "@/neko-chill/stores/neko-session-store";

describe("Neko Chill shell UI", () => {
  beforeEach(() => {
    useNekoAgentStore.setState({
      agents: [],
      isLoading: false,
      detect: vi.fn(async () => {}),
    });
    useNekoSessionStore.setState({
      sessions: {},
      activeSessionId: null,
      hydrated: true,
      hydrate: vi.fn(async () => {}),
    });
  });

  it("exposes the mode menu state and closes it with Escape", () => {
    render(<NekoChillApp />);

    const switcher = screen.getByRole("button", { name: "Chuyển chế độ" });
    expect(switcher.getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(switcher);
    expect(switcher.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("menu", { name: "Chọn chế độ" })).toBeTruthy();
    expect(screen.getByRole("menuitemradio", { name: /Neko Chill/i }).getAttribute("aria-checked"))
      .toBe("true");

    fireEvent.keyDown(window, { key: "Escape" });
    expect(switcher.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("menu", { name: "Chọn chế độ" })).toBeNull();
  });

  it("exposes persisted sessions and their delete actions to keyboard users", () => {
    useNekoSessionStore.setState({
      sessions: {
        "session-1": {
          id: "session-1",
          agentId: "neko",
          agentName: "Neko Core",
          title: "Phiên kiểm thử",
          createdAt: 1_786_598_400_000,
          lastActivityAt: 1_786_598_400_000,
          status: "exited",
          statusDetail: "Đã lưu",
          messages: [],
          pendingPermission: null,
        },
      },
      activeSessionId: null,
    });

    render(<NekoChillApp />);

    expect(screen.getByRole("button", { name: "Mở phiên Phiên kiểm thử" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Xoá phiên Phiên kiểm thử" })).toBeTruthy();
  });
});
