export type VisualFrameKind = "legacy" | "inline_html" | "app";
export type VisualFrameSizingMode = "content" | "viewport";

export interface VisualFrameHostSyncPayload {
  sessionId: string;
  frameKind: VisualFrameKind;
  shellVariant: string;
  sizingMode: VisualFrameSizingMode;
  runtimeManifest: unknown | null;
}

export interface VisualFrameHostSyncMessage {
  type: "wiii-visual-sync";
  payload: VisualFrameHostSyncPayload;
}

export interface VisualFrameHeightProfile {
  initialHeight: number;
  minHeight: number;
  maxHeight: number;
  sizingMode: VisualFrameSizingMode;
}

export type VisualFrameBridgeMessage =
  | { kind: "tweaks_available" }
  | { kind: "tweaks_persist"; edits: Record<string, unknown> }
  | { kind: "resize"; height: number; sessionId?: string }
  | { kind: "ready" }
  | {
      kind: "bridge";
      bridgeType: "telemetry" | "interaction" | "control" | "focus" | "result";
      detail: Record<string, unknown>;
    };

const CONTENT_FRAME_HEIGHT: Record<VisualFrameKind, Omit<VisualFrameHeightProfile, "sizingMode">> = {
  legacy: { initialHeight: 320, minHeight: 120, maxHeight: 880 },
  inline_html: { initialHeight: 320, minHeight: 120, maxHeight: 880 },
  app: { initialHeight: 520, minHeight: 360, maxHeight: 1120 },
};

const VIEWPORT_FRAME_HEIGHT: Record<VisualFrameKind, Omit<VisualFrameHeightProfile, "sizingMode">> = {
  legacy: { initialHeight: 320, minHeight: 0, maxHeight: 880 },
  inline_html: { initialHeight: 320, minHeight: 0, maxHeight: 880 },
  app: { initialHeight: 520, minHeight: 0, maxHeight: 1120 },
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function resolveVisualFrameSizingMode(
  _frameKind: VisualFrameKind,
  requested?: VisualFrameSizingMode,
): VisualFrameSizingMode {
  if (requested) return requested;
  return "content";
}

export function getVisualFrameHeightProfile(
  frameKind: VisualFrameKind,
  sizingMode: VisualFrameSizingMode,
): VisualFrameHeightProfile {
  const source =
    sizingMode === "viewport"
      ? VIEWPORT_FRAME_HEIGHT[frameKind]
      : CONTENT_FRAME_HEIGHT[frameKind];
  return { ...source, sizingMode };
}

export function clampVisualFrameContentHeight(
  nextHeight: number,
  profile: VisualFrameHeightProfile,
): number | null {
  if (!Number.isFinite(nextHeight) || nextHeight <= 0) return null;
  if (profile.sizingMode === "viewport") return null;
  return Math.min(Math.max(nextHeight + 10, profile.minHeight), profile.maxHeight);
}

export function resolveVisualFrameCssHeight(
  height: number,
  profile: VisualFrameHeightProfile,
): string {
  if (profile.sizingMode === "viewport") return "100%";
  return `${height}px`;
}

export function buildVisualFrameHostSyncMessage(
  payload: VisualFrameHostSyncPayload,
): VisualFrameHostSyncMessage {
  return {
    type: "wiii-visual-sync",
    payload,
  };
}

export function parseVisualFrameBridgeMessage(
  data: unknown,
): VisualFrameBridgeMessage | null {
  const record = asRecord(data);
  if (!record || typeof record.type !== "string") return null;

  if (record.type === "__edit_mode_available") {
    return { kind: "tweaks_available" };
  }

  if (record.type === "__edit_mode_set_keys") {
    const edits = asRecord(record.edits);
    return edits ? { kind: "tweaks_persist", edits } : null;
  }

  if (record.type === "wiii-frame-resize") {
    const payload = asRecord(record.payload);
    if (!payload) return null;
    const height = payload.height;
    if (typeof height !== "number") return null;
    return {
      kind: "resize",
      height,
      sessionId:
        typeof payload.sessionId === "string" ? payload.sessionId : undefined,
    };
  }

  if (record.type === "wiii-frame-ready") {
    return { kind: "ready" };
  }

  const bridgeType =
    record.type === "wiii-frame-telemetry"
      ? "telemetry"
      : record.type === "wiii-frame-control"
        ? "control"
        : record.type === "wiii-frame-focus"
          ? "focus"
          : record.type === "wiii-frame-result"
            ? "result"
            : record.type === "wiii-frame-interaction"
              ? "interaction"
              : null;

  if (!bridgeType) return null;
  return {
    kind: "bridge",
    bridgeType,
    detail: { bridgeType, ...(asRecord(record.payload) || {}) },
  };
}
