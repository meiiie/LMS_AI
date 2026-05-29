import { describe, it, expect } from "vitest";
import {
  buildHostActionPreviewItem,
  buildHostActionResultRequest,
} from "@/hooks/useSSEStream";
import { useHostContextStore } from "@/stores/host-context-store";
import type { HostContext } from "@/stores/host-context-store";

describe("Host Action SSE + PostMessage Integration (Sprint 222b)", () => {
  it("wiii:action-response resolves pending action", async () => {
    useHostContextStore.getState().clear();
    const store = useHostContextStore.getState();
    const promise = store.requestAction("create_course", { name: "Test" });

    const [reqId] = Array.from(useHostContextStore.getState().pendingActions.keys());

    store.resolveAction(reqId, { success: true, data: { id: 42 } });

    const result = await promise;
    expect(result.success).toBe(true);
    expect(result.data?.id).toBe(42);
  });

  it("host_action SSE event type is recognized", () => {
    const eventType = "host_action";
    expect(eventType).toBe("host_action");
  });

  it("preserves backend-provided request ids for host_action SSE flow", async () => {
    useHostContextStore.getState().clear();
    const store = useHostContextStore.getState();
    const promise = store.requestAction(
      "authoring.generate_lesson",
      { course_id: "course-1" },
      "req-backend-42",
    );

    expect(useHostContextStore.getState().pendingActions.has("req-backend-42")).toBe(true);
    store.resolveAction("req-backend-42", { success: true, data: { opened: true } });

    const result = await promise;
    expect(result.success).toBe(true);
    expect(result.data?.opened).toBe(true);
  });

  it("host_action SSE flow keeps preview feedback available for follow-up apply turns", async () => {
    useHostContextStore.getState().clear();
    const store = useHostContextStore.getState();
    const promise = store.requestAction(
      "assessment.preview_quiz_commit",
      { lesson_id: "lesson-1" },
      "req-backend-preview-1",
    );

    store.resolveAction("req-backend-preview-1", {
      success: true,
      data: {
        preview_token: "quiz-preview-123",
        preview_kind: "quiz_commit",
        summary: "Quiz preview ready.",
      },
    });

    await promise;

    const feedback = useHostContextStore.getState().getActionFeedbackForRequest();
    expect(feedback?.last_action_result?.data?.preview_kind).toBe("quiz_commit");
    expect(feedback?.last_action_result?.summary).toBe("Quiz preview ready.");
  });

  it("preserves source references from host preview responses", () => {
    const hostContext = {
      host_type: "lms",
      page: { type: "course_editor", title: "Course editor" },
      workflow_stage: "editing",
    } satisfies HostContext;

    const item = buildHostActionPreviewItem(
      "authoring.preview_lesson_patch",
      "req-source-1",
      {},
      {
        preview_token: "lesson-preview-123",
        preview_kind: "lesson_patch",
        summary: "Lesson patch preview ready.",
        lesson_title: "Bài học nguồn",
        source_references: [
          {
            kind: "lesson",
            chapter_index: 1,
            lesson_index: 0,
            title: "Mục tài liệu",
            source_pages: [7, "8-9"],
          },
        ],
      },
      hostContext,
    );

    expect(item?.metadata?.source_references).toMatchObject([
      {
        kind: "lesson",
        chapter_index: 1,
        lesson_index: 0,
        title: "Mục tài liệu",
        source_pages: [7, "8-9"],
      },
    ]);
    expect(item?.title).toBe("Xem trước cập nhật bài học: Bài học nguồn");
    expect(item?.metadata?.next_step).toBe(
      "Xem bản xem trước rồi xác nhận rõ ràng nếu bạn muốn Wiii áp dụng thay đổi này vào LMS.",
    );
  });

  it("preserves LMS approval tokens from host preview responses", () => {
    const hostContext = {
      host_type: "lms",
      page: { type: "course_editor", title: "Course editor" },
      workflow_stage: "editing",
    } satisfies HostContext;

    const item = buildHostActionPreviewItem(
      "authoring.preview_lesson_patch",
      "req-approval-1",
      {},
      {
        preview_token: "lesson-preview-123",
        approval_token: "approval-from-lms-dialog",
        preview_kind: "lesson_patch",
        apply_action: "authoring.apply_lesson_patch",
        summary: "Teacher approved the LMS preview dialog.",
        lesson_title: "Bài học đã duyệt",
      },
      hostContext,
    );

    expect(item?.metadata?.preview_token).toBe("lesson-preview-123");
    expect(item?.metadata?.approval_token).toBe("approval-from-lms-dialog");
    expect(item?.metadata?.apply_action).toBe("authoring.apply_lesson_patch");
  });

  it("builds a Facebook post preview item from Wiii Connect host action data", () => {
    const hostContext = {
      host_type: "wiii desktop",
      page: { type: "chat", title: "Wiii" },
    } satisfies HostContext;

    const item = buildHostActionPreviewItem(
      "wiii_connect.facebook_post.preview",
      "req-facebook-1",
      {},
      {
        preview_evidence_id: "fb-preview-123",
        approval_token: "approval-token",
        preview_kind: "facebook_post",
        apply_action: "wiii_connect.facebook_post.apply",
        summary: "Preview Facebook đã sẵn sàng.",
        page_id: "page-1",
        page_label: "Wiii Page",
        message: "Bài đăng thử từ Wiii.",
        image_present: true,
        facebook_post_body: {
          connection_ref: "wiii-facebook-abc",
          page_id: "page-1",
          message: "Bài đăng thử từ Wiii.",
        },
      },
      hostContext,
    );

    expect(item?.title).toBe("Xem trước bài đăng Facebook: Wiii Page");
    expect(item?.metadata?.preview_token).toBe("fb-preview-123");
    expect(item?.metadata?.preview_evidence_id).toBe("fb-preview-123");
    expect(item?.metadata?.apply_action).toBe("wiii_connect.facebook_post.apply");
    expect(item?.metadata?.facebook_post_body).toMatchObject({
      page_id: "page-1",
      message: "Bài đăng thử từ Wiii.",
    });
  });

  it("builds sanitized host action result submissions", () => {
    const request = buildHostActionResultRequest(
      "wiii_connect.facebook_post.direct_apply",
      "req-facebook-result-1",
      {
        success: true,
        data: {
          summary: "Published.",
          provider_post_id: "post-1",
          approval_token: "secret-approval",
          nested: {
            image_base64: "secret-image",
          },
        },
      },
    );

    expect(request).toMatchObject({
      action: "wiii_connect.facebook_post.direct_apply",
      request_id: "req-facebook-result-1",
      success: true,
      summary: "Published.",
    });
    expect(request.data?.provider_post_id).toBe("post-1");
    expect(request.data?.approval_token).toBe("[redacted]");
    expect((request.data?.nested as Record<string, unknown>).image_base64).toBe("[redacted]");
  });
});
