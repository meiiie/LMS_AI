/**
 * Sprint 228: "Visual Tuong Tac" — InlineHtmlWidget + MarkdownRenderer widget routing.
 *
 * Tests:
 * - MarkdownRenderer routes ```widget code blocks to InlineHtmlWidget
 * - Normal code blocks still render via CodeBlock
 * - Multiple widgets in same message
 * - Widget receives correct code content
 */
import { describe, it, expect, vi } from "vitest";

// Mock InlineHtmlWidget (lazy-loaded in MarkdownRenderer)
vi.mock("@/components/common/InlineHtmlWidget", () => ({
  default: ({ code, className }: { code: string; className?: string }) => (
    <div data-testid="inline-widget" data-code={code} className={className}>
      Widget Preview
    </div>
  ),
}));

// Mock MermaidDiagram (lazy-loaded)
vi.mock("@/components/common/MermaidDiagram", () => ({
  default: ({ code }: { code: string }) => (
    <div data-testid="mermaid-diagram" data-code={code}>Mermaid</div>
  ),
}));

// Mock CodeBlock
vi.mock("@/components/common/CodeBlock", () => ({
  CodeBlock: ({ language, code }: { language: string; code: string }) => (
    <pre data-testid="code-block" data-lang={language}><code>{code}</code></pre>
  ),
}));

// Mock KaTeX CSS import
vi.mock("katex/dist/katex.min.css", () => ({}));

import { render, screen, waitFor } from "@testing-library/react";
import { MarkdownRenderer } from "@/components/common/MarkdownRenderer";

describe("Sprint 228: Widget Routing in MarkdownRenderer", () => {
  const lazyMarkdownTimeout = { timeout: 10_000 };

  it("renders widget code blocks via InlineHtmlWidget", async () => {
    const content = "Here is a chart:\n\n```widget\n<div>Hello Widget</div>\n```\n\nNice!";
    render(<MarkdownRenderer content={content} />);
    await waitFor(() => {
      expect(screen.getByTestId("inline-widget")).toBeTruthy();
    });
  });

  it("renders normal code blocks via CodeBlock (not widget)", async () => {
    const content = "```python\nprint('hello')\n```";
    render(<MarkdownRenderer content={content} />);
    const codeBlock = await screen.findByTestId("code-block", undefined, lazyMarkdownTimeout);
    expect(codeBlock.getAttribute("data-lang")).toBe("python");
    expect(screen.queryByTestId("inline-widget")).toBeNull();
  });

  it("does not render widget for html code blocks", async () => {
    const content = "```html\n<div>Normal HTML code</div>\n```";
    render(<MarkdownRenderer content={content} />);
    const codeBlock = await screen.findByTestId("code-block", undefined, lazyMarkdownTimeout);
    expect(codeBlock.getAttribute("data-lang")).toBe("html");
    expect(screen.queryByTestId("inline-widget")).toBeNull();
  });

  it("renders multiple widget blocks in same message", async () => {
    const content = [
      "First chart:",
      "",
      "```widget",
      "<canvas id='c1'></canvas>",
      "```",
      "",
      "Second chart:",
      "",
      "```widget",
      "<canvas id='c2'></canvas>",
      "```",
    ].join("\n");
    render(<MarkdownRenderer content={content} />);
    await waitFor(() => {
      const widgets = screen.getAllByTestId("inline-widget");
      expect(widgets.length).toBe(2);
    });
  });

  it("passes raw code to InlineHtmlWidget", async () => {
    const widgetCode = "console.log('test')";
    const content = "```widget\n" + widgetCode + "\n```";
    render(<MarkdownRenderer content={content} />);
    await waitFor(() => {
      const widget = screen.getByTestId("inline-widget");
      expect(widget.getAttribute("data-code")).toContain("test");
    });
  });

  it("does not render widget for javascript code blocks", async () => {
    const content = "```javascript\nconst x = 1;\n```";
    render(<MarkdownRenderer content={content} />);
    const codeBlock = await screen.findByTestId("code-block", undefined, lazyMarkdownTimeout);
    expect(codeBlock.getAttribute("data-lang")).toBe("javascript");
    expect(screen.queryByTestId("inline-widget")).toBeNull();
  });

  it("renders widget alongside regular markdown text", async () => {
    const content = [
      "# Title",
      "",
      "Some text.",
      "",
      "```widget",
      "<p>Interactive</p>",
      "```",
      "",
      "More text.",
    ].join("\n");
    render(<MarkdownRenderer content={content} />);
    await waitFor(() => {
      expect(screen.getByTestId("inline-widget")).toBeTruthy();
    });
  });

  it("shows a pending widget shell while the closing fence has not arrived yet", () => {
    const content = [
      "Dang giai thich truoc khi widget xuat hien.",
      "",
      "```widget",
      "<div>Dang stream widget",
    ].join("\n");

    render(<MarkdownRenderer content={content} />);

    expect(screen.getByTestId("pending-inline-widget")).toBeTruthy();
    expect(screen.queryByText("```widget")).toBeNull();
  });
});
