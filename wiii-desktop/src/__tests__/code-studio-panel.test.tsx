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

    fireEvent.click(screen.getByRole("button", { name: "Xem trước" }));

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

  it("keeps the overlay shell mobile-safe before the sm breakpoint", async () => {
    seedCompleteSession("code");

    const { container } = render(<CodeStudioPanel />);

    const shell = container.querySelector(".code-studio-panel");
    expect(shell).toBeTruthy();
    const classTokens = new Set((shell?.getAttribute("class") || "").split(/\s+/));

    expect(classTokens.has("inset-x-0")).toBe(true);
    expect(classTokens.has("w-full")).toBe(true);
    expect(classTokens.has("max-w-full")).toBe(true);
    expect(classTokens.has("min-w-0")).toBe(true);
    expect(classTokens.has("min-w-[420px]")).toBe(false);
    expect(classTokens.has("sm:min-w-[420px]")).toBe(true);
  });

  it("uses Vietnamese-first labels in the Code Studio surface", async () => {
    seedCompleteSession("code");

    render(<CodeStudioPanel />);

    expect(await screen.findByRole("button", { name: "Mã" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Xem trước" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Đóng Code Studio" })).toBeTruthy();
    expect(screen.getByText("Đã xong")).toBeTruthy();
    expect(screen.getByText(/1 dòng · \d+ byte/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Sao chép" })).toBeTruthy();
  });
});
