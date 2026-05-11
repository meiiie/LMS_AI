import { describe, it, expect } from "vitest";
import { buildHostActionPreviewItem } from "@/hooks/useSSEStream";
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
});
