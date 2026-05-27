import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { CapabilityStatusBar } from "@/components/chat/CapabilityStatusBar";
import { useChatStore } from "@/stores/chat-store";
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
    useChatStore.setState({
      streamingLifecycleEvents: [],
      lastCompletedLifecycleEvents: [],
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

  it("opens an integration dashboard without raw tool names", () => {
    useConnectionStore.setState({
      serverVersion: "test-version",
      lastCheckedAt: "2026-05-27T12:00:00.000Z",
    });
    useHostContextStore.getState().setCapabilities({
      host_type: "lms",
      host_name: "Maritime LMS",
      connector_id: "maritime-lms-dev",
      resources: ["current-page"],
      surfaces: ["desktop-chat"],
      tools: [
        {
          name: "authoring.preview_lesson_patch",
          description: "Preview lesson",
          requires_confirmation: true,
        },
        {
          name: "authoring.apply_lesson_patch",
          description: "Apply lesson",
          mutates_state: true,
          requires_confirmation: true,
        },
        {
          name: "ui.highlight",
          description: "Highlight target",
        },
      ],
    });

    render(<CapabilityStatusBar />);

    fireEvent.click(screen.getByTestId("capability-dashboard-toggle"));

    expect(screen.getByTestId("capability-dashboard-panel")).toBeTruthy();
    expect(screen.getByText("Dashboard runtime")).toBeTruthy();
    expect(screen.getByTestId("capability-dashboard-section-server")).toBeTruthy();
    expect(screen.getByTestId("capability-dashboard-section-host")).toBeTruthy();
    expect(screen.getByTestId("capability-dashboard-section-lms_authoring")).toBeTruthy();
    expect(screen.getByText("Qua approval_token")).toBeTruthy();
    expect(screen.getByText("Preview trước, apply sau")).toBeTruthy();
    expect(screen.queryByText("authoring.apply_lesson_patch")).toBeNull();
  });

  it("shows the latest lifecycle path in the dashboard", () => {
    useChatStore.setState({
      lastCompletedLifecycleEvents: [
        {
          schema_version: "1",
          event_name: "path.selected",
          phase: "routing",
          status: "selected",
          message: "Selected native turn",
          lane: "native_turn",
          capabilities: {
            host_surface: "desktop_chat",
            observed_tools: ["memory.lookup"],
            suppressed_tools: ["host_action"],
            wiii_connect: {
              version: "wiii_connect_snapshot.v0",
              surface: "desktop_chat",
              connections: [
                {
                  slug: "document_corpus",
                  label: "Document corpus",
                  status: "connected",
                  active: true,
                  agent_ready: true,
                  capabilities: ["document.read"],
                  attachment_count: 1,
                  source_ref_count: 2,
                },
              ],
              path_capabilities: [
                {
                  path: "document_grounded_answer",
                  required_connection_slugs: ["document_corpus"],
                },
              ],
            },
          },
          received_at_ms: 1779825600000,
        },
      ],
    });

    render(<CapabilityStatusBar />);

    fireEvent.click(screen.getByTestId("capability-dashboard-toggle"));

    expect(screen.getByTestId("capability-dashboard-section-path")).toBeTruthy();
    expect(screen.getAllByText("native_turn").length).toBeGreaterThan(0);
    expect(screen.getAllByText("desktop_chat").length).toBeGreaterThan(0);
    expect(screen.getByText("1 tool (Memory)")).toBeTruthy();
    expect(screen.getByText("1 tool (Host)")).toBeTruthy();
    expect(screen.getByTestId("capability-dashboard-section-wiii_connect")).toBeTruthy();
    expect(screen.getByText("Document corpus")).toBeTruthy();
    expect(screen.getByText(/1 file/)).toBeTruthy();
    expect(screen.queryByText("host_action")).toBeNull();
    expect(screen.queryByText("document.read")).toBeNull();
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
