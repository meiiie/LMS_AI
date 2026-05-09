/**
 * Unit tests for theme management utilities.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { initTheme, setTheme, getCurrentTheme } from "@/lib/theme";

// Mock window.matchMedia (not available in jsdom)
function mockMatchMedia(prefersDark = false) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: prefersDark && query === "(prefers-color-scheme: dark)",
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}

function mockLocalStorage() {
  let values: Record<string, string> = {};
  const storage = {
    getItem: vi.fn((key: string) => values[key] ?? null),
    setItem: vi.fn((key: string, value: string) => {
      values[key] = String(value);
    }),
    removeItem: vi.fn((key: string) => {
      delete values[key];
    }),
    clear: vi.fn(() => {
      values = {};
    }),
  };
  Object.defineProperty(window, "localStorage", {
    value: storage,
    configurable: true,
  });
  Object.defineProperty(globalThis, "localStorage", {
    value: storage,
    configurable: true,
  });
  return storage;
}

describe("Theme Utilities", () => {
  beforeEach(() => {
    mockLocalStorage();
    // Mock matchMedia before each test
    mockMatchMedia(false);
    // Clear dark class and localStorage
    document.documentElement.classList.remove("dark");
    localStorage.clear();
  });

  afterEach(() => {
    document.documentElement.classList.remove("dark");
    localStorage.clear();
  });

  it("should initialize with system theme by default", () => {
    const mode = initTheme();
    expect(mode).toBe("system");
  });

  it("should initialize with system theme and resolve to light", () => {
    mockMatchMedia(false);
    const mode = initTheme();
    expect(mode).toBe("system");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("should initialize with system theme and resolve to dark", () => {
    mockMatchMedia(true);
    const mode = initTheme();
    expect(mode).toBe("system");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("should initialize with persisted light theme", () => {
    localStorage.setItem("wiii:theme", "light");
    const mode = initTheme();
    expect(mode).toBe("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("should initialize with persisted dark theme", () => {
    localStorage.setItem("wiii:theme", "dark");
    const mode = initTheme();
    expect(mode).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("should set theme to dark", () => {
    setTheme("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(localStorage.getItem("wiii:theme")).toBe("dark");
  });

  it("should set theme to light", () => {
    // Start with dark
    setTheme("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);

    // Switch to light
    setTheme("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(localStorage.getItem("wiii:theme")).toBe("light");
  });

  it("should get current theme", () => {
    setTheme("dark");
    expect(getCurrentTheme()).toBe("dark");

    setTheme("light");
    expect(getCurrentTheme()).toBe("light");
  });

  it("should persist theme to localStorage", () => {
    setTheme("dark");
    expect(localStorage.getItem("wiii:theme")).toBe("dark");

    setTheme("system");
    expect(localStorage.getItem("wiii:theme")).toBe("system");
  });

  it("should handle invalid stored theme gracefully", () => {
    localStorage.setItem("wiii:theme", "invalid_value");
    const mode = initTheme();
    expect(mode).toBe("system"); // Falls back to system
  });
});
