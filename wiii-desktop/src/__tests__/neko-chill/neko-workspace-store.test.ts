import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  listWorkspaceFiles,
  listWorkspaceChanges,
  readWorkspaceFile,
  readWorkspaceDiff,
} = vi.hoisted(() => ({
  listWorkspaceFiles: vi.fn(),
  listWorkspaceChanges: vi.fn(),
  readWorkspaceFile: vi.fn(),
  readWorkspaceDiff: vi.fn(),
}));

vi.mock("@/neko-chill/workspace-files", () => ({
  listWorkspaceFiles,
  listWorkspaceChanges,
  readWorkspaceFile,
  readWorkspaceDiff,
}));

import { useNekoWorkspaceStore } from "@/neko-chill/stores/neko-workspace-store";

const WORKSPACE = { path: "C:/work/project", name: "project" };

function file(path: string, content = path) {
  return {
    path,
    name: path.split("/").at(-1)!,
    kind: "text" as const,
    language: "typescript",
    mimeType: "text/plain",
    size: content.length,
    modifiedAt: 1,
    content,
    dataUrl: null,
  };
}

describe("neko workspace store", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useNekoWorkspaceStore.setState({ sessions: {} });
    listWorkspaceFiles.mockResolvedValue({
      entries: [{ path: "src/App.tsx", name: "App.tsx", size: 10, modifiedAt: 1, language: "typescript" }],
      truncated: false,
    });
    listWorkspaceChanges.mockResolvedValue({
      isGit: true,
      changes: [{ path: "src/App.tsx", status: "modified", staged: false }],
    });
    readWorkspaceFile.mockImplementation(async (_workspace: string, path: string) =>
      file(path.replace("C:/work/project/", "")),
    );
    readWorkspaceDiff.mockResolvedValue({
      path: "src/App.tsx",
      status: "modified",
      language: "typescript",
      original: "before",
      modified: "after",
      binary: false,
    });
  });

  it("loads files and Git changes for one session", async () => {
    await useNekoWorkspaceStore.getState().refresh("session-1", WORKSPACE);
    const pane = useNekoWorkspaceStore.getState().sessions["session-1"];
    expect(pane.entries.map((entry) => entry.path)).toEqual(["src/App.tsx"]);
    expect(pane.changes).toHaveLength(1);
    expect(pane.isGit).toBe(true);
  });

  it("follows a completed structured ACP file activity", async () => {
    useNekoWorkspaceStore.getState().observeActivity("session-1", WORKSPACE, {
      id: "tool-1",
      title: "Write(src/App.tsx)",
      kind: "file",
      status: "completed",
      operation: "update",
      locations: [{ path: "C:/work/project/src/App.tsx" }],
    });

    await vi.waitFor(() => {
      expect(useNekoWorkspaceStore.getState().sessions["session-1"].selectedFile?.path)
        .toBe("src/App.tsx");
    });
    expect(useNekoWorkspaceStore.getState().sessions["session-1"]).toMatchObject({
      open: true,
      activeTab: "files",
      selectedPath: "src/App.tsx",
    });
  });

  it("keeps a pinned file selected and records unseen activity", async () => {
    await useNekoWorkspaceStore.getState().openFile("session-1", WORKSPACE, "src/App.tsx");
    useNekoWorkspaceStore.getState().setPinned("session-1", true);
    readWorkspaceFile.mockClear();

    useNekoWorkspaceStore.getState().observeActivity("session-1", WORKSPACE, {
      id: "tool-2",
      title: "Write(src/Other.ts)",
      kind: "file",
      status: "completed",
      operation: "update",
      locations: [{ path: "C:/work/project/src/Other.ts" }],
    });

    await vi.waitFor(() => {
      expect(useNekoWorkspaceStore.getState().sessions["session-1"].unseenChanges).toBe(1);
    });
    expect(useNekoWorkspaceStore.getState().sessions["session-1"].selectedPath)
      .toBe("src/App.tsx");
    expect(readWorkspaceFile).not.toHaveBeenCalled();
  });

  it("ignores a stale file response after the user selects another file", async () => {
    let resolveFirst!: (value: ReturnType<typeof file>) => void;
    readWorkspaceFile
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }))
      .mockResolvedValueOnce(file("src/Second.ts", "second"));

    const first = useNekoWorkspaceStore
      .getState()
      .openFile("session-1", WORKSPACE, "src/First.ts");
    const second = useNekoWorkspaceStore
      .getState()
      .openFile("session-1", WORKSPACE, "src/Second.ts");
    await second;
    resolveFirst(file("src/First.ts", "first"));
    await first;

    expect(useNekoWorkspaceStore.getState().sessions["session-1"].selectedFile?.path)
      .toBe("src/Second.ts");
  });

  it("ignores an older workspace refresh that finishes last", async () => {
    let resolveOldFiles!: (value: { entries: any[]; truncated: boolean }) => void;
    let resolveOldChanges!: (value: { isGit: boolean; changes: any[] }) => void;
    listWorkspaceFiles
      .mockImplementationOnce(() => new Promise((resolve) => { resolveOldFiles = resolve; }))
      .mockResolvedValueOnce({
        entries: [{ path: "src/New.ts", name: "New.ts", size: 2, modifiedAt: 2, language: "typescript" }],
        truncated: false,
      });
    listWorkspaceChanges
      .mockImplementationOnce(() => new Promise((resolve) => { resolveOldChanges = resolve; }))
      .mockResolvedValueOnce({ isGit: true, changes: [] });

    const older = useNekoWorkspaceStore.getState().refresh("session-1", WORKSPACE);
    const newer = useNekoWorkspaceStore.getState().refresh("session-1", WORKSPACE);
    await newer;
    resolveOldFiles({
      entries: [{ path: "src/Old.ts", name: "Old.ts", size: 1, modifiedAt: 1, language: "typescript" }],
      truncated: false,
    });
    resolveOldChanges({ isGit: true, changes: [] });
    await older;

    expect(useNekoWorkspaceStore.getState().sessions["session-1"].entries[0].path)
      .toBe("src/New.ts");
  });
});
