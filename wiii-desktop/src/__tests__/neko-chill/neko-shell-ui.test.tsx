import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import NekoChillApp from "@/neko-chill/NekoChillApp";
import { formatReasoningLabel } from "@/neko-chill/components/NekoTranscript";
import { useNekoAgentStore } from "@/neko-chill/stores/neko-agent-store";
import {
  type NekoSession,
  useNekoSessionStore,
} from "@/neko-chill/stores/neko-session-store";

function makeSession(
  id: string,
  title: string,
  workspace: NekoSession["workspace"],
  overrides: Partial<NekoSession> = {},
): NekoSession {
  return {
    id,
    agentId: "neko",
    agentName: "Neko Core",
    title,
    createdAt: 1_786_598_400_000,
    updatedAt: 1_786_598_400_000,
    workspace,
    launchProfile: null,
    controls: [],
    commands: [],
    pendingControlId: null,
    lastActivityAt: 1_786_598_400_000,
    status: "exited",
    statusDetail: "Đã lưu",
    messages: [],
    events: [],
    runtime: null,
    pendingPermission: null,
    resolvingPermissionId: null,
    ...overrides,
  };
}

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

  it("removes transport emphasis markers from reasoning labels only", () => {
    expect(formatReasoningLabel("**Inspecting workspace**")).toBe("Inspecting workspace");
    expect(formatReasoningLabel("Keep **inner emphasis** here")).toBe(
      "Keep **inner emphasis** here",
    );
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

  it("groups every persisted session and searches all local history from Ctrl+K", () => {
    useNekoSessionStore.setState({
      sessions: {
        alpha: makeSession(
          "alpha",
          "Kiểm tra bản đồ",
          { path: "C:/work/alpha", name: "Project Alpha" },
          {
            messages: [{ id: "a1", role: "user", text: "phân tích hàng hải" }],
            updatedAt: 30,
          },
        ),
        beta: makeSession(
          "beta",
          "Gemini review",
          { path: "C:/work/beta", name: "Project Beta" },
          { agentId: "gemini", agentName: "Gemini CLI", updatedAt: 20 },
        ),
        legacy: makeSession("legacy", "Phiên cũ", null, { updatedAt: 10 }),
      },
      activeSessionId: null,
    });

    render(<NekoChillApp />);

    expect(screen.getAllByText("Project Alpha").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Project Beta").length).toBeGreaterThan(0);
    expect(screen.getByText("Phiên chưa gắn dự án")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Mở phiên Kiểm tra bản đồ" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Xoá phiên Phiên cũ" })).toBeTruthy();

    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(screen.getByRole("dialog", { name: "Trung tâm lệnh Neko Chill" })).toBeTruthy();
    const commandSearch = screen.getByRole("searchbox", { name: "Tìm phiên hoặc lệnh" });
    fireEvent.change(commandSearch, { target: { value: "hàng hải" } });
    expect(screen.getByRole("option", { name: /Kiểm tra bản đồ.*Project Alpha/i })).toBeTruthy();
    expect(screen.queryByRole("option", { name: /Gemini review/i })).toBeNull();
  });

  it("routes provider controls and inserts agent slash commands", async () => {
    const setConfigOption = vi.fn(async () => {});
    useNekoSessionStore.setState({
      sessions: {
        active: makeSession(
          "active",
          "Phiên ACP",
          { path: "C:/work/neko", name: "Neko" },
          {
            status: "idle",
            statusDetail: undefined,
            launchProfile: {
              id: "chatgpt",
              provider: "chatgpt",
              model: "gpt-5.6-luna",
              active: true,
            },
            controls: [
              {
                id: "mode",
                label: "Chế độ",
                category: "mode",
                kind: "select",
                currentValue: "default",
                choices: [
                  { value: "default", label: "Default" },
                  { value: "plan", label: "Plan" },
                ],
              },
            ],
            commands: [{ name: "memory show", description: "Hiện bộ nhớ" }],
          },
        ),
      },
      activeSessionId: "active",
      setConfigOption,
    });

    render(<NekoChillApp />);

    const modeSelects = screen.getAllByLabelText("Chế độ");
    fireEvent.change(modeSelects[0], { target: { value: "plan" } });
    expect(setConfigOption).toHaveBeenCalledWith("mode", "plan");
    expect(screen.getAllByText("C:/work/neko").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/gpt-5\.6-luna/).length).toBeGreaterThan(0);

    const composer = screen.getByTestId("neko-composer-input");
    fireEvent.change(composer, { target: { value: "/memory" } });
    expect(screen.getByRole("listbox", { name: "Lệnh slash" })).toBeTruthy();
    expect(screen.getByRole("option", { name: /memory show.*Agent/i })).toBeTruthy();
    fireEvent.keyDown(composer, { key: "Enter" });
    expect((composer as HTMLTextAreaElement).value).toBe("/memory show");

    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const commandSearch = screen.getByRole("searchbox", { name: "Tìm phiên hoặc lệnh" });
    fireEvent.change(commandSearch, { target: { value: "memory" } });
    fireEvent.click(screen.getByRole("option", { name: /memory show.*Agent/i }));
    expect((composer as HTMLTextAreaElement).value).toBe("/memory show");
    await vi.waitFor(() => expect(document.activeElement).toBe(composer));
  });

  it("keeps navigation and inspector progressively disclosed", () => {
    useNekoSessionStore.setState({
      sessions: {
        active: makeSession(
          "active",
          "Phiên gọn gàng",
          { path: "C:/work/neko", name: "Neko" },
          { status: "idle", statusDetail: undefined },
        ),
      },
      activeSessionId: "active",
    });

    render(<NekoChillApp />);

    expect(screen.queryByTestId("session-inspector")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Mở thông tin phiên" }));
    expect(screen.getByTestId("session-inspector")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Ẩn cây dự án và phiên" }));
    expect(screen.queryByTestId("session-sidebar")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Hiện cây dự án và phiên" }));
    expect(screen.getByTestId("session-sidebar")).toBeTruthy();
  });

  it("gives an empty live session a useful, non-executing start state", () => {
    useNekoSessionStore.setState({
      sessions: {
        active: makeSession(
          "active",
          "Phiên mới",
          { path: "C:/work/neko", name: "Neko" },
          { status: "idle", statusDetail: undefined },
        ),
      },
      activeSessionId: "active",
    });

    render(<NekoChillApp />);

    expect(screen.getByText("Sẵn sàng trong Neko")).toBeTruthy();
    expect(screen.getByText(/Gõ \/ để xem lệnh/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Chèn gợi ý Kiểm tra dự án này" }));
    const composer = screen.getByTestId("neko-composer-input") as HTMLTextAreaElement;
    expect(composer.value).toBe("Kiểm tra dự án này và cho tôi biết điểm cần chú ý.");
  });

  it("shows in-flight durability states and disables duplicate actions", () => {
    useNekoSessionStore.setState({
      sessions: {
        active: makeSession(
          "active",
          "Phiên đang lưu",
          { path: "C:/work/neko", name: "Neko" },
          {
            status: "dispatching",
            statusDetail: undefined,
            pendingPermission: {
              requestId: "perm-1",
              title: "Write(config.json)",
              options: [
                { optionId: "allow_once", label: "Cho phép", kind: "allow_once" },
                { optionId: "reject_once", label: "Từ chối", kind: "reject_once" },
              ],
            },
            resolvingPermissionId: "perm-1",
          },
        ),
      },
      activeSessionId: "active",
    });

    render(<NekoChillApp />);

    expect(screen.getByText(/đang lưu & gửi/i)).toBeTruthy();
    expect(screen.getByText("Đang lưu quyết định…")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Cho phép" }) as HTMLButtonElement).disabled)
      .toBe(true);
    expect((screen.getByRole("button", { name: "Từ chối" }) as HTMLButtonElement).disabled)
      .toBe(true);
    const composer = screen.getByTestId("neko-composer-input") as HTMLTextAreaElement;
    expect(composer.disabled).toBe(false);
    expect(composer.readOnly).toBe(true);
    expect(composer.getAttribute("aria-busy")).toBe("true");
    expect(screen.getByRole("status").textContent).toBe("Đang lưu quyết định…");
  });

  it("keeps the close action available when a session is in error", () => {
    const closeSession = vi.fn(async () => {});
    useNekoSessionStore.setState({
      sessions: {
        active: makeSession(
          "active",
          "Phiên cần phục hồi",
          { path: "C:/work/neko", name: "Neko" },
          {
            status: "error",
            statusDetail: "Runtime báo lỗi",
          },
        ),
      },
      activeSessionId: "active",
      closeSession,
    });

    render(<NekoChillApp />);
    fireEvent.click(screen.getByRole("button", { name: "Kết thúc" }));

    expect(closeSession).toHaveBeenCalledWith("active");
  });

  it("requires a project and reuses an exact recent workspace for a new session", async () => {
    const createSession = vi.fn(async () => "created");
    const agent = {
      id: "neko",
      name: "Neko Core",
      binary: "neko",
      version: "0.24.0",
      found: true,
    };
    useNekoAgentStore.setState({ agents: [agent], isLoading: false });
    useNekoSessionStore.setState({
      sessions: {
        recent: makeSession("recent", "Lịch sử", {
          path: "C:/Users/me/project",
          name: "project",
        }),
      },
      activeSessionId: null,
      createSession,
    });

    render(<NekoChillApp />);

    expect(screen.queryByTestId("start-neko")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "project" }));
    const start = await screen.findByTestId("start-neko") as HTMLButtonElement;
    await vi.waitFor(() => expect(start.disabled).toBe(false));
    fireEvent.click(start);

    await vi.waitFor(() => {
      expect(createSession).toHaveBeenCalledWith(
        agent,
        { path: "C:/Users/me/project", name: "project" },
        null,
      );
    });
  });
});
