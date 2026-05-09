/**
 * Tests for PageScanner — DOM inventory contract.
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { PageScanner, formatTargetsForLLM } from "../scanner";

describe("PageScanner", () => {
  let scanner: PageScanner | null = null;

  beforeEach(() => {
    document.body.innerHTML = "";
  });

  afterEach(() => {
    scanner?.dispose();
    scanner = null;
  });

  it("detects buttons with id", () => {
    document.body.innerHTML = `
      <button id="send-btn">Gửi</button>
      <button id="attach-btn">Đính kèm</button>
    `;
    scanner = new PageScanner({ observe: false });
    const targets = scanner.getTargets();
    expect(targets).toHaveLength(2);
    expect(targets.find((t) => t.id === "send-btn")).toBeDefined();
    expect(targets.find((t) => t.id === "attach-btn")).toBeDefined();
  });

  it("prefers data-wiii-id over CSS id", () => {
    document.body.innerHTML = `
      <button id="css-id" data-wiii-id="wiii-handle">Click</button>
    `;
    scanner = new PageScanner({ observe: false });
    const targets = scanner.getTargets();
    expect(targets).toHaveLength(1);
    expect(targets[0].id).toBe("wiii-handle");
    expect(targets[0].selector).toBe("wiii-handle");
  });

  it("infers role from HTML tag", () => {
    document.body.innerHTML = `
      <button id="b">B</button>
      <a id="l" href="#">L</a>
      <input id="i" type="text" />
    `;
    scanner = new PageScanner({ observe: false });
    const targets = scanner.getTargets();
    expect(targets.find((t) => t.id === "b")?.role).toBe("button");
    expect(targets.find((t) => t.id === "l")?.role).toBe("link");
    expect(targets.find((t) => t.id === "i")?.role).toBe("input");
  });

  it("infers role from ARIA role attribute", () => {
    document.body.innerHTML = `
      <div id="custom-btn" role="button" data-wiii-id="custom-btn">Custom</div>
      <span id="custom-link" role="link" data-wiii-id="custom-link">Link</span>
    `;
    scanner = new PageScanner({ observe: false });
    const targets = scanner.getTargets();
    expect(targets.find((t) => t.id === "custom-btn")?.role).toBe("button");
    expect(targets.find((t) => t.id === "custom-link")?.role).toBe("link");
  });

  it("supports data-wiii-role for stable non-button wrappers", () => {
    document.body.innerHTML = `
      <span data-wiii-id="chat-send-button" data-wiii-role="button" aria-label="Send message">
        <button aria-label="Stop generation"></button>
      </span>
    `;
    scanner = new PageScanner({ observe: false });
    const target = scanner.getTargets().find((t) => t.id === "chat-send-button");
    expect(target?.role).toBe("button");
    expect(target?.label).toBe("Send message");
  });

  it("dedupes repeated data-wiii-id entries and keeps the visible candidate", () => {
    document.body.innerHTML = `
      <button data-wiii-id="attach-file-button" aria-label="Old attach"></button>
      <button data-wiii-id="attach-file-button" aria-label="Current attach"></button>
    `;
    const [oldAttach, currentAttach] = Array.from(
      document.querySelectorAll<HTMLElement>('[data-wiii-id="attach-file-button"]'),
    );
    Object.defineProperty(oldAttach, "getBoundingClientRect", {
      configurable: true,
      value: () => ({
        left: -200,
        top: -200,
        right: -168,
        bottom: -168,
        width: 32,
        height: 32,
      }),
    });
    Object.defineProperty(currentAttach, "getBoundingClientRect", {
      configurable: true,
      value: () => ({
        left: 40,
        top: 40,
        right: 72,
        bottom: 72,
        width: 32,
        height: 32,
      }),
    });

    scanner = new PageScanner({ observe: false });
    const matches = scanner
      .getTargets()
      .filter((t) => t.id === "attach-file-button");
    expect(matches).toHaveLength(1);
    expect(matches[0].label).toBe("Current attach");
  });

  it("infers label from aria-label first", () => {
    document.body.innerHTML = `
      <button id="b" aria-label="Gửi tin nhắn" title="Title">Click here</button>
    `;
    scanner = new PageScanner({ observe: false });
    const targets = scanner.getTargets();
    expect(targets[0].label).toBe("Gửi tin nhắn");
  });

  it("falls back to text content when no aria-label", () => {
    document.body.innerHTML = `<button id="b">Send Message</button>`;
    scanner = new PageScanner({ observe: false });
    const targets = scanner.getTargets();
    expect(targets[0].label).toBe("Send Message");
  });

  it("excludes disabled buttons", () => {
    document.body.innerHTML = `
      <button id="ok" >OK</button>
      <button id="bad" disabled>Disabled</button>
    `;
    scanner = new PageScanner({ observe: false });
    const targets = scanner.getTargets();
    expect(targets.find((t) => t.id === "ok")).toBeDefined();
    expect(targets.find((t) => t.id === "bad")).toBeUndefined();
  });

  it("excludes elements with aria-hidden=true", () => {
    document.body.innerHTML = `
      <button id="visible">V</button>
      <button id="hidden" aria-hidden="true">H</button>
    `;
    scanner = new PageScanner({ observe: false });
    const targets = scanner.getTargets();
    expect(targets.find((t) => t.id === "visible")).toBeDefined();
    expect(targets.find((t) => t.id === "hidden")).toBeUndefined();
  });

  it("marks click_safe correctly from data-wiii-click-safe", () => {
    document.body.innerHTML = `
      <button id="a" data-wiii-id="a" data-wiii-click-safe="true">Safe</button>
      <button id="b" data-wiii-id="b">Unsafe (default)</button>
    `;
    scanner = new PageScanner({ observe: false });
    const targets = scanner.getTargets();
    expect(targets.find((t) => t.id === "a")?.click_safe).toBe(true);
    expect(targets.find((t) => t.id === "b")?.click_safe).toBe(false);
  });

  it("captures click_kind metadata", () => {
    document.body.innerHTML = `
      <button id="x" data-wiii-id="x"
        data-wiii-click-safe="true"
        data-wiii-click-kind="navigate">Go</button>
    `;
    scanner = new PageScanner({ observe: false });
    const targets = scanner.getTargets();
    expect(targets[0].click_kind).toBe("navigate");
  });

  it("auto-discovers labelled elements without explicit handles", () => {
    document.body.innerHTML = `<button>No handle</button>`;
    scanner = new PageScanner({ observe: false });
    const targets = scanner.getTargets();
    expect(targets).toHaveLength(1);
    expect(targets[0].id).toMatch(/^auto:button:/);
    expect(targets[0].label).toBe("No handle");
  });

  it("skips anonymous elements without a stable semantic handle", () => {
    document.body.innerHTML = `<button aria-label=""></button>`;
    scanner = new PageScanner({ observe: false });
    const targets = scanner.getTargets();
    expect(targets).toHaveLength(0);
  });

  it("scanNow() forces immediate refresh", () => {
    document.body.innerHTML = `<button id="a">A</button>`;
    scanner = new PageScanner({ observe: false });
    expect(scanner.getTargets()).toHaveLength(1);

    document.body.innerHTML = `
      <button id="a">A</button>
      <button id="b">B</button>
    `;
    // Without scanNow(), cached result is stale (since observe:false).
    expect(scanner.getTargets()).toHaveLength(1);
    const fresh = scanner.scanNow();
    expect(fresh).toHaveLength(2);
  });

  it("respects maxTargets clip", () => {
    let html = "";
    for (let i = 0; i < 100; i++) {
      html += `<button id="btn-${i}">B${i}</button>`;
    }
    document.body.innerHTML = html;
    scanner = new PageScanner({ observe: false, maxTargets: 25 });
    expect(scanner.getTargets().length).toBeLessThanOrEqual(25);
  });

  it("subscribe() pushes initial snapshot then updates", () => {
    document.body.innerHTML = `<button id="a">A</button>`;
    scanner = new PageScanner({ observe: false });
    const calls: number[] = [];
    const unsub = scanner.subscribe((targets) => {
      calls.push(targets.length);
    });
    // Initial push.
    expect(calls).toEqual([1]);
    // Manually trigger rescan with new content.
    document.body.innerHTML = `
      <button id="a">A</button>
      <button id="b">B</button>
    `;
    scanner.scanNow();
    expect(calls).toEqual([1, 2]);
    unsub();
  });
});

describe("formatTargetsForLLM", () => {
  it("returns 'no targets' message when empty", () => {
    expect(formatTargetsForLLM([])).toBe(
      "No pointable elements detected on screen.",
    );
  });

  it("includes id, role, label in output", () => {
    document.body.innerHTML = `
      <button id="b" aria-label="Gửi" data-wiii-click-safe="true">B</button>
    `;
    const scanner = new PageScanner({ observe: false });
    const targets = scanner.getTargets();
    const out = formatTargetsForLLM(targets);
    expect(out).toContain('id="b"');
    expect(out).toContain("role=button");
    expect(out).toContain('label="Gửi"');
    expect(out).toContain("click_safe");
    scanner.dispose();
  });

  it("clips to maxLines", () => {
    let html = "";
    for (let i = 0; i < 50; i++) {
      html += `<button id="btn-${i}">B${i}</button>`;
    }
    document.body.innerHTML = html;
    const scanner = new PageScanner({ observe: false });
    const out = formatTargetsForLLM(scanner.getTargets(), 10);
    expect(out).toContain("more elements omitted");
    scanner.dispose();
  });
});
