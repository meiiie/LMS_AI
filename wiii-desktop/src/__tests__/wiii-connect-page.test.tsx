import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { WiiiConnectPage } from "@/components/connect/WiiiConnectPage";
import { useChatStore } from "@/stores/chat-store";
import { useConnectionStore } from "@/stores/connection-store";
import { useHostContextStore } from "@/stores/host-context-store";
import { useUIStore } from "@/stores/ui-store";

describe("WiiiConnectPage", () => {
  beforeEach(() => {
    useHostContextStore.getState().clear();
    useConnectionStore.setState({
      status: "connected",
      serverVersion: "test-version",
      lastCheckedAt: "2026-05-28T12:00:00.000Z",
      errorMessage: null,
      pollIntervalId: null,
    });
    useChatStore.setState({
      streamingLifecycleEvents: [],
      lastCompletedLifecycleEvents: [],
    });
    useUIStore.setState({
      activeView: "wiii-connect",
      commandPaletteOpen: false,
      sidebarOpen: true,
    });
  });

  it("renders sanitized Wiii Connect snapshot without raw tool or token payloads", async () => {
    useChatStore.setState({
      lastCompletedLifecycleEvents: [
        {
          schema_version: "1",
          event_name: "path.selected",
          phase: "routing",
          status: "selected",
          message: "Selected document path",
          lane: "document_grounded_answer",
          capabilities: {
            host_surface: "desktop_chat",
            observed_tools: ["authoring.apply_lesson_patch", "document.read"],
            suppressed_tools: ["host_action.execute"],
            approval_token_present: true,
            wiii_connect: {
              version: "wiii_connect_snapshot.v0",
              generated_at: "2026-05-28T12:00:00.000Z",
              surface: "desktop_chat",
              connections: [
                {
                  slug: "document_corpus",
                  label: "Document corpus",
                  provider_kind: "wiii_native",
                  status: "connected",
                  active: true,
                  agent_ready: true,
                  capabilities: ["document.read", "document.cite"],
                  required_for_paths: ["document_grounded_answer"],
                  scopes: { read: true },
                  attachment_count: 1,
                  source_ref_count: 2,
                  last_checked_at: "2026-05-28T12:00:00.000Z",
                  reason: "active",
                },
                {
                  slug: "lms_authoring",
                  label: "LMS authoring",
                  provider_kind: "wiii_native",
                  status: "not_connected",
                  active: false,
                  agent_ready: false,
                  capabilities: ["authoring.apply_lesson_patch"],
                  required_for_paths: ["lms_document_preview", "lms_document_apply"],
                  scopes: { read: false, preview: false, apply: false },
                  reason: "missing_lms_host",
                },
              ],
              path_capabilities: [
                {
                  path: "document_grounded_answer",
                  required_connection_slugs: ["document_corpus"],
                  allowed_tool_groups: ["knowledge_search"],
                  mutation_policy: "none",
                  delegation_policy: "direct_only",
                },
                {
                  path: "lms_document_apply",
                  required_connection_slugs: ["lms_authoring"],
                  allowed_tool_groups: ["lms_authoring"],
                  mutation_policy: "approval_token_required",
                  delegation_policy: "direct_only",
                },
              ],
            },
          },
          received_at_ms: 1779969600000,
        },
      ],
    });

    render(<WiiiConnectPage />);

    expect(screen.getByTestId("wiii-connect-page")).toBeTruthy();
    expect(screen.getByText("Document corpus")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Document corpus/i }));
    expect(screen.getByText("2 capability")).toBeTruthy();
    expect(screen.getByText(/1 file/)).toBeTruthy();
    expect(screen.queryByText("document.read")).toBeNull();
    expect(screen.queryByText("authoring.apply_lesson_patch")).toBeNull();
    expect(screen.queryByText("host_action.execute")).toBeNull();
    expect(screen.queryByText("approval-token")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Path policy/i }));

    expect(screen.getByText("document_grounded_answer")).toBeTruthy();
    expect(await screen.findByText("lms_document_apply")).toBeTruthy();
    expect(screen.getByText("Cần approval_token")).toBeTruthy();
  });

  it("shows a fail-closed connection catalog before a backend snapshot exists", () => {
    useHostContextStore.getState().setCapabilities({
      host_type: "desktop",
      host_name: "Wiii Desktop",
      tools: [{ name: "ui.highlight", description: "Highlight" }],
    });

    render(<WiiiConnectPage />);

    expect(screen.getAllByText("Chưa có snapshot").length).toBeGreaterThan(0);
    expect(screen.getByText("Danh bạ kết nối")).toBeTruthy();
    expect(screen.getByText("Đang dùng fallback local")).toBeTruthy();
    expect(screen.getAllByText("Máy chủ Wiii").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: /Composio/i }));
    expect(screen.getByRole("button", { name: /Facebook/i })).toBeTruthy();
    expect(screen.getAllByText("Chưa bật").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: /Facebook/i }));
    expect(screen.getByText("Token vault")).toBeTruthy();
    const disabledConnectButton = screen.getByRole("button", {
      name: "Chưa thể kết nối",
    }) as HTMLButtonElement;
    expect(disabledConnectButton.disabled).toBe(true);

    fireEvent.change(screen.getByPlaceholderText("Tìm kết nối..."), {
      target: { value: "facebook" },
    });
    expect(screen.getByRole("button", { name: /Facebook/i })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Gmail/i })).toBeNull();
    expect(screen.queryByText("ui.highlight")).toBeNull();
  });
});
