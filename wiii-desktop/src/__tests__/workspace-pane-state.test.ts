import { beforeEach, describe, expect, it } from "vitest";
import { useUIStore } from "@/stores/ui-store";

describe("workspace pane state", () => {
  beforeEach(() => {
    useUIStore.setState({
      rightPane: { kind: "closed" },
      workspaceFollowAgent: true,
      workspacePinned: false,
      previewPanelOpen: false,
      selectedPreviewId: null,
      artifactPanelOpen: false,
      selectedArtifactId: null,
      codeStudioPanelOpen: false,
    });
  });

  it("keeps exactly one right-side surface active", () => {
    useUIStore.getState().openPreview("preview-1");
    expect(useUIStore.getState()).toMatchObject({
      rightPane: { kind: "preview", id: "preview-1" },
      previewPanelOpen: true,
      artifactPanelOpen: false,
      codeStudioPanelOpen: false,
    });

    useUIStore.getState().openArtifact("artifact-1");
    expect(useUIStore.getState()).toMatchObject({
      rightPane: { kind: "artifact", id: "artifact-1" },
      previewPanelOpen: false,
      artifactPanelOpen: true,
      codeStudioPanelOpen: false,
    });

    useUIStore.getState().openCodeStudio();
    expect(useUIStore.getState()).toMatchObject({
      rightPane: { kind: "code-studio" },
      previewPanelOpen: false,
      artifactPanelOpen: false,
      codeStudioPanelOpen: true,
    });
  });

  it("does not let an agent event steal a pinned surface", () => {
    useUIStore.getState().openArtifact("artifact-1");
    useUIStore.getState().setWorkspacePinned(true);
    useUIStore.getState().revealPreview("preview-2");

    expect(useUIStore.getState().rightPane).toEqual({
      kind: "artifact",
      id: "artifact-1",
    });
  });

  it("follows agent events only when follow mode is enabled", () => {
    useUIStore.getState().setWorkspaceFollowAgent(false);
    useUIStore.getState().revealPreview("preview-1");
    expect(useUIStore.getState().rightPane).toEqual({ kind: "closed" });

    useUIStore.getState().setWorkspaceFollowAgent(true);
    useUIStore.getState().revealPreview("preview-1");
    expect(useUIStore.getState().rightPane).toEqual({
      kind: "preview",
      id: "preview-1",
    });
  });

  it("a surface-specific close cannot close a different active surface", () => {
    useUIStore.getState().openArtifact("artifact-1");
    useUIStore.getState().closePreview();
    expect(useUIStore.getState().rightPane).toEqual({
      kind: "artifact",
      id: "artifact-1",
    });
  });
});
