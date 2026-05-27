/**
 * UI store — sidebar, modals, theme state (not persisted).
 * Sprint 81: Added commandPaletteOpen state.
 * Sprint 192: Added activeView for full-page admin/settings layout.
 */
import { create } from "zustand";
import type { ArtifactData } from "@/api/types";

/** Sprint 192: Main content view — chat or full-page admin/settings */
export type ActiveView =
  | "chat"
  | "system-admin"
  | "org-admin"
  | "settings"
  | "soul-bridge"
  | "wiii-connect";

interface UIState {
  /** Sprint 192: Which view is displayed in the main content area */
  activeView: ActiveView;
  sidebarOpen: boolean;
  sourcesPanelOpen: boolean;
  selectedSourceIndex: number | null;
  commandPaletteOpen: boolean;
  inputFocused: boolean;
  characterPanelOpen: boolean;
  /** Sprint 166: Preview panel */
  previewPanelOpen: boolean;
  selectedPreviewId: string | null;
  /** Sprint 167: Artifact panel */
  artifactPanelOpen: boolean;
  selectedArtifactId: string | null;
  artifactActiveTab: "code" | "preview" | "output";
  /** Sprint 168: Ad-hoc artifact from CodeBlock "Sandbox" button */
  _ephemeralArtifact: ArtifactData | null;
  orgManagerTargetOrgId: string | null;
  /** Code Studio panel */
  codeStudioPanelOpen: boolean;

  /** Whether any right-side split panel is open (artifact, code studio, or preview) */
  hasRightPanel: () => boolean;

  // Actions
  toggleSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;
  openSettings: () => void;
  closeSettings: () => void;
  toggleSourcesPanel: () => void;
  selectSource: (index: number | null) => void;
  openCommandPalette: () => void;
  closeCommandPalette: () => void;
  toggleCommandPalette: () => void;
  setInputFocused: (focused: boolean) => void;
  toggleCharacterPanel: () => void;
  /** Sprint 166: Preview panel actions */
  openPreview: (id: string) => void;
  closePreview: () => void;
  togglePreviewPanel: () => void;
  /** Sprint 167: Artifact panel actions */
  openArtifact: (id: string, artifact?: ArtifactData) => void;
  closeArtifact: () => void;
  setArtifactTab: (tab: "code" | "preview" | "output") => void;
  /** Sprint 179: Admin panel */
  openAdminPanel: () => void;
  closeAdminPanel: () => void;
  /** Sprint 181: Org manager panel */
  openOrgManagerPanel: (orgId: string) => void;
  closeOrgManagerPanel: () => void;
  /** Sprint 216: Soul Bridge panel */
  openSoulBridge: () => void;
  closeSoulBridge: () => void;
  /** Wiii Connect capability page */
  openWiiiConnect: () => void;
  closeWiiiConnect: () => void;
  /** Code Studio panel actions */
  openCodeStudio: () => void;
  closeCodeStudio: () => void;
  /** Sprint 192: Navigate back to chat from any view */
  navigateToChat: () => void;
  closeAll: () => void;
}

export const useUIStore = create<UIState>((set, get) => ({
  activeView: "chat" as ActiveView,
  sidebarOpen: true,
  sourcesPanelOpen: false,
  selectedSourceIndex: null,
  commandPaletteOpen: false,
  inputFocused: false,
  characterPanelOpen: false,
  previewPanelOpen: false,
  selectedPreviewId: null,
  artifactPanelOpen: false,
  selectedArtifactId: null,
  artifactActiveTab: "code" as const,
  _ephemeralArtifact: null,
  orgManagerTargetOrgId: null,
  codeStudioPanelOpen: false,

  hasRightPanel: () => {
    const s = get();
    return s.artifactPanelOpen || s.codeStudioPanelOpen || s.previewPanelOpen;
  },

  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  setSidebarOpen: (open) => set({ sidebarOpen: open }),
  openSettings: () => set({ activeView: "settings" as ActiveView, commandPaletteOpen: false }),
  closeSettings: () => set({ activeView: "chat" as ActiveView }),
  toggleSourcesPanel: () =>
    set((s) => ({ sourcesPanelOpen: !s.sourcesPanelOpen, previewPanelOpen: false })),
  selectSource: (index) => set({ selectedSourceIndex: index }),
  openCommandPalette: () => set({ commandPaletteOpen: true }),
  closeCommandPalette: () => set({ commandPaletteOpen: false }),
  toggleCommandPalette: () =>
    set((s) => ({ commandPaletteOpen: !s.commandPaletteOpen })),
  setInputFocused: (focused) => set({ inputFocused: focused }),
  toggleCharacterPanel: () =>
    set((s) => ({
      characterPanelOpen: !s.characterPanelOpen,
      sourcesPanelOpen: s.characterPanelOpen ? s.sourcesPanelOpen : false,
    })),
  // Sprint 166: Preview panel — mutual exclusion with sources panel
  openPreview: (id) => set({ previewPanelOpen: true, selectedPreviewId: id, sourcesPanelOpen: false, artifactPanelOpen: false }),
  closePreview: () => set({ previewPanelOpen: false, selectedPreviewId: null }),
  togglePreviewPanel: () =>
    set((s) => ({ previewPanelOpen: !s.previewPanelOpen, sourcesPanelOpen: s.previewPanelOpen ? s.sourcesPanelOpen : false })),
  // Sprint 167: Artifact panel — mutual exclusion with preview + sources
  // Sprint 168: Optional artifact param for ad-hoc artifacts from CodeBlock
  openArtifact: (id, artifact) => set({ artifactPanelOpen: true, selectedArtifactId: id, artifactActiveTab: "code" as const, previewPanelOpen: false, sourcesPanelOpen: false, _ephemeralArtifact: artifact || null }),
  closeArtifact: () => set({ artifactPanelOpen: false, selectedArtifactId: null, _ephemeralArtifact: null }),
  setArtifactTab: (tab) => set({ artifactActiveTab: tab }),
  openAdminPanel: () => set({ activeView: "system-admin" as ActiveView, commandPaletteOpen: false }),
  closeAdminPanel: () => set({ activeView: "chat" as ActiveView }),
  openOrgManagerPanel: (orgId) => set({ activeView: "org-admin" as ActiveView, orgManagerTargetOrgId: orgId, commandPaletteOpen: false }),
  closeOrgManagerPanel: () => set({ activeView: "chat" as ActiveView, orgManagerTargetOrgId: null }),
  // Code Studio panel — mutual exclusion with artifact + preview + sources
  openCodeStudio: () => set({ codeStudioPanelOpen: true, artifactPanelOpen: false, previewPanelOpen: false, sourcesPanelOpen: false }),
  closeCodeStudio: () => set({ codeStudioPanelOpen: false }),
  openSoulBridge: () => set({ activeView: "soul-bridge" as ActiveView, commandPaletteOpen: false }),
  closeSoulBridge: () => set({ activeView: "chat" as ActiveView }),
  openWiiiConnect: () => set({ activeView: "wiii-connect" as ActiveView, commandPaletteOpen: false }),
  closeWiiiConnect: () => set({ activeView: "chat" as ActiveView, commandPaletteOpen: false }),
  navigateToChat: () => set({ activeView: "chat" as ActiveView, orgManagerTargetOrgId: null }),
  closeAll: () =>
    set({ activeView: "chat" as ActiveView, commandPaletteOpen: false, sourcesPanelOpen: false, characterPanelOpen: false, previewPanelOpen: false, selectedPreviewId: null, artifactPanelOpen: false, selectedArtifactId: null, _ephemeralArtifact: null, orgManagerTargetOrgId: null, codeStudioPanelOpen: false }),
}));
