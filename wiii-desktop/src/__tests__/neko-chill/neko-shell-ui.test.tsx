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
    pendingPermission: null,
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

  it("groups every persisted session by project and searches local history", () => {
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

    const search = screen.getByRole("searchbox", { name: "Tìm phiên Neko Chill" });
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(document.activeElement).toBe(search);
    fireEvent.change(search, { target: { value: "hàng hải" } });
    expect(screen.getByRole("button", { name: "Mở phiên Kiểm tra bản đồ" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Mở phiên Gemini review" })).toBeNull();
  });

  it("routes provider controls and inserts agent slash commands", () => {
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

    const start = screen.getByTestId("start-neko") as HTMLButtonElement;
    expect(start.disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "project" }));
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
