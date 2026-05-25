import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { VisualBlock } from "@/components/chat/VisualBlock";
import type { VisualBlockData, VisualPayload } from "@/api/types";
import { useChatStore } from "@/stores/chat-store";
import { useCodeStudioStore } from "@/stores/code-studio-store";
import { useUIStore } from "@/stores/ui-store";

vi.mock("@/components/common/InlineVisualFrame", () => ({
  InlineVisualFrame: ({ title }: { title?: string }) => (
    <div data-testid="inline-visual-frame">{title}</div>
  ),
}));

vi.mock("@/hooks/useReducedMotion", () => ({
  useReducedMotion: () => true,
}));

function makeVisual(overrides: Partial<VisualPayload> = {}): VisualPayload {
  return {
    id: "visual-copy-1",
    visual_session_id: "vs-copy-1",
    type: "concept",
    renderer_kind: "app",
    shell_variant: "immersive",
    patch_strategy: "app_state",
    figure_group_id: "fg-copy",
    figure_index: 1,
    figure_total: 1,
    pedagogical_role: "mechanism",
    chrome_mode: "app",
    claim: "Mô phỏng tương tác",
    presentation_intent: "code_studio_app",
    figure_budget: 1,
    quality_profile: "standard",
    renderer_contract: "host_shell",
    studio_lane: "app",
    artifact_kind: "html_app",
    narrative_anchor: "after-lead",
    runtime: "sandbox_html",
    title: "Mô phỏng tương tác",
    summary: "Khung mô phỏng có thể mở thành artifact.",
    spec: {},
    scene: { kind: "concept", nodes: [], links: [] },
    controls: [],
    annotations: [],
    interaction_mode: "static",
    ephemeral: true,
    lifecycle_event: "visual_open",
    fallback_html: "<main>Mô phỏng</main>",
    artifact_handoff_available: true,
    artifact_handoff_mode: "followup_prompt",
    artifact_handoff_label: null,
    artifact_handoff_prompt: "Mở visual này thành artifact",
    ...overrides,
  };
}

describe("VisualBlock copy", () => {
  beforeEach(() => {
    useChatStore.setState({
      visualSessions: {},
      isStreaming: false,
    });
    useCodeStudioStore.setState({
      activeSessionId: null,
      sessions: {},
    });
    useUIStore.setState({
      codeStudioPanelOpen: false,
    });
  });

  it("uses Vietnamese copy for the default artifact handoff action", () => {
    const block: VisualBlockData = {
      type: "visual",
      id: "block-copy-1",
      visual: makeVisual(),
      status: "committed",
    };

    render(<VisualBlock block={block} onSuggestedQuestion={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Mở thành Artifact" })).toBeTruthy();
  });

  it("delegates mapped Code Studio visuals to the owning panel session", () => {
    const store = useCodeStudioStore.getState();
    store.openSession("cs-owner", "Mapped simulation", "html", 1);
    store.completeSession(
      "cs-owner",
      "<main>Mapped simulation</main>",
      "html",
      1,
      undefined,
      "vs-copy-1",
    );
    useUIStore.setState({
      codeStudioPanelOpen: true,
    });
    store.setActiveSession("cs-owner");

    const block: VisualBlockData = {
      type: "visual",
      id: "block-copy-2",
      visual: makeVisual(),
      status: "committed",
    };

    render(<VisualBlock block={block} onSuggestedQuestion={vi.fn()} />);

    expect(screen.queryByTestId("inline-visual-frame")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Code Studio/ }));
    expect(useCodeStudioStore.getState().activeSessionId).toBe("cs-owner");
  });
});
