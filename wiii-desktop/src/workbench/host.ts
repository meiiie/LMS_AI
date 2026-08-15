export type WorkbenchHostKind = "desktop" | "web";

export interface WorkbenchHostCapabilities {
  localProcess: boolean;
  localWorkspace: boolean;
  nativeWindow: boolean;
  tray: boolean;
  secureSecretStore: boolean;
  remoteRuntime: boolean;
}
export type WorkbenchHostCapability = keyof WorkbenchHostCapabilities;

export interface WorkbenchHost {
  kind: WorkbenchHostKind;
  capabilities: WorkbenchHostCapabilities;
}

/** Minimal evidence accepted by the pure resolver. Missing evidence fails closed. */
export interface WorkbenchHostProbe {
  tauri?: boolean;
}

const WEB_CAPABILITIES: WorkbenchHostCapabilities = {
  localProcess: false,
  localWorkspace: false,
  nativeWindow: false,
  tray: false,
  secureSecretStore: false,
  remoteRuntime: true,
};

const DESKTOP_CAPABILITIES: WorkbenchHostCapabilities = {
  localProcess: true,
  localWorkspace: true,
  nativeWindow: true,
  tray: true,
  // Wiii currently uses plugin-store, not an OS keychain contract. Do not
  // advertise secure provider-secret ownership until a real keychain exists.
  secureSecretStore: false,
  remoteRuntime: true,
};

export function resolveWorkbenchHost(probe: WorkbenchHostProbe): WorkbenchHost {
  if (probe.tauri === true) {
    return { kind: "desktop", capabilities: { ...DESKTOP_CAPABILITIES } };
  }
  return { kind: "web", capabilities: { ...WEB_CAPABILITIES } };
}

export function detectWorkbenchHost(): WorkbenchHost {
  const tauri =
    typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
  return resolveWorkbenchHost({ tauri });
}
