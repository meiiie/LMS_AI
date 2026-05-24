import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { InlineVisualFrame } from "@/components/common/InlineVisualFrame";

const originalCreateObjectUrl = URL.createObjectURL;
const originalRevokeObjectUrl = URL.revokeObjectURL;

describe("InlineVisualFrame rendering contract", () => {
  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => "blob:wiii-visual-frame");
    URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    URL.createObjectURL = originalCreateObjectUrl;
    URL.revokeObjectURL = originalRevokeObjectUrl;
  });

  it("renders Code Studio viewport previews as full-height sandbox frames", async () => {
    render(
      <InlineVisualFrame
        html="<main style='height:1400px'>Tall app</main>"
        title="Tall app"
        frameKind="app"
        sizingMode="viewport"
        shellVariant="immersive"
        className="h-full"
      />,
    );

    const iframe = await screen.findByTitle("Tall app");
    await waitFor(() => expect(iframe.getAttribute("src")).toBe("blob:wiii-visual-frame"));

    expect(iframe.parentElement?.getAttribute("data-inline-visual-sizing")).toBe("viewport");
    expect(iframe.parentElement?.getAttribute("data-inline-visual-ready")).toBe("false");
    expect(iframe.parentElement?.getAttribute("aria-busy")).toBe("true");
    expect(iframe.parentElement?.style.height).toBe("100%");
    expect(iframe.parentElement?.style.minHeight).toBe("0px");
    expect((iframe as HTMLIFrameElement).style.height).toBe("100%");
    expect((iframe as HTMLIFrameElement).style.minHeight).toBe("0px");
  });

  it("syncs host visual state when a sandbox frame finishes loading", async () => {
    render(
      <InlineVisualFrame
        html="<main>Bridge app</main>"
        title="Bridge app"
        sessionId="vs_bridge"
        frameKind="app"
        sizingMode="viewport"
        shellVariant="immersive"
        runtimeManifest={{ ui_runtime: "iframe", storage: true }}
      />,
    );

    const iframe = await screen.findByTitle("Bridge app");
    const postMessage = vi.fn();
    Object.defineProperty(iframe, "contentWindow", {
      configurable: true,
      value: { postMessage },
    });

    fireEvent.load(iframe);

    expect(postMessage).toHaveBeenCalledWith(
      {
        type: "wiii-visual-sync",
        payload: {
          sessionId: "vs_bridge",
          frameKind: "app",
          shellVariant: "immersive",
          sizingMode: "viewport",
          runtimeManifest: { ui_runtime: "iframe", storage: true },
        },
      },
      "*",
    );
    expect(iframe.parentElement?.getAttribute("data-inline-visual-ready")).toBe("true");
  });

  it("keeps normal inline app visuals content-sized", async () => {
    render(
      <InlineVisualFrame
        html="<main>Inline app</main>"
        title="Inline app"
        frameKind="app"
        shellVariant="immersive"
      />,
    );

    const iframe = await screen.findByTitle("Inline app");

    expect(iframe.parentElement?.getAttribute("data-inline-visual-sizing")).toBe("content");
    expect((iframe as HTMLIFrameElement).style.height).toBe("520px");
    expect((iframe as HTMLIFrameElement).style.minHeight).toBe("360px");
  });

  it("uses Vietnamese copy for frame creation errors", async () => {
    URL.createObjectURL = vi.fn(() => {
      throw new Error("blob failed");
    });

    render(<InlineVisualFrame html="<main>Broken</main>" title="Broken" />);

    expect(await screen.findByText("Lỗi frame: blob failed")).toBeTruthy();
  });
});
