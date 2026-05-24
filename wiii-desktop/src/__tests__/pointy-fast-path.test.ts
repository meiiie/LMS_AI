import { describe, expect, it } from "vitest";
import type { HostContext } from "@/stores/host-context-store";
import {
  buildPointyFastPathAction,
  getPointyTargetsFromContext,
  looksExplicitPointyTurn,
  normalizePointyText,
  POINTY_FAST_PATH_SOURCE,
} from "@/lib/pointy-fast-path";

function makeHostContext(targets: unknown[]): HostContext {
  return {
    host_type: "lms",
    page: {
      type: "course_list",
      title: "Khoa hoc cua toi",
      metadata: {
        available_targets: targets,
      },
    },
  };
}

describe("pointy fast path", () => {
  it("normalizes Vietnamese UI prompts for local matching", () => {
    expect(normalizePointyText("Wiii oi, nut Kham pha khoa hoc o dau?")).toContain(
      "kham pha khoa hoc o dau",
    );
    expect(normalizePointyText("Wiii ơi, Khám phá khóa học ở đâu?")).toContain(
      "kham pha khoa hoc o dau",
    );
  });

  it("extracts valid Pointy targets from host context metadata", () => {
    const ctx = makeHostContext([
      { id: "browse-courses", selector: "[data-wiii-id=\"browse-courses\"]", label: "Kham pha" },
      { id: "", selector: "#bad" },
      "noise",
    ]);

    expect(getPointyTargetsFromContext(ctx)).toEqual([
      expect.objectContaining({ id: "browse-courses", label: "Kham pha" }),
    ]);
  });

  it("highlights the matching target immediately for where-is prompts", () => {
    const ctx = makeHostContext([
      {
        id: "browse-courses",
        selector: "[data-wiii-id=\"browse-courses\"]",
        label: "Kham pha khoa hoc",
        click_safe: true,
      },
    ]);

    const action = buildPointyFastPathAction("Wiii oi, nut Kham pha khoa hoc o dau?", ctx);

    expect(action).toMatchObject({
      action: "ui.highlight",
      target: expect.objectContaining({ id: "browse-courses" }),
      params: expect.objectContaining({ selector: "browse-courses" }),
      reason: "locate",
    });
  });

  it("highlights accented where-is prompts even when the user does not say button", () => {
    const ctx = makeHostContext([
      {
        id: "browse-courses-link",
        selector: "[data-wiii-id=\"browse-courses-link\"]",
        label: "Khám phá khóa học",
        click_safe: true,
      },
    ]);

    const action = buildPointyFastPathAction("Wiii ơi, Khám phá khóa học ở đâu?", ctx);

    expect(action).toMatchObject({
      action: "ui.highlight",
      target: expect.objectContaining({ id: "browse-courses-link" }),
      params: expect.objectContaining({ selector: "browse-courses-link" }),
      reason: "locate",
    });
  });

  it("clicks only explicitly safe navigation targets for open prompts", () => {
    const ctx = makeHostContext([
      {
        id: "browse-courses-link",
        selector: "[data-wiii-id=\"browse-courses-link\"]",
        label: "Kham pha khoa hoc",
        click_safe: true,
        click_kind: "navigation",
      },
    ]);

    const action = buildPointyFastPathAction("Wiii mo Kham pha khoa hoc giup toi", ctx);

    expect(action).toMatchObject({
      action: "ui.click",
      params: expect.objectContaining({
        selector: "browse-courses-link",
        message: "Wiii đang mở Kham pha khoa hoc cho bạn.",
      }),
      reason: "click",
    });
  });

  it("demotes unsafe click intents to highlight instead of clicking", () => {
    const ctx = makeHostContext([
      {
        id: "submit-quiz",
        selector: "[data-wiii-id=\"submit-quiz\"]",
        label: "Nop bai",
        click_safe: false,
      },
    ]);

    const action = buildPointyFastPathAction("Wiii bam nut Nop bai giup toi", ctx);

    expect(action).toMatchObject({
      action: "ui.highlight",
      params: expect.objectContaining({
        message: "Đây là Nop bai. Wiii trỏ vào để bạn thấy ngay.",
      }),
      reason: "unsafe_click_demoted",
    });
  });

  it("prefers the send-message button over edit-message controls", () => {
    const ctx = makeHostContext([
      {
        id: "auto:button:chinh-sua-tin-nhan-8",
        selector: "[data-wiii-id=\"auto:button:chinh-sua-tin-nhan-8\"]",
        label: "Chinh sua tin nhan",
        click_safe: false,
      },
      {
        id: "chat-send-button",
        selector: "[data-wiii-id=\"chat-send-button\"]",
        label: "Gui tin nhan",
        click_safe: false,
      },
    ]);

    const action = buildPointyFastPathAction(
      "Pointy hay chi vao nut Gui tin nhan va noi mot lan thoi.",
      ctx,
    );

    expect(action).toMatchObject({
      action: "ui.highlight",
      target: expect.objectContaining({ id: "chat-send-button" }),
      params: expect.objectContaining({ selector: "chat-send-button" }),
    });

    const retryAction = buildPointyFastPathAction(
      "Pointy, chi lai nut Gui va noi that ngan thoi.",
      ctx,
    );

    expect(retryAction).toMatchObject({
      action: "ui.highlight",
      target: expect.objectContaining({ id: "chat-send-button" }),
      params: expect.objectContaining({ selector: "chat-send-button" }),
    });
  });

  it("uses the stable Wiii desktop send button when the scanner inventory is stale", () => {
    const ctx: HostContext = {
      ...makeHostContext([
        {
          id: "auto:button:chinh-sua-tin-nhan-9",
          selector: "[data-wiii-id=\"auto:button:chinh-sua-tin-nhan-9\"]",
          label: "Chinh sua tin nhan",
          click_safe: false,
        },
      ]),
      host_type: "wiii-desktop",
      page: {
        type: "chat",
        metadata: {
          available_targets: [
            {
              id: "auto:button:chinh-sua-tin-nhan-9",
              selector: "[data-wiii-id=\"auto:button:chinh-sua-tin-nhan-9\"]",
              label: "Chinh sua tin nhan",
              click_safe: false,
            },
          ],
        },
      },
    };

    const action = buildPointyFastPathAction(
      "Pointy hay chi vao nut Gui tin nhan va noi mot lan thoi.",
      ctx,
    );

    expect(action).toMatchObject({
      action: "ui.highlight",
      target: expect.objectContaining({ id: "chat-send-button" }),
      params: expect.objectContaining({ selector: "chat-send-button" }),
    });
  });

  it("does not reissue an action after pointy fast-path feedback", () => {
    const ctx: HostContext = {
      ...makeHostContext([
        {
          id: "browse-courses",
          selector: "[data-wiii-id=\"browse-courses\"]",
          label: "Kham pha khoa hoc",
        },
      ]),
      host_action_feedback: {
        last_action_result: {
          params: { source: POINTY_FAST_PATH_SOURCE },
        },
      },
    };

    expect(buildPointyFastPathAction("Wiii oi, nut Kham pha khoa hoc o dau?", ctx)).toBeNull();
  });

  it("does not hijack semantic web-search prompts as search-button pointing", () => {
    const ctx = makeHostContext([
      {
        id: "search-button",
        selector: "[data-wiii-id=\"search-button\"]",
        label: "Mo tim kiem",
        click_safe: true,
      },
    ]);

    expect(
      buildPointyFastPathAction(
        "Tim tren web giup minh: OpenAI Responses API dung de lam gi? Ma kiem thu WEB-527.",
        ctx,
      ),
    ).toBeNull();
  });

  it("does not hijack capability inventory prompts because of 'anh dau vao'", () => {
    const ctx = makeHostContext([
      {
        id: "image-upload-button",
        selector: "[data-wiii-id=\"image-upload-button\"]",
        label: "Anh dau vao",
        click_safe: true,
      },
    ]);

    expect(
      buildPointyFastPathAction(
        "Wiii hien xu ly duoc anh dau vao, tao anh, Word, Excel, video toi muc nao?",
        ctx,
      ),
    ).toBeNull();
  });

  it("does not treat 'chi xac nhan' or semantic Pointy mentions as a UI pointing request", () => {
    const ctx = makeHostContext([
      {
        id: "auto:button:giai-thich-quy-tac-15-colregs",
        selector: "[data-wiii-id=\"auto:button:giai-thich-quy-tac-15-colregs\"]",
        label: "Giai thich Quy tac 15 COLREGs",
        click_safe: true,
      },
    ]);

    expect(
      buildPointyFastPathAction(
        "Nho giup minh: 3 uu tien bao cao la Pointy dang tin, RAG co nguon, UX binh tinh. Chi xac nhan da nho, khong giai thich dai.",
        ctx,
      ),
    ).toBeNull();
  });

  it("does not hijack visual simulation prompts because of the Vietnamese 'mo' token", () => {
    const ctx = makeHostContext([
      {
        id: "auto:button:giai-thich-quy-tac-15-colregs",
        selector: "[data-wiii-id=\"auto:button:giai-thich-quy-tac-15-colregs\"]",
        label: "Giai thich Quy tac 15 COLREGs",
        click_safe: true,
      },
    ]);

    expect(buildPointyFastPathAction("Mô phỏng Quy tắc 15 COLREGs", ctx)).toBeNull();
  });

  it("allows embodied Pointy only for explicit Pointy-style turns", () => {
    expect(looksExplicitPointyTurn("Pointy hay chi vao nut Gui tin nhan va noi mot lan thoi.")).toBe(true);
    expect(looksExplicitPointyTurn("Pointy, chi lai nut Gui va noi that ngan thoi.")).toBe(true);
    expect(looksExplicitPointyTurn("Wiii oi, nut dinh kem o dau?")).toBe(true);
    expect(looksExplicitPointyTurn("3 uu tien la Pointy dang tin va UX binh tinh.")).toBe(false);
    expect(looksExplicitPointyTurn("Noi ngan gon ve anh dau vao va dinh kem file trong Wiii.")).toBe(false);
    expect(looksExplicitPointyTurn("Wiii hien xu ly duoc anh dau vao, tao anh, Word, Excel, video toi muc nao?")).toBe(false);
    expect(looksExplicitPointyTurn("Bat dau", ["wiii-pointy"])).toBe(true);
  });

  it("does nothing when no visible target matches", () => {
    const ctx = makeHostContext([
      { id: "profile-link", selector: "[data-wiii-id=\"profile-link\"]", label: "Ho so" },
    ]);

    expect(buildPointyFastPathAction("Wiii oi hom nay sao roi?", ctx)).toBeNull();
  });
});
