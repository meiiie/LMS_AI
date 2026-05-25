import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PreviewPanel } from "@/components/layout/PreviewPanel";
import { buildHostActionPreviewItem } from "@/hooks/useSSEStream";
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

function makeLessonPatchPreview(
  metadataOverrides: Record<string, unknown> = {},
): PreviewItemData {
  return {
    preview_type: "host_action",
    preview_id: "host-preview-lesson-1",
    title: "Xem trước cập nhật bài học: Bài học gốc",
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
      ...metadataOverrides,
    },
  };
}

describe("PreviewPanel host action operator flow", () => {
  beforeEach(() => {
    vi.clearAllMocks();

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
    const preview = makeLessonPatchPreview({
      source_references: [
        {
          kind: "chapter",
          chapter_index: 0,
          title: "Doc chuong 1",
          source_pages: [4, 5],
          excerpt: "Noi dung goc tu tai lieu.",
        },
      ],
    });

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
    expect(screen.getByText("Nguồn tài liệu")).toBeTruthy();
    expect(screen.getByText("Doc chuong 1")).toBeTruthy();
    expect(screen.getByText("Trang 4, 5")).toBeTruthy();
    expect(screen.getByText("Noi dung goc tu tai lieu.")).toBeTruthy();

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

  it("keeps Wiii apply disabled when the host requires its own approval token", () => {
    const preview = makeLessonPatchPreview();
    useHostContextStore.setState({
      capabilities: {
        host_type: "lms",
        host_name: "LMS",
        version: "1",
        resources: ["course"],
        surfaces: ["right_sidebar"],
        tools: [
          {
            name: "authoring.apply_lesson_patch",
            description: "Apply a teacher-approved lesson patch.",
            input_schema: {
              type: "object",
              properties: {
                preview_token: { type: "string" },
                approval_token: { type: "string" },
              },
              required: ["preview_token", "approval_token"],
            },
            requires_confirmation: true,
            mutates_state: true,
          },
        ],
      },
    } as never);

    seedConversation([preview]);
    useUIStore.getState().openPreview("host-preview-lesson-1");

    render(<PreviewPanel inline />);

    const button = screen.getByRole("button", {
      name: "Xác nhận áp dụng vào bài học",
    }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(
      screen.getByText(/LMS đang giữ quyền áp dụng trong hộp thoại preview/),
    ).toBeTruthy();

    fireEvent.click(button);

    expect(useHostContextStore.getState().requestAction).not.toHaveBeenCalled();
  });

  it("forwards the LMS approval token when the host preview already confirmed apply", async () => {
    const preview = makeLessonPatchPreview({
      approval_token: "approval-lesson-1",
    });
    const requestAction = vi.fn().mockResolvedValue({
      success: true,
      data: {
        summary: "Applied with LMS approval.",
        preview_token: "preview-lesson-1",
        preview_kind: "lesson_patch",
        approval_token: "approval-lesson-1",
      },
    });
    useHostContextStore.setState({
      capabilities: {
        host_type: "lms",
        host_name: "LMS",
        version: "1",
        resources: ["course"],
        surfaces: ["right_sidebar"],
        tools: [
          {
            name: "authoring.apply_lesson_patch",
            description: "Apply a teacher-approved lesson patch.",
            input_schema: {
              type: "object",
              properties: {
                preview_token: { type: "string" },
                approval_token: { type: "string" },
              },
              required: ["preview_token", "approval_token"],
            },
            requires_confirmation: true,
            mutates_state: true,
          },
        ],
      },
      requestAction,
    } as never);

    seedConversation([preview]);
    useUIStore.getState().openPreview("host-preview-lesson-1");

    render(<PreviewPanel inline />);

    const button = screen.getByRole("button", {
      name: "Xác nhận áp dụng vào bài học",
    }) as HTMLButtonElement;
    expect(button.disabled).toBe(false);

    fireEvent.click(button);

    await waitFor(() => {
      expect(requestAction).toHaveBeenCalledWith(
        "authoring.apply_lesson_patch",
        {
          preview_token: "preview-lesson-1",
          approval_token: "approval-lesson-1",
        },
        expect.stringMatching(/^req-preview-apply-/),
      );
    });
    expect(await screen.findByText("Applied with LMS approval.")).toBeTruthy();

    const { submitHostActionAudit } = await import("@/api/host-actions");
    const submitAuditMock = vi.mocked(submitHostActionAudit);
    await waitFor(() => {
      expect(submitAuditMock).toHaveBeenCalledWith(
        expect.objectContaining({
          event_type: "apply_confirmed",
          action: "authoring.apply_lesson_patch",
          preview_kind: "lesson_patch",
          preview_token: "preview-lesson-1",
        }),
      );
    });
    const auditPayload = submitAuditMock.mock.calls[0]?.[0];
    expect(JSON.stringify(auditPayload)).not.toContain("approval-lesson-1");
  });

  it("forwards approval tokens that arrive through the host-action SSE preview item", async () => {
    const preview = buildHostActionPreviewItem(
      "authoring.preview_lesson_patch",
      "req-preview-from-lms-dialog",
      {},
      {
        preview_token: "preview-lesson-from-sse",
        approval_token: "approval-from-lms-dialog",
        preview_kind: "lesson_patch",
        apply_action: "authoring.apply_lesson_patch",
        summary: "LMS preview dialog approved.",
        lesson_id: "lesson-1",
        lesson_title: "Bài học đã duyệt",
      },
      {
        host_type: "lms",
        page: { type: "course_editor", title: "Course editor" },
        workflow_stage: "editing",
      },
    );
    expect(preview).not.toBeNull();

    const requestAction = vi.fn().mockResolvedValue({
      success: true,
      data: {
        summary: "Applied with LMS approval from SSE.",
      },
    });
    useHostContextStore.setState({
      capabilities: {
        host_type: "lms",
        host_name: "LMS",
        version: "1",
        resources: ["course"],
        surfaces: ["right_sidebar"],
        tools: [
          {
            name: "authoring.apply_lesson_patch",
            description: "Apply a teacher-approved lesson patch.",
            input_schema: {
              type: "object",
              properties: {
                preview_token: { type: "string" },
                approval_token: { type: "string" },
              },
              required: ["preview_token", "approval_token"],
            },
            requires_confirmation: true,
            mutates_state: true,
          },
        ],
      },
      requestAction,
    } as never);

    seedConversation([preview as PreviewItemData]);
    useUIStore.getState().openPreview("host-action-req-preview-from-lms-dialog");

    render(<PreviewPanel inline />);

    fireEvent.click(
      screen.getByRole("button", { name: "Xác nhận áp dụng vào bài học" }),
    );

    await waitFor(() => {
      expect(requestAction).toHaveBeenCalledWith(
        "authoring.apply_lesson_patch",
        {
          preview_token: "preview-lesson-from-sse",
          approval_token: "approval-from-lms-dialog",
        },
        expect.stringMatching(/^req-preview-apply-/),
      );
    });
    expect(
      await screen.findByText("Applied with LMS approval from SSE."),
    ).toBeTruthy();
  });

  it("treats host_preview_approval_required as the expected LMS safety gate", async () => {
    const preview = makeLessonPatchPreview();
    const requestAction = vi.fn().mockResolvedValue({
      success: false,
      error: "host_preview_approval_required",
    });
    useHostContextStore.setState({
      requestAction,
    } as never);

    seedConversation([preview]);
    useUIStore.getState().openPreview("host-preview-lesson-1");

    render(<PreviewPanel inline />);

    fireEvent.click(
      screen.getByRole("button", { name: "Xác nhận áp dụng vào bài học" }),
    );

    await waitFor(() => {
      expect(
        screen.getByText(/LMS đang giữ quyền áp dụng trong hộp thoại preview/),
      ).toBeTruthy();
    });

    const { submitHostActionAudit } = await import("@/api/host-actions");
    expect(submitHostActionAudit).not.toHaveBeenCalled();
    expect(useToastStore.getState().toasts).toEqual([
      expect.objectContaining({
        type: "info",
        message: expect.stringContaining("LMS đang giữ quyền áp dụng"),
      }),
    ]);
  });
});
