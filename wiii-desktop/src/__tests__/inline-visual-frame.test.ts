import { describe, expect, it } from "vitest";
import { buildVisualFrameDocument } from "@/lib/visual-frame-document";

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
      sizingMode: "viewport",
      showFrameIntro: false,
      hostShellMode: "force",
    });

    expect(wrapped).toContain("overflow: auto;");
    expect(wrapped).toContain("overscroll-behavior: contain;");
    expect(wrapped).toContain('data-wiii-sizing-mode="viewport"');
    expect(wrapped).toContain("state.parentState.sizingMode");
    expect(wrapped).toContain("function measureHeight()");
    expect(wrapped).toContain("resizeObserver.observe(document.documentElement)");
  });

  it("strips blocked external font assets before applying the iframe CSP", () => {
    const wrapped = buildVisualFrameDocument(
      [
        "<!DOCTYPE html>",
        "<html>",
        "<head>",
        "<link rel=\"preconnect\" href=\"https://fonts.gstatic.com\">",
        "<link rel=\"stylesheet\" href=\"https://fonts.googleapis.com/css?family=Open+Sans:300,400,600\">",
        "<style>@import url('https://fonts.googleapis.com/css?family=Roboto'); body{font-family:sans-serif}</style>",
        "</head>",
        "<body><main>Preview</main></body>",
        "</html>",
      ].join(""),
      {
        title: "Preview",
        sessionId: "vs-fonts",
        shellVariant: "immersive",
        frameKind: "app",
        hostShellMode: "force",
      },
    );

    expect(wrapped).not.toContain("fonts.googleapis.com");
    expect(wrapped).not.toContain("fonts.gstatic.com");
    expect(wrapped).toContain("Content-Security-Policy");
    expect(wrapped).toContain("body{font-family:sans-serif}");
  });
});
