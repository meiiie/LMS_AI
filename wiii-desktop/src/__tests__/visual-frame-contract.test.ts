import { describe, expect, it } from "vitest";
import {
  buildVisualFrameHostSyncMessage,
  clampVisualFrameContentHeight,
  getVisualFrameHeightProfile,
  parseVisualFrameBridgeMessage,
  resolveVisualFrameCssHeight,
} from "@/lib/visual-frame-contract";

describe("visual frame contract", () => {
  it("keeps inline app frames content-sized by default", () => {
    const profile = getVisualFrameHeightProfile("app", "content");

    expect(profile).toMatchObject({
      initialHeight: 520,
      minHeight: 360,
      maxHeight: 1120,
      sizingMode: "content",
    });
    expect(clampVisualFrameContentHeight(1400, profile)).toBe(1120);
    expect(resolveVisualFrameCssHeight(720, profile)).toBe("720px");
  });

  it("uses viewport sizing for Code Studio panel previews", () => {
    const profile = getVisualFrameHeightProfile("app", "viewport");

    expect(profile).toMatchObject({
      initialHeight: 520,
      minHeight: 0,
      maxHeight: 1120,
      sizingMode: "viewport",
    });
    expect(clampVisualFrameContentHeight(1400, profile)).toBeNull();
    expect(resolveVisualFrameCssHeight(720, profile)).toBe("100%");
  });

  it("parses iframe bridge messages into typed host events", () => {
    expect(parseVisualFrameBridgeMessage({ type: "__edit_mode_available" })).toEqual({
      kind: "tweaks_available",
    });
    expect(parseVisualFrameBridgeMessage({
      type: "wiii-frame-resize",
      payload: { height: 640, sessionId: "vs_1" },
    })).toEqual({ kind: "resize", height: 640, sessionId: "vs_1" });
    expect(parseVisualFrameBridgeMessage({
      type: "wiii-frame-result",
      payload: { summary: "Hoàn thành", sessionId: "vs_1" },
    })).toEqual({
      kind: "bridge",
      bridgeType: "result",
      detail: {
        bridgeType: "result",
        summary: "Hoàn thành",
        sessionId: "vs_1",
      },
    });
    expect(parseVisualFrameBridgeMessage({
      type: "wiii-frame-resize",
      payload: { height: "640" },
    })).toBeNull();
  });

  it("builds a typed host sync message for app frames", () => {
    expect(buildVisualFrameHostSyncMessage({
      sessionId: "vs_1",
      frameKind: "app",
      shellVariant: "immersive",
      sizingMode: "viewport",
      runtimeManifest: { storage: "ephemeral" },
    })).toEqual({
      type: "wiii-visual-sync",
      payload: {
        sessionId: "vs_1",
        frameKind: "app",
        shellVariant: "immersive",
        sizingMode: "viewport",
        runtimeManifest: { storage: "ephemeral" },
      },
    });
  });
});
