/**
 * Tests for MentionPicker (autocomplete dropdown) + MentionMirror
 * (inline highlight overlay) — Wiii Pointy v3.0 Phase 2.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MentionPicker } from "../components/chat/MentionPicker";
import { MentionMirror } from "../components/chat/MentionMirror";
import { MessageMentions } from "../components/chat/MessageMentions";
import { suggestMentions } from "../lib/skill-mentions";

describe("MentionPicker", () => {
  it("renders all 3 skills when fragment is empty", () => {
    const onSelect = vi.fn();
    const onHover = vi.fn();
    render(
      <MentionPicker
        suggestions={suggestMentions("")}
        selectedIndex={0}
        fragment=""
        onSelect={onSelect}
        onHover={onHover}
      />,
    );
    expect(screen.getByText("Wiii Pointy")).toBeTruthy();
    expect(screen.getByText("Web Search")).toBeTruthy();
    expect(screen.getByText("Code Studio")).toBeTruthy();
  });

  it("shows only matching skills when fragment is 'poi'", () => {
    const { container } = render(
      <MentionPicker
        suggestions={suggestMentions("poi")}
        selectedIndex={0}
        fragment="poi"
        onSelect={vi.fn()}
        onHover={vi.fn()}
      />,
    );
    // Each suggestion row has the canonical id rendered as `@<id>`.
    expect(container.textContent).toContain("@wiii-pointy");
    expect(container.textContent).not.toContain("@web-search");
  });

  it("fires onSelect when an item is clicked", () => {
    const onSelect = vi.fn();
    render(
      <MentionPicker
        suggestions={suggestMentions("")}
        selectedIndex={0}
        fragment=""
        onSelect={onSelect}
        onHover={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText("Wiii Pointy"));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect.mock.calls[0][0].entry.id).toBe("wiii-pointy");
  });

  it("fires onHover with index when mouse enters a row", () => {
    const onHover = vi.fn();
    render(
      <MentionPicker
        suggestions={suggestMentions("")}
        selectedIndex={0}
        fragment=""
        onSelect={vi.fn()}
        onHover={onHover}
      />,
    );
    fireEvent.mouseEnter(screen.getByText("Web Search"));
    expect(onHover).toHaveBeenCalled();
    // Web Search is index 1 (after Wiii Pointy at 0).
    expect(onHover.mock.calls[onHover.mock.calls.length - 1][0]).toBe(1);
  });

  it("renders empty when no suggestions match", () => {
    const { container } = render(
      <MentionPicker
        suggestions={[]}
        selectedIndex={0}
        fragment="xyz"
        onSelect={vi.fn()}
        onHover={vi.fn()}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders SVG icons (lucide), not emoji", () => {
    const { container } = render(
      <MentionPicker
        suggestions={suggestMentions("")}
        selectedIndex={0}
        fragment=""
        onSelect={vi.fn()}
        onHover={vi.fn()}
      />,
    );
    // Lucide renders <svg> elements. Each row should have one.
    const svgs = container.querySelectorAll("svg");
    expect(svgs.length).toBeGreaterThanOrEqual(3); // 3 skill icons
    // No emoji characters in text — quick sanity check.
    expect(container.textContent).not.toContain("🎯");
    expect(container.textContent).not.toContain("🔍");
    expect(container.textContent).not.toContain("✨");
  });
});
describe("MentionMirror", () => {
  it("returns null when text has no mentions", () => {
    const { container } = render(
      <MentionMirror text="hello world" className="w-full text-[14px]" />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("returns null on empty input", () => {
    const { container } = render(
      <MentionMirror text="" className="w-full text-[14px]" />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders mention chunk với data-mention-id when @canonical-id present", () => {
    const { container } = render(
      <MentionMirror
        text="@wiii-pointy chỉ cho tôi"
        className="w-full text-[14px]"
      />,
    );
    const chip = container.querySelector('[data-mention-id="wiii-pointy"]');
    expect(chip).not.toBeNull();
    expect(chip?.textContent).toBe("@wiii-pointy");
  });

  it("resolves alias '@pointy' → canonical 'wiii-pointy'", () => {
    const { container } = render(
      <MentionMirror text="@pointy chỉ" className="w-full text-[14px]" />,
    );
    const chip = container.querySelector('[data-mention-id="wiii-pointy"]');
    expect(chip).not.toBeNull();
    // Display text giữ nguyên typed form (@pointy), not canonical.
    expect(chip?.textContent).toBe("@pointy");
  });

  it("renders multiple mentions in one message", () => {
    const { container } = render(
      <MentionMirror
        text="@wiii-pointy và @web-search"
        className="w-full text-[14px]"
      />,
    );
    expect(container.querySelector('[data-mention-id="wiii-pointy"]'))
      .not.toBeNull();
    expect(container.querySelector('[data-mention-id="web-search"]'))
      .not.toBeNull();
  });

  it("ignores unknown mention ids (renders as plain text)", () => {
    const { container } = render(
      <MentionMirror
        text="@unknown-skill hello"
        className="w-full text-[14px]"
      />,
    );
    // Returns null because no VALID mentions present.
    expect(container.firstChild).toBeNull();
  });

  it("preserves leading whitespace in plain text segments", () => {
    const { container } = render(
      <MentionMirror
        text="hỏi @web-search tin tức hôm nay"
        className="w-full text-[14px]"
      />,
    );
    // Mirror should contain "hỏi " before the chip.
    expect(container.textContent).toContain("hỏi");
    expect(container.textContent).toContain("@web-search");
    expect(container.textContent).toContain("tin tức hôm nay");
  });

  it("uses different highlight class per skill (visual differentiation)", () => {
    const { container } = render(
      <MentionMirror
        text="@wiii-pointy @web-search @visual-code-gen"
        className="w-full text-[14px]"
      />,
    );
    const pointyChip = container.querySelector('[data-mention-id="wiii-pointy"]');
    const webChip = container.querySelector('[data-mention-id="web-search"]');
    const codeChip = container.querySelector('[data-mention-id="visual-code-gen"]');
    expect(pointyChip?.className).toMatch(/orange/);
    expect(webChip?.className).toMatch(/sky/);
    expect(codeChip?.className).toMatch(/violet/);
  });
});

describe("MessageMentions (chat bubble persistent chip)", () => {
  it("renders plain text without chips when no mention present", () => {
    const { container } = render(
      <MessageMentions text="hello world" />,
    );
    expect(container.textContent).toBe("hello world");
    expect(container.querySelector("[data-mention-id]")).toBeNull();
  });

  it("renders @mention as visible chip với icon + skill label", () => {
    const { container } = render(
      <MessageMentions text="@wiii-pointy chỉ giúp" />,
    );
    const chip = container.querySelector('[data-mention-id="wiii-pointy"]');
    expect(chip).not.toBeNull();
    // Chip displays the friendly label, not the raw @id.
    expect(chip?.textContent).toContain("Wiii Pointy");
    // SVG icon present.
    expect(chip?.querySelector("svg")).not.toBeNull();
    // Tooltip shows raw + canonical.
    expect(chip?.getAttribute("title")).toContain("@wiii-pointy");
  });

  it("alias '@pointy' resolves to canonical chip 'Wiii Pointy'", () => {
    const { container } = render(<MessageMentions text="@pointy chỉ" />);
    const chip = container.querySelector('[data-mention-id="wiii-pointy"]');
    expect(chip).not.toBeNull();
    expect(chip?.textContent).toContain("Wiii Pointy");
    expect(chip?.getAttribute("title")).toContain("@pointy");
  });

  it("renders multiple mentions — each as its own chip", () => {
    const { container } = render(
      <MessageMentions text="@wiii-pointy và @web-search hôm nay" />,
    );
    expect(container.querySelectorAll("[data-mention-id]").length).toBe(2);
  });

  it("preserves surrounding plain text intact", () => {
    const { container } = render(
      <MessageMentions text="hôm nay @web-search tin tức gì hot" />,
    );
    expect(container.textContent).toContain("hôm nay");
    expect(container.textContent).toContain("tin tức gì hot");
    // Chip should display "Web Search" not "@web-search"
    expect(container.textContent).toContain("Web Search");
  });
});
