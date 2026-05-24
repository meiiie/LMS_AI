import { describe, expect, it } from "vitest";
import { buildVisualFrameDocument } from "@/components/common/InlineVisualFrame";

describe("InlineVisualFrame host shell", () => {
  it("wraps full-document app html in the host shell when forced", () => {
    const html = [
      "<!DOCTYPE html>",
      "<html>",
      "<head><title>Pendulum</title></head>",
      "<body>",
      "<h1 class=\"widget-title\">Mo phong con lac</h1>",
      "<div class=\"sim-controls\">controls</div>",
      "<canvas id=\"sim\"></canvas>",
      "</body>",
      "</html>",
    ].join("");

    const wrapped = buildVisualFrameDocument(html, {
      title: "Mo phong Con lac Don",
      summary: "Mo phong tuong tac voi cac tham so co the dieu chinh.",
      sessionId: "vs-pendulum",
      shellVariant: "immersive",
      frameKind: "app",
      showFrameIntro: false,
      hostShellMode: "force",
    });

    expect(wrapped).toContain('data-wiii-host-shell="true"');
    expect(wrapped).toContain("wiii-host-shell-active");
    expect(wrapped).toContain("wiii-frame-shell");
    expect(wrapped).toContain("<div class=\"wiii-frame-content\"><h1 class=\"widget-title\">Mo phong con lac</h1>");
  });

  it("can render an intro shell for wrapped inline html documents when requested", () => {
    const wrapped = buildVisualFrameDocument("<div>Inline visual</div>", {
      title: "Compute cost",
      summary: "Figure nay chung minh chi phi tang nhanh theo context.",
      sessionId: "vs-inline",
      shellVariant: "editorial",
      frameKind: "inline_html",
      showFrameIntro: true,
      hostShellMode: "force",
    });

    expect(wrapped).toContain("wiii-frame-intro");
    expect(wrapped).toContain("Compute cost");
    expect(wrapped).toContain("Figure nay chung minh chi phi tang nhanh theo context.");
  });

  it("allows app frames to scroll inside the iframe instead of clipping tall simulations", () => {
    const wrapped = buildVisualFrameDocument("<main style=\"height:1400px\">Tall app</main>", {
      title: "Tall simulation",
      summary: "",
      sessionId: "vs-tall",
      shellVariant: "immersive",
      frameKind: "app",
      showFrameIntro: false,
      hostShellMode: "force",
    });

    expect(wrapped).toContain("overflow: auto;");
    expect(wrapped).toContain("overscroll-behavior: contain;");
    expect(wrapped).toContain("function measureHeight()");
    expect(wrapped).toContain("resizeObserver.observe(document.documentElement)");
  });
});
