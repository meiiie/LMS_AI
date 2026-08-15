import { beforeEach, describe, expect, it, vi } from "vitest";
import type { WorkbenchHost } from "@/workbench/host";

const storage = new Map<string, unknown>();

vi.mock("@/lib/storage", () => ({
  loadStore: vi.fn(async (store: string, key: string, fallback: unknown) =>
    storage.has(`${store}:${key}`) ? storage.get(`${store}:${key}`) : fallback,
  ),
  saveStore: vi.fn(async (store: string, key: string, value: unknown) => {
    storage.set(`${store}:${key}`, value);
  }),
}));

import {
  resolveInitialWorkbenchSurface,
  useWorkbenchStore,
} from "@/workbench/workbench-store";

const desktop: WorkbenchHost = {
  kind: "desktop",
  capabilities: {
    localProcess: true,
    localWorkspace: true,
    nativeWindow: true,
    tray: true,
    secureSecretStore: false,
    remoteRuntime: true,
  },
};

const web: WorkbenchHost = {
  kind: "web",
  capabilities: {
    localProcess: false,
    localWorkspace: false,
    nativeWindow: false,
    tray: false,
    secureSecretStore: false,
    remoteRuntime: true,
  },
};

describe("Workbench surface migration", () => {
  beforeEach(() => {
    storage.clear();
    useWorkbenchStore.setState({ surface: "local", isLoaded: false });
  });

  it("starts a fresh desktop install in the local workbench", () => {
    expect(resolveInitialWorkbenchSurface(desktop, null, null, false)).toBe("local");
  });

  it("preserves an existing managed-mode intent without deleting auth", () => {
    expect(resolveInitialWorkbenchSurface(desktop, null, "wiii", true)).toBe("managed");
    expect(resolveInitialWorkbenchSurface(desktop, null, null, true)).toBe("managed");
  });

  it("forces hosted web onto a remote-capable surface", () => {
    expect(resolveInitialWorkbenchSurface(web, "local", "neko-chill", false)).toBe("managed");
  });

  it("migrates legacy mode and persists only the new surface preference", async () => {
    storage.set("neko-chill-mode.json:mode", "wiii");
    storage.set("auth_state:data", { user: { id: "existing" } });

    await useWorkbenchStore.getState().load(desktop);
    expect(useWorkbenchStore.getState().surface).toBe("managed");

    await useWorkbenchStore.getState().setSurface("local", desktop);
    expect(storage.get("wiii-workbench.json:surface")).toBe("local");
    expect(storage.get("neko-chill-mode.json:mode")).toBe("wiii");
    expect(storage.get("auth_state:data")).toEqual({ user: { id: "existing" } });
  });

  it("refuses a local surface on hosted web", async () => {
    await useWorkbenchStore.getState().setSurface("local", web);
    expect(useWorkbenchStore.getState().surface).toBe("managed");
  });
});
