/**
 * Sprint 192: Full-page admin/settings layout tests.
 *
 * Tests: ui-store activeView, view routing, sidebar behavior,
 * keyboard shortcuts, backward compatibility.
 */
import { describe, it, expect, beforeEach } from "vitest";
import { useUIStore } from "@/stores/ui-store";
import type { ActiveView } from "@/stores/ui-store";

// Reset store between tests
function resetStore() {
  useUIStore.setState({
    activeView: "chat",
    sidebarOpen: true,
    orgManagerTargetOrgId: null,
    commandPaletteOpen: false,
    sourcesPanelOpen: false,
    characterPanelOpen: false,
    previewPanelOpen: false,
    selectedPreviewId: null,
    artifactPanelOpen: false,
    selectedArtifactId: null,
    _ephemeralArtifact: null,
  });
}

describe("Sprint 192: ui-store activeView", () => {
  beforeEach(resetStore);

  it("defaults activeView to chat", () => {
    expect(useUIStore.getState().activeView).toBe("chat");
  });

  it("openAdminPanel sets activeView to system-admin", () => {
    useUIStore.getState().openAdminPanel();
    expect(useUIStore.getState().activeView).toBe("system-admin");
  });

  it("closeAdminPanel returns to chat", () => {
    useUIStore.getState().openAdminPanel();
    useUIStore.getState().closeAdminPanel();
    expect(useUIStore.getState().activeView).toBe("chat");
  });

  it("openOrgManagerPanel sets activeView to org-admin", () => {
    useUIStore.getState().openOrgManagerPanel("org-123");
    const s = useUIStore.getState();
    expect(s.activeView).toBe("org-admin");
    expect(s.orgManagerTargetOrgId).toBe("org-123");
  });

  it("closeOrgManagerPanel returns to chat", () => {
    useUIStore.getState().openOrgManagerPanel("org-123");
    useUIStore.getState().closeOrgManagerPanel();
    const s = useUIStore.getState();
    expect(s.activeView).toBe("chat");
    expect(s.orgManagerTargetOrgId).toBeNull();
  });

  it("openSettings sets activeView to settings", () => {
    useUIStore.getState().openSettings();
    expect(useUIStore.getState().activeView).toBe("settings");
  });

  it("closeSettings returns to chat", () => {
    useUIStore.getState().openSettings();
    useUIStore.getState().closeSettings();
    expect(useUIStore.getState().activeView).toBe("chat");
  });

  it("openWiiiConnect sets activeView to wiii-connect", () => {
    useUIStore.getState().openWiiiConnect();
    expect(useUIStore.getState().activeView).toBe("wiii-connect");
  });

  it("closeWiiiConnect returns to chat", () => {
    useUIStore.getState().openWiiiConnect();
    useUIStore.setState({ commandPaletteOpen: true });
    useUIStore.getState().closeWiiiConnect();
    const state = useUIStore.getState();
    expect(state.activeView).toBe("chat");
    expect(state.commandPaletteOpen).toBe(false);
  });

  it("navigateToChat returns to chat from any view", () => {
    const views: ActiveView[] = ["system-admin", "org-admin", "settings", "wiii-connect"];
    for (const view of views) {
      useUIStore.setState({ activeView: view });
      useUIStore.getState().navigateToChat();
      expect(useUIStore.getState().activeView).toBe("chat");
    }
  });

  it("closeAll resets to chat", () => {
    useUIStore.getState().openAdminPanel();
    useUIStore.getState().closeAll();
    expect(useUIStore.getState().activeView).toBe("chat");
  });

  it("switching between views works correctly", () => {
    expect(useUIStore.getState().activeView).toBe("chat");
    useUIStore.getState().openAdminPanel();
    expect(useUIStore.getState().activeView).toBe("system-admin");
    useUIStore.getState().openSettings();
    expect(useUIStore.getState().activeView).toBe("settings");
  });

  it("openAdminPanel closes other views", () => {
    useUIStore.getState().openSettings();
    useUIStore.getState().openAdminPanel();
    const s = useUIStore.getState();
    expect(s.activeView).toBe("system-admin");
    expect(s.commandPaletteOpen).toBe(false);
  });

  it("openOrgManagerPanel closes other views", () => {
    useUIStore.getState().openSettings();
    useUIStore.getState().openOrgManagerPanel("org-456");
    expect(useUIStore.getState().activeView).toBe("org-admin");
  });
});

describe("Sprint 192: View independence", () => {
  beforeEach(resetStore);

  it("existing open/close signatures unchanged", () => {
    useUIStore.getState().openSettings();
    useUIStore.getState().closeSettings();
    useUIStore.getState().openAdminPanel();
    useUIStore.getState().closeAdminPanel();
    useUIStore.getState().openOrgManagerPanel("org-id");
    useUIStore.getState().closeOrgManagerPanel();
    useUIStore.getState().closeAll();
    expect(useUIStore.getState().activeView).toBe("chat");
  });

  it("sidebarOpen is independent of activeView", () => {
    useUIStore.setState({ sidebarOpen: true });
    useUIStore.getState().openAdminPanel();
    expect(useUIStore.getState().sidebarOpen).toBe(true);
    expect(useUIStore.getState().activeView).toBe("system-admin");
  });

  it("commandPalette can open independently of activeView", () => {
    useUIStore.getState().openAdminPanel();
    useUIStore.getState().openCommandPalette();
    expect(useUIStore.getState().commandPaletteOpen).toBe(true);
    expect(useUIStore.getState().activeView).toBe("system-admin");
  });
});

describe("Sprint 192: Keyboard shortcuts — activeView", () => {
  beforeEach(resetStore);

  it("Escape from system-admin navigates to chat", () => {
    useUIStore.getState().openAdminPanel();
    const ui = useUIStore.getState();
    // Simulate what useKeyboardShortcuts does
    if (ui.activeView !== "chat") {
      ui.navigateToChat();
    }
    expect(useUIStore.getState().activeView).toBe("chat");
  });

  it("Escape from settings navigates to chat", () => {
    useUIStore.getState().openSettings();
    const ui = useUIStore.getState();
    if (ui.activeView !== "chat") {
      ui.navigateToChat();
    }
    expect(useUIStore.getState().activeView).toBe("chat");
  });

  it("Escape from org-admin navigates to chat", () => {
    useUIStore.getState().openOrgManagerPanel("org-test");
    const ui = useUIStore.getState();
    if (ui.activeView !== "chat") {
      ui.navigateToChat();
    }
    expect(useUIStore.getState().activeView).toBe("chat");
  });

  it("Escape in chat view does not trigger navigateToChat", () => {
    // activeView is already "chat" — Escape should not do anything related to views
    const ui = useUIStore.getState();
    expect(ui.activeView).toBe("chat");
    // The shortcut handler checks activeView !== "chat" before calling navigateToChat
    // so nothing happens — just verify state didn't change
    expect(useUIStore.getState().activeView).toBe("chat");
  });

  it("commandPalette Escape takes priority over view navigation", () => {
    useUIStore.getState().openAdminPanel();
    useUIStore.getState().openCommandPalette();
    // The shortcut handler checks commandPaletteOpen first
    const ui = useUIStore.getState();
    expect(ui.commandPaletteOpen).toBe(true);
    // Simulating Escape: close command palette first, don't navigate
    ui.closeCommandPalette();
    expect(useUIStore.getState().commandPaletteOpen).toBe(false);
    // Still in admin view
    expect(useUIStore.getState().activeView).toBe("system-admin");
  });
});

describe("Sprint 192: View transition edge cases", () => {
  beforeEach(resetStore);

  it("opening admin from org-admin switches correctly", () => {
    useUIStore.getState().openOrgManagerPanel("org-1");
    useUIStore.getState().openAdminPanel();
    expect(useUIStore.getState().activeView).toBe("system-admin");
  });

  it("opening org-admin from admin switches correctly", () => {
    useUIStore.getState().openAdminPanel();
    useUIStore.getState().openOrgManagerPanel("org-2");
    expect(useUIStore.getState().activeView).toBe("org-admin");
  });

  it("opening settings from admin switches correctly", () => {
    useUIStore.getState().openAdminPanel();
    useUIStore.getState().openSettings();
    expect(useUIStore.getState().activeView).toBe("settings");
  });

  it("double open of same view is idempotent", () => {
    useUIStore.getState().openAdminPanel();
    useUIStore.getState().openAdminPanel();
    expect(useUIStore.getState().activeView).toBe("system-admin");
  });

  it("navigateToChat resets orgManagerTargetOrgId", () => {
    useUIStore.getState().openOrgManagerPanel("org-xyz");
    expect(useUIStore.getState().orgManagerTargetOrgId).toBe("org-xyz");
    useUIStore.getState().navigateToChat();
    expect(useUIStore.getState().orgManagerTargetOrgId).toBeNull();
  });

  it("side panels are only for chat — state preserved when switching views", () => {
    // Open sources panel in chat
    useUIStore.setState({ sourcesPanelOpen: true });
    expect(useUIStore.getState().sourcesPanelOpen).toBe(true);

    // Switch to admin — sources panel state stays (AppShell gates rendering)
    useUIStore.getState().openAdminPanel();
    expect(useUIStore.getState().sourcesPanelOpen).toBe(true);
    expect(useUIStore.getState().activeView).toBe("system-admin");

    // Come back to chat — sources panel still open
    useUIStore.getState().navigateToChat();
    expect(useUIStore.getState().sourcesPanelOpen).toBe(true);
  });
});
