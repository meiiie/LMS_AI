/**
 * Tests for the PostMessage bridge — protocol validation, origin filtering,
 * action dispatch, and reply targeting.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  _testing,
  createBridge,
  describeTarget,
  handleClick,
  handleCursorMove,
  handleHighlight,
  handleNavigate,
  handleScrollTo,
  handleShowTour,
  resolveSelector,
  type BridgeHandle,
} from "../bridge";
import { destroy } from "../index";
import { clearPointyDomRefreshHook, setPointyDomRefreshHook } from "../dom-refresh";

const liveBridges: BridgeHandle[] = [];

function makeBridge(...args: Parameters<typeof createBridge>): BridgeHandle {
  const h = createBridge(...args);
  liveBridges.push(h);
  return h;
}

afterEach(() => {
  while (liveBridges.length) {
    liveBridges.pop()?.dispose();
  }
  destroy();
  clearPointyDomRefreshHook();
  document.body.innerHTML = "";
});

describe("isPointyRequest", () => {
  it("accepts a well-formed request", () => {
    expect(
      _testing.isPointyRequest({
        type: "wiii:action-request",
        id: "abc",
        action: "ui.highlight",
        params: { selector: "#x" },
      }),
    ).toBe(true);
  });

  it("rejects messages of other types", () => {
    expect(
      _testing.isPointyRequest({
        type: "wiii:capabilities",
        id: "abc",
        action: "ui.highlight",
        params: {},
      }),
    ).toBe(false);
    expect(_testing.isPointyRequest("not-an-object")).toBe(false);
    expect(_testing.isPointyRequest(null)).toBe(false);
  });
});

describe("isSafeUrl", () => {
  it("accepts public https URLs", () => {
    expect(_testing.isSafeUrl("https://holilihu.online/courses/1")).toBe(true);
  });
  it("rejects loopback and internal hosts", () => {
    expect(_testing.isSafeUrl("http://localhost:8000/")).toBe(false);
    expect(_testing.isSafeUrl("http://127.0.0.1/")).toBe(false);
    expect(_testing.isSafeUrl("https://foo.local/")).toBe(false);
  });
  it("rejects non-http schemes", () => {
    expect(_testing.isSafeUrl("file:///etc/passwd")).toBe(false);
    expect(_testing.isSafeUrl("javascript:alert(1)")).toBe(false);
  });
});

describe("resolveSelector", () => {
  it("returns null for empty or non-string input", () => {
    expect(resolveSelector("")).toBeNull();
    expect(resolveSelector("   ")).toBeNull();
    expect(resolveSelector(undefined)).toBeNull();
    expect(resolveSelector(123)).toBeNull();
  });
  it("returns null for invalid CSS", () => {
    expect(resolveSelector(">>>not-valid")).toBeNull();
  });
  it("resolves data-wiii-id and id selectors", () => {
    document.body.innerHTML = `<button id="b1" data-wiii-id="login-btn">Login</button>`;
    expect(resolveSelector("#b1")?.tagName).toBe("BUTTON");
    expect(resolveSelector('[data-wiii-id="login-btn"]')?.tagName).toBe("BUTTON");
    expect(resolveSelector("login-btn")?.tagName).toBe("BUTTON");
  });
  it("prefers data-wiii-id over matching custom-element tag names", () => {
    document.body.innerHTML = `
      <profile-link id="wrong-target"></profile-link>
      <button data-wiii-id="profile-link">Profile</button>
    `;
    expect(resolveSelector("profile-link")?.tagName).toBe("BUTTON");
  });
  it("chooses the best visible duplicate data-wiii-id candidate", () => {
    document.body.innerHTML = `
      <button data-wiii-id="chat-send-button" style="display:none">Old hidden</button>
      <span data-wiii-id="chat-send-button" data-wiii-role="button" aria-label="Gửi tin nhắn"></span>
    `;
    const target = resolveSelector("chat-send-button");
    expect(target?.tagName).toBe("SPAN");
    expect(target?.getAttribute("aria-label")).toBe("Gửi tin nhắn");
  });

  it("refreshes DOM inventory before resolving a selector", () => {
    let refreshCalls = 0;
    setPointyDomRefreshHook(() => {
      refreshCalls += 1;
      document.body.innerHTML = `<button data-wiii-id="late-target">Late target</button>`;
    });

    const target = resolveSelector("late-target");

    expect(refreshCalls).toBe(1);
    expect(target?.tagName).toBe("BUTTON");
  });
});

describe("describeTarget", () => {
  it("prefers data-wiii-id, then id, then aria, then text", () => {
    document.body.innerHTML = `
      <button id="ok" data-wiii-id="submit">Gửi</button>
      <button id="x" aria-label="Đóng"></button>
      <button id="y">Mở</button>
      <button>Khám phá</button>
    `;
    expect(describeTarget(document.querySelector("[data-wiii-id]")!)).toContain("#submit");
    expect(describeTarget(document.querySelector('[aria-label="Đóng"]')!)).toContain('"Đóng"');
    expect(describeTarget(document.querySelector("#y")!)).toContain("#y");
    // Element with neither id nor aria falls back to its text content.
    const buttons = document.querySelectorAll("button");
    expect(describeTarget(buttons[buttons.length - 1])).toContain('"Khám phá"');
  });
});

describe("handleHighlight", () => {
  it("returns success when selector resolves", async () => {
    document.body.innerHTML = `<button data-wiii-id="login">Login</button>`;
    const result = await handleHighlight({ selector: '[data-wiii-id="login"]' });
    expect(result.success).toBe(true);
    expect(result.data?.summary).toContain("login");
  });
  it("returns failure when selector missing", async () => {
    const result = await handleHighlight({ selector: "#nope" });
    expect(result.success).toBe(false);
    expect(result.error).toContain("selector_not_found");
  });
  it("returns failure when selector resolves to a hidden target", async () => {
    document.body.innerHTML = `<button id="ghost" style="display:none">Ghost</button>`;
    const result = await handleHighlight({ selector: "#ghost" });
    expect(result.success).toBe(false);
    expect(result.error).toContain("target_not_visible");
  });
});

describe("handleCursorMove", () => {
  it("moves cursor to a selector without spotlighting or clicking", async () => {
    const browseButton = document.createElement("button");
    browseButton.dataset.wiiiId = "browse";
    browseButton.textContent = "Browse";
    document.body.appendChild(browseButton);
    const result = await handleCursorMove({ selector: "browse", label: "Wiii" });
    expect(result.success).toBe(true);
    expect(result.data?.summary).toContain("browse");
    expect(document.querySelector("#wiii-pointy-cursor")).not.toBeNull();
    expect(document.querySelector("#wiii-pointy-overlay")).toBeNull();
  });

  it("moves cursor to normalized viewport coordinates", async () => {
    const originalAnimate = Element.prototype.animate;
    Object.defineProperty(Element.prototype, "animate", {
      configurable: true,
      value: undefined,
    });
    try {
      const result = await handleCursorMove({
        x: 0.5,
        y: 0.5,
        coordinate_space: "normalized",
        label: "Wiii",
      });
      expect(result.success).toBe(true);
      const cursor = document.querySelector("#wiii-pointy-cursor") as SVGSVGElement;
      expect(cursor).not.toBeNull();
      const expectedX = window.innerWidth * 0.5 - 5;
      const expectedY = window.innerHeight * 0.5 - 4;
      expect(cursor.style.transform).toBe(`translate(${expectedX}px, ${expectedY}px) scale(1)`);
    } finally {
      Object.defineProperty(Element.prototype, "animate", {
        configurable: true,
        value: originalAnimate,
      });
    }
  });

  it("fails closed when no selector or coordinates are provided", async () => {
    const result = await handleCursorMove({});
    expect(result.success).toBe(false);
    expect(result.error).toBe("missing_cursor_target");
  });

  it("fails closed for non-finite coordinates", async () => {
    const result = await handleCursorMove({ x: Number.NaN, y: Infinity });
    expect(result.success).toBe(false);
    expect(result.error).toBe("missing_cursor_target");
  });
});

describe("handleScrollTo", () => {
  it("succeeds for present target", async () => {
    document.body.innerHTML = `<section id="ch1">Chapter 1</section>`;
    const result = await handleScrollTo({ selector: "#ch1" });
    expect(result.success).toBe(true);
  });
});

describe("handleShowTour", () => {
  it("uses the same data-wiii-id resolver as highlight and click", async () => {
    document.body.innerHTML = `
      <button data-wiii-id="continue-lesson">Continue</button>
      <button data-wiii-id="quiz-card">Quiz</button>
    `;

    const result = await handleShowTour({
      steps: [
        { selector: "continue-lesson", message: "Step 1", duration_ms: 1 },
        { selector: "quiz-card", message: "Step 2", duration_ms: 1 },
      ],
    });

    expect(result.success).toBe(true);
    expect(result.data?.completed_steps).toBe(2);
    expect(result.data?.total_steps).toBe(2);
    expect(result.data?.cancelled).toBe(false);
    expect(result.data?.missing_selectors).toEqual([]);
  });
});

describe("handleClick", () => {
  it("clicks only targets explicitly marked safe", async () => {
    document.body.innerHTML = `<button data-wiii-id="browse-courses" data-wiii-click-safe="true" data-wiii-click-kind="navigation">Browse</button>`;
    const target = document.querySelector("button")!;
    const clickSpy = vi.spyOn(target, "click");
    const result = await handleClick({ selector: '[data-wiii-id="browse-courses"]' });

    expect(result.success).toBe(true);
    expect(result.data?.clicked).toBe(true);
    expect(result.data?.click_kind).toBe("navigation");
    expect(clickSpy).toHaveBeenCalled();
  });

  it("fails closed for unsafe targets", async () => {
    document.body.innerHTML = `<button data-wiii-id="submit-quiz">Submit</button>`;
    const target = document.querySelector("button")!;
    const clickSpy = vi.spyOn(target, "click");
    const result = await handleClick({ selector: '[data-wiii-id="submit-quiz"]' });

    expect(result.success).toBe(false);
    expect(result.error).toContain("unsafe_click_target");
    expect(clickSpy).not.toHaveBeenCalled();
  });
});

describe("handleNavigate", () => {
  it("rejects when no route or url provided", async () => {
    const result = await handleNavigate({}, { iframeOrigin: "https://x" });
    expect(result.success).toBe(false);
    expect(result.error).toBe("missing_target");
  });
  it("invokes onNavigate callback when route is given", async () => {
    const onNavigate = vi.fn().mockResolvedValue(undefined);
    const result = await handleNavigate(
      { route: "/courses/123" },
      { iframeOrigin: "https://x", onNavigate },
    );
    expect(onNavigate).toHaveBeenCalledWith("/courses/123");
    expect(result.success).toBe(true);
  });
  it("rejects unsafe absolute URLs", async () => {
    const result = await handleNavigate(
      { url: "http://localhost/internal" },
      { iframeOrigin: "https://x" },
    );
    expect(result.success).toBe(false);
    expect(result.error).toBe("unsafe_url");
  });
});

describe("isSafeUrl edge cases", () => {
  it("rejects malformed URLs", () => {
    expect(_testing.isSafeUrl("https://")).toBe(false);
    expect(_testing.isSafeUrl("not a url at all")).toBe(false);
  });
  it("accepts the canonical LMS domain", () => {
    expect(_testing.isSafeUrl("https://holilihu.online")).toBe(true);
    expect(_testing.isSafeUrl("https://wiii.holilihu.online/embed/")).toBe(true);
  });
  it("rejects 0.0.0.0 explicitly", () => {
    expect(_testing.isSafeUrl("http://0.0.0.0:8000")).toBe(false);
  });
});

describe("handleHighlight edge cases", () => {
  it("returns missing-selector when params.selector is empty string", async () => {
    const result = await handleHighlight({ selector: "" });
    expect(result.success).toBe(false);
    expect(result.error).toContain("selector_not_found");
  });
  it("does not throw when target lacks scrollIntoView", async () => {
    document.body.innerHTML = `<div id="x"></div>`;
    const target = document.getElementById("x") as HTMLElement & { scrollIntoView?: unknown };
    // Force-remove scrollIntoView to simulate exotic elements.
    target.scrollIntoView = undefined as unknown as () => void;
    const result = await handleHighlight({ selector: "#x", message: "ok", duration_ms: 800 });
    expect(result.success).toBe(true);
  });
});

describe("handleNavigate edge cases", () => {
  it("succeeds for route fallback when no onNavigate callback is provided", async () => {
    // jsdom forbids redefining window.location.assign — we only assert the
    // return shape. Real browsers exercise window.location.assign in QA.
    const result = await handleNavigate({ route: "/courses/42" }, { iframeOrigin: "https://x" });
    expect(result.success).toBe(true);
    expect(result.data?.summary).toContain("/courses/42");
  });
  it("passes through when onNavigate callback throws", async () => {
    const onNavigate = vi.fn().mockRejectedValue(new Error("router_error"));
    const result = await handleNavigate(
      { route: "/courses/42" },
      { iframeOrigin: "https://x", onNavigate },
    );
    expect(result.success).toBe(false);
    expect(result.error).toContain("navigate_failed");
    expect(result.error).toContain("router_error");
  });
});

describe("createBridge", () => {
  it("ignores messages from other origins", async () => {
    const onNavigate = vi.fn();
    makeBridge({ iframeOrigin: "https://wiii.example", onNavigate });
    const evil = new MessageEvent("message", {
      data: {
        type: "wiii:action-request",
        id: "1",
        action: "ui.navigate",
        params: { route: "/x" },
      },
      origin: "https://attacker.example",
    });
    window.dispatchEvent(evil);
    await Promise.resolve();
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it("dispatches and replies with matching id when origin matches", async () => {
    document.body.innerHTML = `<button data-wiii-id="login"></button>`;
    const replies: unknown[] = [];
    const fakeSource = {
      postMessage: (msg: unknown) => replies.push(msg),
    } as unknown as Window;
    makeBridge({ iframeOrigin: "https://wiii.example" });
    const event = new MessageEvent("message", {
      data: {
        type: "wiii:action-request",
        id: "req-42",
        action: "ui.highlight",
        params: { selector: '[data-wiii-id="login"]', message: "Đây" },
      },
      origin: "https://wiii.example",
    });
    Object.defineProperty(event, "source", { value: fakeSource });
    window.dispatchEvent(event);
    await new Promise((r) => setTimeout(r, 10));
    expect(replies).toHaveLength(1);
    const reply = replies[0] as { type: string; id: string; result: { success: boolean } };
    expect(reply.type).toBe("wiii:action-response");
    expect(reply.id).toBe("req-42");
    expect(reply.result.success).toBe(true);
  });

  it("replies with failure for unsupported action", async () => {
    const replies: unknown[] = [];
    const fakeSource = {
      postMessage: (msg: unknown) => replies.push(msg),
    } as unknown as Window;
    makeBridge({ iframeOrigin: "https://wiii.example" });
    const event = new MessageEvent("message", {
      data: {
        type: "wiii:action-request",
        id: "req-99",
        action: "ui.delete_universe",
        params: {},
      },
      origin: "https://wiii.example",
    });
    Object.defineProperty(event, "source", { value: fakeSource });
    window.dispatchEvent(event);
    await new Promise((r) => setTimeout(r, 5));
    const reply = replies[0] as { result: { success: boolean; error?: string } };
    expect(reply.result.success).toBe(false);
    expect(reply.result.error).toContain("unsupported_action");
  });

  it("ignores requests whose data is not a pointy request", async () => {
    const onNavigate = vi.fn();
    makeBridge({ iframeOrigin: "https://wiii.example", onNavigate });
    const noise = new MessageEvent("message", {
      data: { type: "some-other-event", payload: { foo: 1 } },
      origin: "https://wiii.example",
    });
    window.dispatchEvent(noise);
    await Promise.resolve();
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it("logs and short-circuits when event.source is missing", async () => {
    const logSpy = vi.fn();
    document.body.innerHTML = `<button data-wiii-id="login"></button>`;
    makeBridge({ iframeOrigin: "https://wiii.example", log: logSpy });
    const event = new MessageEvent("message", {
      data: {
        type: "wiii:action-request",
        id: "req-no-source",
        action: "ui.highlight",
        params: { selector: '[data-wiii-id="login"]' },
      },
      origin: "https://wiii.example",
    });
    // No source set on the event — bridge must not throw.
    window.dispatchEvent(event);
    await new Promise((r) => setTimeout(r, 5));
    expect(logSpy).toHaveBeenCalledWith("warn", "no_event_source");
  });
});
