import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PreviewPanel } from "@/components/layout/PreviewPanel";
import { useChatStore } from "@/stores/chat-store";
import { useUIStore } from "@/stores/ui-store";
import { useHostContextStore } from "@/stores/host-context-store";
import { useToastStore } from "@/stores/toast-store";
import type { PreviewItemData } from "@/api/types";

vi.mock("@/api/host-actions", () => ({
  submitHostActionAudit: vi.fn().mockResolvedValue({
    status: "success",
    event_type: "apply_confirmed",
    action: "authoring.apply_lesson_patch",
    request_id: "req-audit-1",
  }),
}));

function seedConversation(previews: PreviewItemData[]) {
  useChatStore.setState({
    activeConversationId: "conv-preview-ui",
    conversations: [
      {
        id: "conv-preview-ui",
        title: "Preview UI",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        messages: [
          {
            id: "msg-a",
            role: "assistant",
            content: "Preview ready",
            timestamp: new Date().toISOString(),
            previews,
          },
        ],
      },
    ],
  });
}

describe("PreviewPanel host action operator flow", () => {
  beforeEach(() => {
    useChatStore.setState({
      conversations: [],
      activeConversationId: null,
      isLoaded: false,
      isStreaming: false,
      streamingContent: "",
      streamingThinking: "",
      streamingSources: [],
      streamingStep: "",
      streamingToolCalls: [],
      streamingBlocks: [],
      streamingStartTime: null,
      streamingSteps: [],
      streamingDomainNotice: "",
      streamingPhases: [],
      streamingPreviews: [],
      streamingArtifacts: [],
      pendingStreamMetadata: null,
      _activeSubagentGroupId: null,
      streamError: "",
      streamCompletedAt: null,
    } as never);

    useUIStore.setState({
      previewPanelOpen: false,
      selectedPreviewId: null,
    } as never);

    useHostContextStore.setState({
      capabilities: {
        host_type: "lms",
        host_name: "LMS",
        version: "1",
        resources: ["course"],
        surfaces: ["right_sidebar"],
        tools: [],
      },
      currentContext: {
        host_type: "lms",
        host_name: "LMS",
        page: {
          type: "course_editor",
          title: "Curriculum",
        },
        user_role: "teacher",
        workflow_stage: "editing",
      },
      lastActionResult: null,
      recentActionResults: [],
      pendingActions: new Map(),
      requestAction: vi.fn().mockResolvedValue({
        success: true,
        data: {
          summary: "Applied lesson patch to lesson lesson-1.",
        },
      }),
      resolveAction: vi.fn(),
    } as never);

    useToastStore.setState({ toasts: [] });
  });

  it("renders block diff details and confirms apply from the right sidebar preview", async () => {
    const preview: PreviewItemData = {
      preview_type: "host_action",
      preview_id: "host-preview-lesson-1",
      title: "Preview cap nhat bai hoc: Bai hoc goc",
      snippet:
        "Lesson patch preview ready. Confirm explicitly when you want me to apply it.",
      metadata: {
        preview_kind: "lesson_patch",
        preview_token: "preview-lesson-1",
        apply_action: "authoring.apply_lesson_patch",
        lesson_id: "lesson-1",
        target_label: "Bai hoc goc",
        lesson_before: {
          title: "Bai hoc goc",
          description: "Mo ta cu",
          content_excerpt: "Noi dung cu",
          blocks: [
            { id: "b1", type: "text", label: "Doan 1", excerpt: "Noi dung cu" },
          ],
        },
        lesson_after: {
          title: "Bai hoc moi",
          description: "Mo ta cu",
          content_excerpt: "Noi dung moi",
          blocks: [
            {
              id: "b1",
              type: "text",
              label: "Doan 1",
              excerpt: "Noi dung moi",
            },
          ],
        },
        block_diff: {
          changed: 1,
          added: 0,
          removed: 0,
          unchanged: 0,
          items: [
            {
              index: 0,
              status: "changed",
              before: { id: "b1", label: "Doan 1", excerpt: "Noi dung cu" },
              after: { id: "b1", label: "Doan 1", excerpt: "Noi dung moi" },
            },
          ],
        },
      },
    };

    seedConversation([preview]);
    useUIStore.getState().openPreview("host-preview-lesson-1");

    render(<PreviewPanel inline />);

    expect(screen.getByText("Xác nhận của giáo viên")).toBeTruthy();
    const blockDiffHeading = screen.getByText("Diff theo block");
    expect(blockDiffHeading).toBeTruthy();
    const blockDiffSection = blockDiffHeading.closest("section");
    expect(blockDiffSection).toBeTruthy();
    const diffQueries = within(blockDiffSection as HTMLElement);
    expect(diffQueries.getByText("Noi dung cu")).toBeTruthy();
    expect(diffQueries.getByText("Noi dung moi")).toBeTruthy();

    fireEvent.click(
      screen.getByRole("button", { name: "Xác nhận áp dụng vào bài học" }),
    );

    await waitFor(() => {
      expect(useHostContextStore.getState().requestAction).toHaveBeenCalledWith(
        "authoring.apply_lesson_patch",
        { preview_token: "preview-lesson-1" },
        expect.stringMatching(/^req-preview-apply-/),
      );
    });

    const { submitHostActionAudit } = await import("@/api/host-actions");
    await waitFor(() => {
      expect(submitHostActionAudit).toHaveBeenCalledWith(
        expect.objectContaining({
          event_type: "apply_confirmed",
          action: "authoring.apply_lesson_patch",
          preview_kind: "lesson_patch",
          preview_token: "preview-lesson-1",
          surface: "preview_panel",
        }),
      );
    });

    expect(
      await screen.findByText("Applied lesson patch to lesson lesson-1."),
    ).toBeTruthy();
  });
});
