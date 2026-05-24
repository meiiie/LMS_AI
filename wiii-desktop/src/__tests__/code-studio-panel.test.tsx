import { createElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { CodeStudioPanel } from "@/components/layout/CodeStudioPanel";
import { useCodeStudioStore } from "@/stores/code-studio-store";
import { useUIStore } from "@/stores/ui-store";

const inlineVisualFrameSpy = vi.fn();

vi.mock("motion/react", () => ({
  AnimatePresence: ({ children }: any) => createElement("div", null, children),
  motion: {
    div: ({ children, ...props }: any) => {
      const { initial, animate, exit, transition, ...rest } = props;
      return createElement("div", rest, children);
    },
  },
}));

vi.mock("@/components/common/InlineVisualFrame", () => ({
  InlineVisualFrame: (props: Record<string, unknown>) => {
    inlineVisualFrameSpy(props);
    return createElement("div", { "data-testid": "inline-visual-frame" }, `Preview: ${props.title}`);
  },
}));

if (typeof globalThis.requestAnimationFrame === "undefined") {
  (globalThis as any).requestAnimationFrame = (cb: FrameRequestCallback) =>
    setTimeout(() => cb(0), 16);
}

if (typeof globalThis.cancelAnimationFrame === "undefined") {
  (globalThis as any).cancelAnimationFrame = (id: ReturnType<typeof setTimeout>) =>
    clearTimeout(id);
}

function resetStores() {
  inlineVisualFrameSpy.mockReset();
  useUIStore.setState({
    codeStudioPanelOpen: false,
    artifactPanelOpen: false,
    previewPanelOpen: false,
    sourcesPanelOpen: false,
  });
  useCodeStudioStore.setState({
    activeSessionId: null,
    sessions: {},
  });
}

function seedCompleteSession(requestedView?: "code" | "preview") {
  useUIStore.setState({ codeStudioPanelOpen: true });
  useCodeStudioStore.setState({
    activeSessionId: "vs_1",
    sessions: {
      vs_1: {
        sessionId: "vs_1",
        title: "Pendulum Lab",
        language: "html",
        status: "complete",
        code: "<div>pendulum</div>",
        versions: [
          {
            version: 1,
            code: "<div>pendulum</div>",
            title: "Pendulum Lab",
            timestamp: Date.now(),
          },
        ],
        activeVersion: 1,
        chunkCount: 4,
        totalBytes: 64,
        createdAt: Date.now(),
        metadata: requestedView ? { requestedView } : {},
      },
    },
  });
}

describe("CodeStudioPanel", () => {
  beforeEach(() => {
    resetStores();
  });

  it("auto-switches to preview when a completed session has previewable code", async () => {
    seedCompleteSession();

    render(<CodeStudioPanel />);

    await waitFor(() => {
      expect(screen.getByTestId("inline-visual-frame")).toBeTruthy();
    });

    expect(useCodeStudioStore.getState().sessions["vs_1"].metadata.requestedView).toBe("preview");
    expect(screen.queryByText("<div>pendulum</div>")).toBeNull();
  });

  it("keeps the code tab when the session explicitly requests code view", async () => {
    seedCompleteSession("code");

    render(<CodeStudioPanel />);

    await waitFor(() => {
      expect(screen.getByText("<div>pendulum</div>")).toBeTruthy();
    });

    expect(screen.queryByTestId("inline-visual-frame")).toBeNull();
    expect(useCodeStudioStore.getState().sessions["vs_1"].metadata.requestedView).toBe("code");
  });

  it("persists manual tab switches back into session metadata", async () => {
    seedCompleteSession("code");

    render(<CodeStudioPanel />);

    fireEvent.click(screen.getByRole("button", { name: "Preview" }));

    await waitFor(() => {
      expect(screen.getByTestId("inline-visual-frame")).toBeTruthy();
    });

    expect(useCodeStudioStore.getState().sessions["vs_1"].metadata.requestedView).toBe("preview");
  });

  it("renders Code Studio previews as app frames", async () => {
    seedCompleteSession("preview");

    render(<CodeStudioPanel />);

    await waitFor(() => {
      expect(screen.getByTestId("inline-visual-frame")).toBeTruthy();
    });

    expect(inlineVisualFrameSpy).toHaveBeenLastCalledWith(
      expect.objectContaining({
        frameKind: "app",
        sizingMode: "viewport",
        shellVariant: "immersive",
        hostShellMode: "force",
        className: "w-full h-full",
      }),
    );
  });
});
