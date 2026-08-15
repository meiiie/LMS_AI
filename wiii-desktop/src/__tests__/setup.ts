/**
 * Global Vitest setup — runs before each test file.
 * Resets Zustand stores to prevent state leakage between test files
 * when running the full suite concurrently.
 */
import { afterEach, beforeEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

// Layout primitives use ResizeObserver in browsers/WebView. jsdom does not
// implement it, so provide the minimal observer lifecycle used by the panels.
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as typeof ResizeObserver;
}

afterEach(() => {
  // Force DOM cleanup after every test — prevents rendered components from
  // one test leaking into the next when all files run in the same fork.
  cleanup();
});

beforeEach(() => {
  // Clear all vi mocks/spies between tests
  vi.clearAllMocks();
});
