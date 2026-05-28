import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  buildWiiiConnectProviderCallbackUrl,
  createWiiiConnectProviderAuthorizationUrl,
  fetchWiiiConnectProviderConnections,
  fetchWiiiConnectProviders,
  startWiiiConnectProviderSession,
} from "@/api/wiii-connect";
import { WiiiConnectPage } from "@/components/connect/WiiiConnectPage";
import { useChatStore } from "@/stores/chat-store";
import { useConnectionStore } from "@/stores/connection-store";
import { useHostContextStore } from "@/stores/host-context-store";
import { useUIStore } from "@/stores/ui-store";

vi.mock("@/api/wiii-connect", () => ({
  buildWiiiConnectProviderCallbackUrl: vi.fn(),
  createWiiiConnectProviderAuthorizationUrl: vi.fn(),
  fetchWiiiConnectProviderConnections: vi.fn(),
  fetchWiiiConnectProviders: vi.fn(),
  startWiiiConnectProviderSession: vi.fn(),
}));

vi.mock("@tauri-apps/plugin-shell", () => ({
  open: vi.fn().mockRejectedValue(new Error("no tauri runtime")),
}));

const mockBuildWiiiConnectProviderCallbackUrl = vi.mocked(buildWiiiConnectProviderCallbackUrl);
const mockCreateWiiiConnectProviderAuthorizationUrl = vi.mocked(createWiiiConnectProviderAuthorizationUrl);
const mockFetchWiiiConnectProviderConnections = vi.mocked(fetchWiiiConnectProviderConnections);
const mockFetchWiiiConnectProviders = vi.mocked(fetchWiiiConnectProviders);
const mockStartWiiiConnectProviderSession = vi.mocked(startWiiiConnectProviderSession);

describe("WiiiConnectPage", () => {
  beforeEach(() => {
    mockFetchWiiiConnectProviders.mockReset();
    mockFetchWiiiConnectProviders.mockRejectedValue(new Error("offline"));
    mockBuildWiiiConnectProviderCallbackUrl.mockReset();
    mockBuildWiiiConnectProviderCallbackUrl.mockReturnValue("http://localhost:8080/api/v1/wiii-connect/providers/facebook/callback");
    mockCreateWiiiConnectProviderAuthorizationUrl.mockReset();
    mockCreateWiiiConnectProviderAuthorizationUrl.mockRejectedValue(new Error("offline"));
    mockFetchWiiiConnectProviderConnections.mockReset();
    mockFetchWiiiConnectProviderConnections.mockRejectedValue(new Error("offline"));
    mockStartWiiiConnectProviderSession.mockReset();
    mockStartWiiiConnectProviderSession.mockRejectedValue(new Error("offline"));
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
    expect(screen.getAllByText("Chưa nối").length).toBeGreaterThan(0);

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

  it("uses backend provider registry when available", async () => {
    mockFetchWiiiConnectProviders.mockResolvedValue({
      version: "wiii_connect_provider_registry.v1",
      adapter_version: "wiii_connect_adapter.v1",
      providers: [
        {
          slug: "facebook",
          label: "Facebook",
          provider_kind: "composio",
          auth_mode: "oauth2",
          enabled: false,
          agent_ready: false,
          category: "social",
          description: "Facebook provider from backend registry.",
          requirements: ["execution_gateway", "audit_ledger"],
          action_count: 0,
        },
      ],
    });

    render(<WiiiConnectPage />);

    expect(await screen.findByText("Registry backend")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Composio/i }));
    fireEvent.click(screen.getByRole("button", { name: /Facebook/i }));
    expect(screen.getAllByText("Facebook provider from backend registry.").length).toBeGreaterThan(0);
    expect(screen.getByText("execution_gateway")).toBeTruthy();
    expect(screen.getByText("audit_ledger")).toBeTruthy();
    expect(screen.getByText("Backend registry")).toBeTruthy();
  });

  it("requests backend session decision for backend registry providers", async () => {
    mockFetchWiiiConnectProviders.mockResolvedValue({
      version: "wiii_connect_provider_registry.v1",
      adapter_version: "wiii_connect_adapter.v1",
      providers: [
        {
          slug: "facebook",
          label: "Facebook",
          provider_kind: "composio",
          auth_mode: "oauth2",
          enabled: false,
          agent_ready: false,
          category: "social",
          description: "Facebook provider from backend registry.",
          requirements: ["execution_gateway", "audit_ledger"],
          action_count: 0,
        },
      ],
    });
    mockStartWiiiConnectProviderSession.mockResolvedValue({
      version: "wiii_connect_session.v1",
      status: "blocked",
      reason: "provider_disabled",
      provider_slug: "facebook",
      label: "Facebook",
      provider_kind: "composio",
      auth_mode: "oauth2",
      authorization_url: "",
      required_next: ["encrypted_vault_ref", "execution_gateway"],
      audit_event: {
        version: "wiii_connect_session.v1",
        stage: "start_requested",
        reason: "provider_disabled",
        created_at: "2026-05-28T00:00:00Z",
        request: {
          provider_slug: "facebook",
          surface: "desktop",
          requested_scopes: { read: true },
          redirect_uri_present: false,
          request_metadata_keys: ["source", "provider"],
        },
      },
    });

    render(<WiiiConnectPage />);

    expect(await screen.findByText("Registry backend")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Composio/i }));
    fireEvent.click(screen.getByRole("button", { name: /Facebook/i }));
    fireEvent.click(screen.getByRole("button", { name: "Kiểm tra policy" }));

    expect(mockStartWiiiConnectProviderSession).toHaveBeenCalledWith("facebook", {
      surface: "desktop",
      requested_scopes: { read: true },
      request_metadata: {
        source: "wiii_connect_page",
        provider: "composio",
      },
    });
    expect(await screen.findByText("Quyết định backend")).toBeTruthy();
    expect(screen.getByText("provider_disabled")).toBeTruthy();
    expect(screen.getByText("encrypted_vault_ref")).toBeTruthy();
    expect(screen.getByText("Không phát hành")).toBeTruthy();
    expect(screen.queryByText("access_token")).toBeNull();
    expect(screen.queryByText("secret-value")).toBeNull();
  });

  it("starts backend-owned authorization and renders sanitized provider connections", async () => {
    mockFetchWiiiConnectProviders.mockResolvedValue({
      version: "wiii_connect_provider_registry.v1",
      adapter_version: "wiii_connect_adapter.v1",
      providers: [
        {
          slug: "facebook",
          label: "Facebook",
          provider_kind: "composio",
          auth_mode: "oauth2",
          enabled: true,
          agent_ready: false,
          category: "social",
          description: "Facebook provider from backend registry.",
          requirements: ["curated_action_catalog"],
          connect_requirements: ["provider_managed_vault_ref", "durable_audit_ledger"],
          agent_ready_requirements: ["execution_gateway"],
          action_count: 0,
        },
      ],
    });
    mockCreateWiiiConnectProviderAuthorizationUrl.mockResolvedValue({
      version: "wiii_connect_provider_adapter.v1",
      status: "ready",
      reason: "authorization_url_issued",
      provider_slug: "facebook",
      label: "Facebook",
      provider_kind: "composio",
      auth_mode: "oauth2",
      authorization_url: "https://composio.example/connect/safe",
      adapter: {
        version: "wiii_connect_provider_adapter.v1",
        provider_kind: "composio",
        adapter_name: "composio",
        bound: true,
        configured: true,
        can_create_authorization_url: true,
        can_exchange_callback: true,
        can_execute_actions: false,
        authorization_ready: true,
        reason: "configured",
        warnings: [],
      },
      required_next: [],
      audit_event: null,
    });
    mockFetchWiiiConnectProviderConnections.mockResolvedValue({
      version: "wiii_connect_connection_list.v1",
      status: "ready",
      reason: "listed",
      provider_slug: "facebook",
      provider_kind: "composio",
      connection_count: 1,
      connections: [
        {
          version: "wiii_connect_adapter.v1",
          connection_id: "conn_public_1",
          provider_slug: "facebook",
          state: "connected",
          active: true,
          scopes: { read: true, write: false },
          vault_ref_present: true,
          account_label: "Wiii Facebook Page",
          external_account_ref: "fb_page_public",
          last_checked_at: "2026-05-28T00:00:00Z",
          reason: "provider_listed",
          warnings: [],
        },
      ],
      provider: { status: "ready" },
      storage: { persistent: true },
    });
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);

    render(<WiiiConnectPage />);

    expect(await screen.findByText("Registry backend")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Composio/i }));
    fireEvent.click(screen.getByRole("button", { name: /Facebook/i }));
    fireEvent.click(screen.getByRole("button", { name: "Kết nối qua Wiii" }));

    expect(await screen.findByText("Connect Link backend")).toBeTruthy();
    expect(mockCreateWiiiConnectProviderAuthorizationUrl).toHaveBeenCalledWith("facebook", {
      surface: "desktop",
      redirect_uri: "http://localhost:8080/api/v1/wiii-connect/providers/facebook/callback",
      probe_database: true,
      requested_scopes: { read: true },
      request_metadata: {
        source: "wiii_connect_page",
        provider: "composio",
      },
    });
    expect(openSpy).toHaveBeenCalledWith(
      "https://composio.example/connect/safe",
      "_blank",
      "noopener,noreferrer",
    );
    expect(await screen.findByText("Connection thật")).toBeTruthy();
    expect(screen.getAllByText("Wiii Facebook Page").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Đã kết nối").length).toBeGreaterThan(0);
    expect(screen.queryByText("access_token")).toBeNull();
    expect(screen.queryByText("secret-value")).toBeNull();

    openSpy.mockRestore();
  });
});
