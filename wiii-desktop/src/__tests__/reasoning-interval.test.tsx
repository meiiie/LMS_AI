import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import type { ThinkingBlockData, ToolExecutionBlockData } from "@/api/types";
import { ReasoningInterval, type ReasoningIntervalViewModel } from "@/components/chat/ReasoningInterval";
import { useCodeStudioStore } from "@/stores/code-studio-store";
import { useUIStore } from "@/stores/ui-store";

function resetStores() {
  useCodeStudioStore.setState({
    activeSessionId: null,
    sessions: {},
  });
  useUIStore.setState({
    activeView: "chat",
    sidebarOpen: true,
    sourcesPanelOpen: false,
    selectedSourceIndex: null,
    commandPaletteOpen: false,
    inputFocused: false,
    characterPanelOpen: false,
    previewPanelOpen: false,
    selectedPreviewId: null,
    artifactPanelOpen: false,
    selectedArtifactId: null,
    artifactActiveTab: "code",
    _ephemeralArtifact: null,
    orgManagerTargetOrgId: null,
    codeStudioPanelOpen: false,
  });
}

describe("ReasoningInterval", () => {
  beforeEach(() => {
    resetStores();
  });

  it("renders fractional duration text without inflating sub-second intervals", () => {
    const interval: ReasoningIntervalViewModel = {
      id: "interval-fractional",
      label: "Wiii đang suy nghĩ~",
      isLive: false,
      durationSeconds: 0.7,
      items: [],
      rawBlocks: [],
    };

    render(
      <ReasoningInterval
        interval={interval}
        thinkingLevel="balanced"
        onOpenInspector={() => {}}
      />,
    );

    expect(screen.getAllByText("Nhịp 0.7s").length).toBeGreaterThan(0);
  });

  it("keeps Code Studio tool trace out of the main reasoning body in balanced mode", () => {
    useCodeStudioStore.getState().openSession(
      "vs-code-1",
      "Pendulum App",
      "html",
      1,
      {
        studioLane: "app",
        artifactKind: "html_app",
        qualityProfile: "premium",
        rendererContract: "host_shell",
      },
    );
    useCodeStudioStore.getState().appendCode("vs-code-1", "<div>demo</div>", 0, 64);

    const thinkingBlock: ThinkingBlockData = {
      type: "thinking",
      id: "thinking-1",
      content: "Minh dang khau lai app tuong tac nay cho that muot.",
      toolCalls: [],
      summary: "Dang dung app",
    };

    const toolBlock: ToolExecutionBlockData = {
      type: "tool_execution",
      id: "tool-1",
      status: "pending",
      tool: {
        id: "tool-1",
        name: "tool_create_visual_code",
        args: {
          title: "Pendulum App",
          visual_session_id: "vs-code-1",
        },
        result: "Minh hoa da san sang: Pendulum App",
      },
    };

    const interval: ReasoningIntervalViewModel = {
      id: "interval-1",
      label: "Code Studio",
      isLive: true,
      items: [
        { kind: "thinking", id: "thinking-item", block: thinkingBlock },
        { kind: "tool", id: "tool-item", block: toolBlock },
      ],
      rawBlocks: [thinkingBlock, toolBlock],
    };

    render(
      <ReasoningInterval
        interval={interval}
        thinkingLevel="balanced"
        onOpenInspector={() => {}}
      />,
    );

    expect(useCodeStudioStore.getState().getActiveSessionContext()).toEqual({
      active_session: {
        session_id: "vs-code-1",
        title: "Pendulum App",
        status: "streaming",
        active_version: 1,
        version_count: 0,
        language: "html",
        studio_lane: "app",
        artifact_kind: "html_app",
        quality_profile: "premium",
        renderer_contract: "host_shell",
        has_preview: false,
      },
    });
    expect(document.querySelector(".code-studio-card")).toBeNull();
    expect(screen.getByText("Wiii đang xử lý")).toBeTruthy();
    expect(screen.queryByText("Code Studio")).toBeNull();
    expect(screen.getByText("Minh dang khau lai app tuong tac nay cho that muot.")).toBeTruthy();
    expect(screen.queryByText("Pendulum App")).toBeNull();
  });

  it("keeps long balanced turns expanded so living thought stays visible after completion", () => {
    const interval: ReasoningIntervalViewModel = {
      id: "interval-long-balanced",
      label: "Wiii dang suy nghi~",
      isLive: false,
      durationSeconds: 18.4,
      items: [
        {
          kind: "thinking",
          id: "thinking-a",
          block: {
            type: "thinking",
            id: "thinking-a",
            content: "Minh dang gom lai cach hieu truoc khi noi tiep.",
            toolCalls: [],
          },
        },
        {
          kind: "thinking",
          id: "thinking-b",
          block: {
            type: "thinking",
            id: "thinking-b",
            content: "Minh dang doi chieu nhung gi vua thay de khong lech y.",
            toolCalls: [],
          },
        },
        {
          kind: "thinking",
          id: "thinking-c",
          block: {
            type: "thinking",
            id: "thinking-c",
            content: "Minh dang khau lai thanh mot mach noi de ban bat duoc y chinh.",
            toolCalls: [],
          },
        },
      ],
      rawBlocks: [],
    };

    render(
      <ReasoningInterval
        interval={interval}
        thinkingLevel="balanced"
        onOpenInspector={() => {}}
      />,
    );

    expect(screen.getByText("Minh dang gom lai cach hieu truoc khi noi tiep.")).toBeTruthy();
    expect(screen.getByText("Minh dang doi chieu nhung gi vua thay de khong lech y.")).toBeTruthy();
    expect(screen.getByText("Minh dang khau lai thanh mot mach noi de ban bat duoc y chinh.")).toBeTruthy();
  });

  it("keeps a collapsed preview visible after completion for short balanced turns", () => {
    const interval: ReasoningIntervalViewModel = {
      id: "interval-collapsed-preview",
      label: "Wiii da nghi xong~",
      isLive: false,
      durationSeconds: 4.2,
      items: [
        {
          kind: "thinking",
          id: "thinking-only",
          block: {
            type: "thinking",
            id: "thinking-only",
            content: "Minh dang gom lai vai moc dang tin roi moi dung phan nhin.",
            toolCalls: [],
          },
        },
      ],
      rawBlocks: [],
    };

    const { container } = render(
      <ReasoningInterval
        interval={interval}
        thinkingLevel="balanced"
        onOpenInspector={() => {}}
      />,
    );

    expect(screen.getAllByText("Minh dang gom lai vai moc dang tin roi moi dung phan nhin.").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Wiii đã xử lý xong").length).toBeGreaterThan(0);
    expect(container.querySelector(".sr-only")).toBeNull();
    expect(container.querySelector(".reasoning-interval__thinking-body")?.hasAttribute("hidden")).toBe(true);
  });

  it("keeps summary-only intervals header-only when no delta body was streamed", () => {
    const interval: ReasoningIntervalViewModel = {
      id: "interval-summary-preview",
      label: "Wiii da nghi xong~",
      summary: "Minh dang gom vai moc dang tin truoc khi chot cau tra loi.",
      isLive: false,
      durationSeconds: 3.1,
      items: [
        {
          kind: "thinking",
          id: "thinking-empty",
          block: {
            type: "thinking",
            id: "thinking-empty",
            content: "",
            summary: "",
            toolCalls: [],
          },
        },
      ],
      rawBlocks: [],
    };

    render(
      <ReasoningInterval
        interval={interval}
        thinkingLevel="balanced"
        onOpenInspector={() => {}}
      />,
    );

    expect(screen.getAllByText("Wiii đã xử lý xong").length).toBeGreaterThan(0);
    expect(
      screen.queryByText("Minh dang gom vai moc dang tin truoc khi chot cau tra loi."),
    ).toBeNull();
  });
});
