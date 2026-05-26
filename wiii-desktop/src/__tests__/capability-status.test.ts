import { describe, expect, it } from "vitest";
import { buildCapabilityStatuses } from "@/lib/capability-status";

describe("buildCapabilityStatuses", () => {
  it("marks standalone Wiii as personal host with local Pointy", () => {
    const items = buildCapabilityStatuses({
      connectionStatus: "connected",
      capabilities: null,
      currentContext: null,
      isEmbedded: false,
    });

    expect(items.find((item) => item.id === "server")).toMatchObject({
      value: "Đã kết nối",
      tone: "ok",
    });
    expect(items.find((item) => item.id === "host")).toMatchObject({
      value: "Cá nhân",
      tone: "off",
    });
    expect(items.find((item) => item.id === "pointy")).toMatchObject({
      value: "Local",
      tone: "pending",
    });
  });

  it("detects LMS authoring preview and apply actions from host capabilities", () => {
    const items = buildCapabilityStatuses({
      connectionStatus: "connected",
      currentContext: {
        host_type: "lms",
        connector_id: "maritime-lms",
        page: { type: "course_editor", title: "COLREGs" },
      },
      capabilities: {
        host_type: "lms",
        host_name: "Maritime LMS",
        resources: ["current-page"],
        tools: [
          {
            name: "authoring.preview_lesson_patch",
            description: "Preview lesson",
          },
          {
            name: "authoring.apply_lesson_patch",
            description: "Apply lesson",
          },
          {
            name: "ui.cursor_move",
            description: "Move cursor",
          },
        ],
      },
      isEmbedded: true,
    });

    expect(items.find((item) => item.id === "host")).toMatchObject({
      label: "LMS",
      value: "Maritime LMS",
      tone: "ok",
    });
    expect(items.find((item) => item.id === "host_actions")).toMatchObject({
      value: "3 tác vụ",
      tone: "ok",
    });
    expect(items.find((item) => item.id === "lms_authoring")).toMatchObject({
      value: "Preview + Apply",
      tone: "ok",
    });
    expect(items.find((item) => item.id === "pointy")).toMatchObject({
      value: "Host",
      tone: "ok",
    });
  });

  it("shows embedded host as pending until context arrives", () => {
    const items = buildCapabilityStatuses({
      connectionStatus: "checking",
      capabilities: null,
      currentContext: null,
      isEmbedded: true,
    });

    expect(items.find((item) => item.id === "server")).toMatchObject({
      value: "Đang kiểm tra",
      tone: "pending",
    });
    expect(items.find((item) => item.id === "host")).toMatchObject({
      value: "Đang chờ",
      tone: "pending",
    });
  });
});
