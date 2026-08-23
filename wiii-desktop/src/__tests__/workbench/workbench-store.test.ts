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
  hasManagedAccountState,
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

  it("does not mistake empty persisted auth metadata for an account", () => {
    expect(hasManagedAccountState(null)).toBe(false);
    expect(hasManagedAccountState({})).toBe(false);
    expect(hasManagedAccountState({ user: null })).toBe(false);
    expect(hasManagedAccountState({ user: { id: "existing" } })).toBe(true);
    expect(hasManagedAccountState({ authMode: "oauth" })).toBe(false);
    expect(hasManagedAccountState({ authMode: "legacy" })).toBe(true);
  });

  it("returns stale managed desktop preferences to local without an account", () => {
    expect(resolveInitialWorkbenchSurface(desktop, "managed", null, false)).toBe("local");
    expect(resolveInitialWorkbenchSurface(desktop, null, "wiii", false)).toBe("local");
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

  it("boots local when the persisted auth file is empty", async () => {
    storage.set("wiii-workbench.json:surface", "managed");
    storage.set("neko-chill-mode.json:mode", "wiii");
    storage.set("auth_state:data", {});

    await useWorkbenchStore.getState().load(desktop);
    expect(useWorkbenchStore.getState().surface).toBe("local");

    await useWorkbenchStore.getState().setSurface("managed", desktop);
    expect(useWorkbenchStore.getState().surface).toBe("managed");
  });

  it("refuses a local surface on hosted web", async () => {
    await useWorkbenchStore.getState().setSurface("local", web);
    expect(useWorkbenchStore.getState().surface).toBe("managed");
  });
});
