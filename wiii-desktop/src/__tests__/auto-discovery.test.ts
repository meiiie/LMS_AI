/**
 * Tests for v8.0 auto-discovery — synthetic IDs from accessible name.
 */

import { describe, it, expect, beforeEach } from "vitest";
import {
  computeAccessibleName,
  syntheticIdFor,
  registerSyntheticId,
  resolveSyntheticId,
  clearSyntheticRegistry,
} from "../pointy-host/auto-discovery";

describe("computeAccessibleName", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("prefers aria-label over text content", () => {
    document.body.innerHTML = `<button aria-label="Send message">Click me</button>`;
    const el = document.querySelector("button")!;
    expect(computeAccessibleName(el)).toBe("Send message");
  });

  it("uses text content when aria-label/labelledby absent (button subtree)", () => {
    document.body.innerHTML = `<button>Login</button>`;
    const el = document.querySelector("button")!;
    expect(computeAccessibleName(el)).toBe("Login");
  });

  it("falls back to title only when no name found anywhere else (last resort)", () => {
    document.body.innerHTML = `<span title="Tooltip">⚙</span>`;
    const el = document.querySelector("span")!;
    // Per axe-core: title is step 2I, last resort. text content "⚙" wins.
    // For the test to use title, we need element with no text either.
    document.body.innerHTML = `<span title="Settings"></span>`;
    const el2 = document.querySelector("span")!;
    expect(computeAccessibleName(el2)).toBe("Settings");
  });

  it("axe-core: whitespace-only aria-label HALTS algorithm (does not fall through)", () => {
    document.body.innerHTML = `<button aria-label="   ">Real text</button>`;
    const el = document.querySelector("button")!;
    // Whitespace-only aria-label → halt → empty name (NOT "Real text").
    expect(computeAccessibleName(el)).toBe("");
  });

  it("resolves <label for=...> for inputs (Step 2D)", () => {
    document.body.innerHTML = `
      <label for="email-input">Email địa chỉ</label>
      <input id="email-input" type="email" />
    `;
    const el = document.querySelector("input")!;
    expect(computeAccessibleName(el)).toBe("Email địa chỉ");
  });

  it("resolves wrapping <label> for inputs", () => {
    document.body.innerHTML = `
      <label>Tên người dùng <input id="user" type="text" /></label>
    `;
    const el = document.querySelector("input")!;
    expect(computeAccessibleName(el)).toContain("Tên người dùng");
  });

  it("resolves <fieldset>/<legend> as Step 2D", () => {
    document.body.innerHTML = `
      <fieldset>
        <legend>Personal info</legend>
        <input type="text" />
      </fieldset>
    `;
    const fs = document.querySelector("fieldset")!;
    expect(computeAccessibleName(fs)).toBe("Personal info");
  });

  it("resolves <table>/<caption>", () => {
    document.body.innerHTML = `
      <table>
        <caption>Sales 2026</caption>
        <tr><td>data</td></tr>
      </table>
    `;
    const t = document.querySelector("table")!;
    expect(computeAccessibleName(t)).toBe("Sales 2026");
  });

  it("uses <img alt> when present", () => {
    document.body.innerHTML = `<img alt="Wiii logo" src="x" />`;
    const el = document.querySelector("img")!;
    expect(computeAccessibleName(el)).toBe("Wiii logo");
  });

  it("uses placeholder for input elements", () => {
    document.body.innerHTML = `<input type="text" placeholder="Search..." />`;
    const el = document.querySelector("input")!;
    expect(computeAccessibleName(el)).toBe("Search...");
  });

  it("returns empty string when nothing identifies the element", () => {
    document.body.innerHTML = `<button></button>`;
    const el = document.querySelector("button")!;
    expect(computeAccessibleName(el)).toBe("");
  });

  it("resolves aria-labelledby to referenced element text", () => {
    document.body.innerHTML = `
      <h2 id="dialog-title">Confirm action</h2>
      <button aria-labelledby="dialog-title">OK</button>
    `;
    const el = document.querySelector("button")!;
    expect(computeAccessibleName(el)).toBe("Confirm action");
  });
});

describe("syntheticIdFor", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("generates auto:tag:slug for button with aria-label", () => {
    document.body.innerHTML = `<button aria-label="Gửi tin nhắn">Send</button>`;
    const el = document.querySelector("button")!;
    expect(syntheticIdFor(el)).toBe("auto:button:gui-tin-nhan");
  });

  it("uses 'link' for <a> elements", () => {
    document.body.innerHTML = `<a aria-label="Settings">Cài đặt</a>`;
    const el = document.querySelector("a")!;
    expect(syntheticIdFor(el)).toBe("auto:link:settings");
  });

  it("uses 'input-text' for text inputs", () => {
    document.body.innerHTML = `<input type="text" aria-label="Tìm kiếm" />`;
    const el = document.querySelector("input")!;
    expect(syntheticIdFor(el)).toBe("auto:input-text:tim-kiem");
  });

  it("returns empty when no accessible name", () => {
    document.body.innerHTML = `<button></button>`;
    const el = document.querySelector("button")!;
    expect(syntheticIdFor(el)).toBe("");
  });

  it("appends index when called with non-zero", () => {
    document.body.innerHTML = `<button aria-label="Same name"></button>`;
    const el = document.querySelector("button")!;
    expect(syntheticIdFor(el, 0)).toBe("auto:button:same-name");
    expect(syntheticIdFor(el, 1)).toBe("auto:button:same-name-1");
    expect(syntheticIdFor(el, 5)).toBe("auto:button:same-name-5");
  });

  it("strips diacritics consistently", () => {
    document.body.innerHTML = `<button aria-label="Đính kèm file"></button>`;
    const el = document.querySelector("button")!;
    expect(syntheticIdFor(el)).toBe("auto:button:dinh-kem-file");
  });

  it("handles role override (div with role=button)", () => {
    document.body.innerHTML = `<div role="button" aria-label="Custom button"></div>`;
    const el = document.querySelector("div")!;
    expect(syntheticIdFor(el)).toBe("auto:button:custom-button");
  });
});

describe("registry — bidirectional lookup", () => {
  beforeEach(() => {
    clearSyntheticRegistry();
    document.body.innerHTML = "";
  });

  it("registerSyntheticId + resolveSyntheticId roundtrip", () => {
    document.body.innerHTML = `<button>Test</button>`;
    const el = document.querySelector("button")!;
    registerSyntheticId("auto:button:test", el);
    expect(resolveSyntheticId("auto:button:test")).toBe(el);
  });

  it("resolveSyntheticId returns null when element removed from DOM", () => {
    document.body.innerHTML = `<button>Removable</button>`;
    const el = document.querySelector("button")!;
    registerSyntheticId("auto:button:removable", el);
    expect(resolveSyntheticId("auto:button:removable")).toBe(el);
    el.remove();
    expect(resolveSyntheticId("auto:button:removable")).toBeNull();
  });

  it("resolveSyntheticId returns null for unregistered IDs", () => {
    expect(resolveSyntheticId("auto:button:nonexistent")).toBeNull();
  });

  it("clearSyntheticRegistry drops all entries", () => {
    document.body.innerHTML = `<button>A</button><button>B</button>`;
    const els = document.querySelectorAll("button");
    registerSyntheticId("auto:button:a", els[0]);
    registerSyntheticId("auto:button:b", els[1]);
    clearSyntheticRegistry();
    expect(resolveSyntheticId("auto:button:a")).toBeNull();
    expect(resolveSyntheticId("auto:button:b")).toBeNull();
  });

  it("registerSyntheticId overwrites prior entry for same ID", () => {
    document.body.innerHTML = `<button>A</button><button>B</button>`;
    const els = document.querySelectorAll("button");
    registerSyntheticId("auto:button:test", els[0]);
    registerSyntheticId("auto:button:test", els[1]);
    expect(resolveSyntheticId("auto:button:test")).toBe(els[1]);
  });
});
