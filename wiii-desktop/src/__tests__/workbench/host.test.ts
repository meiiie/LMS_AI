import { describe, expect, it } from "vitest";
import {
  resolveWorkbenchHost,
  type WorkbenchHostProbe,
} from "@/workbench/host";

describe("Workbench host contract", () => {
  it("grants native capabilities only from explicit Tauri evidence", () => {
    const probe: WorkbenchHostProbe = { tauri: true };

    expect(resolveWorkbenchHost(probe)).toEqual({
      kind: "desktop",
      capabilities: {
        localProcess: true,
        localWorkspace: true,
        nativeWindow: true,
        tray: true,
        secureSecretStore: false,
        remoteRuntime: true,
      },
    });
  });

  it("fails closed to a hosted web capability set", () => {
    expect(resolveWorkbenchHost({ tauri: false })).toEqual({
      kind: "web",
      capabilities: {
        localProcess: false,
        localWorkspace: false,
        nativeWindow: false,
        tray: false,
        secureSecretStore: false,
        remoteRuntime: true,
      },
    });
  });

  it("does not grant native authority when probe evidence is absent", () => {
    expect(resolveWorkbenchHost({}).kind).toBe("web");
    expect(resolveWorkbenchHost({}).capabilities.localProcess).toBe(false);
  });
});
