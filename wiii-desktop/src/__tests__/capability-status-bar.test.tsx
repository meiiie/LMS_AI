import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { CapabilityStatusBar } from "@/components/chat/CapabilityStatusBar";
import { useConnectionStore } from "@/stores/connection-store";
import { useHostContextStore } from "@/stores/host-context-store";

describe("CapabilityStatusBar", () => {
  beforeEach(() => {
    useHostContextStore.getState().clear();
    useConnectionStore.setState({
      status: "connected",
      serverVersion: null,
      lastCheckedAt: null,
      errorMessage: null,
      pollIntervalId: null,
    });
  });

  it("renders connection chips without raw capability payloads", () => {
    useHostContextStore.getState().setCapabilities({
      host_type: "lms",
      host_name: "Maritime LMS",
      resources: ["current-page"],
      tools: [
        {
          name: "authoring.preview_lesson_patch",
          description: "Preview lesson",
        },
        {
          name: "authoring.apply_lesson_patch",
          description: "Apply lesson",
        },
      ],
    });

    render(<CapabilityStatusBar />);

    expect(screen.getByTestId("capability-status-bar")).toBeTruthy();
    expect(screen.getByText("Máy chủ")).toBeTruthy();
    expect(screen.getByText("Đã kết nối")).toBeTruthy();
    expect(screen.getByText("LMS")).toBeTruthy();
    expect(screen.getByText("Maritime LMS")).toBeTruthy();
    expect(screen.getByText("Preview + Apply")).toBeTruthy();
    expect(screen.queryByText("authoring.preview_lesson_patch")).toBeNull();
  });

  it("shows disconnected server and missing host action bridge", () => {
    useConnectionStore.setState({ status: "disconnected" });

    render(<CapabilityStatusBar />);

    expect(screen.getByText("Mất kết nối")).toBeTruthy();
    expect(screen.getByTestId("capability-status-host_actions").textContent).toContain(
      "Chưa nối",
    );
  });
});
