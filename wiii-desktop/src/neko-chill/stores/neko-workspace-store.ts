import { create } from "zustand";
import type { DriverActivity, DriverFileOperation } from "../drivers/types";
import type { WorkspaceRef } from "../workspace";
import {
  listWorkspaceChanges,
  listWorkspaceFiles,
  readWorkspaceDiff,
  readWorkspaceFile,
  type WorkspaceChange,
  type WorkspaceDiff,
  type WorkspaceEntry,
  type WorkspaceFile,
} from "../workspace-files";

export type NekoWorkspaceTab = "files" | "changes";

export interface ObservedWorkspaceActivity {
  activityId: string;
  path: string;
  operation: DriverFileOperation | null;
  status: DriverActivity["status"];
  title: string;
  updatedAt: number;
}

export interface NekoWorkspaceSession {
  open: boolean;
  activeTab: NekoWorkspaceTab;
  followAgent: boolean;
  pinned: boolean;
  entries: WorkspaceEntry[];
  filesTruncated: boolean;
  changes: WorkspaceChange[];
  isGit: boolean | null;
  selectedPath: string | null;
  selectedFile: WorkspaceFile | null;
  selectedDiff: WorkspaceDiff | null;
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  unseenChanges: number;
  activities: Record<string, ObservedWorkspaceActivity>;
}

interface NekoWorkspaceState {
  sessions: Record<string, NekoWorkspaceSession>;
  ensureSession: (sessionId: string) => void;
  toggle: (sessionId: string) => void;
  close: (sessionId: string) => void;
  setTab: (sessionId: string, tab: NekoWorkspaceTab) => void;
  setFollowAgent: (sessionId: string, follow: boolean) => void;
  setPinned: (sessionId: string, pinned: boolean) => void;
  refresh: (sessionId: string, workspace: WorkspaceRef) => Promise<void>;
  openFile: (sessionId: string, workspace: WorkspaceRef, path: string) => Promise<void>;
  openChange: (sessionId: string, workspace: WorkspaceRef, path: string) => Promise<void>;
  observeActivity: (
    sessionId: string,
    workspace: WorkspaceRef,
    activity: DriverActivity,
  ) => void;
  restoreActivities: (
    sessionId: string,
    workspace: WorkspaceRef,
    activities: DriverActivity[],
  ) => void;
  clearSession: (sessionId: string) => void;
}

const requestVersions = new Map<string, number>();
const refreshVersions = new Map<string, number>();

function emptySession(): NekoWorkspaceSession {
  return {
    open: false,
    activeTab: "files",
    followAgent: true,
    pinned: false,
    entries: [],
    filesTruncated: false,
    changes: [],
    isGit: null,
    selectedPath: null,
    selectedFile: null,
    selectedDiff: null,
    loading: false,
    refreshing: false,
    error: null,
    unseenChanges: 0,
    activities: {},
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function relativePath(workspace: WorkspaceRef, path: string): string {
  const normalizedRoot = workspace.path.replace(/\\/g, "/").replace(/\/+$/, "");
  const normalizedPath = path.replace(/\\/g, "/");
  const rootLower = normalizedRoot.toLocaleLowerCase();
  const pathLower = normalizedPath.toLocaleLowerCase();
  if (pathLower === rootLower) return "";
  if (pathLower.startsWith(`${rootLower}/`)) {
    return normalizedPath.slice(normalizedRoot.length + 1);
  }
  return normalizedPath;
}

function nextRequestVersion(sessionId: string): number {
  const next = (requestVersions.get(sessionId) ?? 0) + 1;
  requestVersions.set(sessionId, next);
  return next;
}

function isCurrentRequest(sessionId: string, version: number): boolean {
  return requestVersions.get(sessionId) === version;
}

export const useNekoWorkspaceStore = create<NekoWorkspaceState>((set, get) => ({
  sessions: {},

  ensureSession: (sessionId) =>
    set((state) =>
      state.sessions[sessionId]
        ? state
        : { sessions: { ...state.sessions, [sessionId]: emptySession() } },
    ),

  toggle: (sessionId) =>
    set((state) => {
      const current = state.sessions[sessionId] ?? emptySession();
      return {
        sessions: {
          ...state.sessions,
          [sessionId]: { ...current, open: !current.open, unseenChanges: 0 },
        },
      };
    }),

  close: (sessionId) =>
    set((state) => {
      const current = state.sessions[sessionId];
      if (!current) return state;
      return {
        sessions: {
          ...state.sessions,
          [sessionId]: { ...current, open: false, pinned: false },
        },
      };
    }),

  setTab: (sessionId, activeTab) =>
    set((state) => {
      const current = state.sessions[sessionId] ?? emptySession();
      return {
        sessions: {
          ...state.sessions,
          [sessionId]: {
            ...current,
            activeTab,
            open: true,
            selectedFile: activeTab === "files" ? current.selectedFile : null,
            selectedDiff: activeTab === "changes" ? current.selectedDiff : null,
            error: null,
            unseenChanges: 0,
          },
        },
      };
    }),

  setFollowAgent: (sessionId, followAgent) =>
    set((state) => {
      const current = state.sessions[sessionId] ?? emptySession();
      return {
        sessions: {
          ...state.sessions,
          [sessionId]: { ...current, followAgent },
        },
      };
    }),

  setPinned: (sessionId, pinned) =>
    set((state) => {
      const current = state.sessions[sessionId] ?? emptySession();
      return {
        sessions: { ...state.sessions, [sessionId]: { ...current, pinned } },
      };
    }),

  refresh: async (sessionId, workspace) => {
    const refreshVersion = (refreshVersions.get(sessionId) ?? 0) + 1;
    refreshVersions.set(sessionId, refreshVersion);
    get().ensureSession(sessionId);
    set((state) => ({
      sessions: {
        ...state.sessions,
        [sessionId]: {
          ...(state.sessions[sessionId] ?? emptySession()),
          refreshing: true,
          error: null,
        },
      },
    }));
    const [files, changes] = await Promise.allSettled([
      listWorkspaceFiles(workspace.path),
      listWorkspaceChanges(workspace.path),
    ]);
    if (refreshVersions.get(sessionId) !== refreshVersion) return;
    set((state) => {
      const current = state.sessions[sessionId];
      if (!current) return state;
      const errors = [files, changes]
        .filter((result): result is PromiseRejectedResult => result.status === "rejected")
        .map((result) => errorMessage(result.reason));
      return {
        sessions: {
          ...state.sessions,
          [sessionId]: {
            ...current,
            refreshing: false,
            entries: files.status === "fulfilled" ? files.value.entries : current.entries,
            filesTruncated:
              files.status === "fulfilled" ? files.value.truncated : current.filesTruncated,
            changes:
              changes.status === "fulfilled" ? changes.value.changes : current.changes,
            isGit: changes.status === "fulfilled" ? changes.value.isGit : current.isGit,
            error: errors.length ? errors.join(" · ") : null,
          },
        },
      };
    });
  },

  openFile: async (sessionId, workspace, path) => {
    const version = nextRequestVersion(sessionId);
    set((state) => {
      const current = state.sessions[sessionId] ?? emptySession();
      return {
        sessions: {
          ...state.sessions,
          [sessionId]: {
            ...current,
            open: true,
            activeTab: "files",
            selectedPath: relativePath(workspace, path),
            selectedFile: null,
            selectedDiff: null,
            loading: true,
            error: null,
            unseenChanges: 0,
          },
        },
      };
    });
    try {
      const selectedFile = await readWorkspaceFile(workspace.path, path);
      if (!isCurrentRequest(sessionId, version)) return;
      set((state) => {
        const current = state.sessions[sessionId];
        if (!current) return state;
        return {
          sessions: {
            ...state.sessions,
            [sessionId]: {
              ...current,
              selectedPath: selectedFile.path,
              selectedFile,
              loading: false,
            },
          },
        };
      });
    } catch (error) {
      if (!isCurrentRequest(sessionId, version)) return;
      set((state) => {
        const current = state.sessions[sessionId];
        if (!current) return state;
        return {
          sessions: {
            ...state.sessions,
            [sessionId]: { ...current, loading: false, error: errorMessage(error) },
          },
        };
      });
    }
  },

  openChange: async (sessionId, workspace, path) => {
    const version = nextRequestVersion(sessionId);
    set((state) => {
      const current = state.sessions[sessionId] ?? emptySession();
      return {
        sessions: {
          ...state.sessions,
          [sessionId]: {
            ...current,
            open: true,
            activeTab: "changes",
            selectedPath: relativePath(workspace, path),
            selectedFile: null,
            selectedDiff: null,
            loading: true,
            error: null,
            unseenChanges: 0,
          },
        },
      };
    });
    try {
      const selectedDiff = await readWorkspaceDiff(workspace.path, path);
      if (!isCurrentRequest(sessionId, version)) return;
      set((state) => {
        const current = state.sessions[sessionId];
        if (!current) return state;
        return {
          sessions: {
            ...state.sessions,
            [sessionId]: { ...current, selectedDiff, loading: false },
          },
        };
      });
    } catch (error) {
      if (!isCurrentRequest(sessionId, version)) return;
      set((state) => {
        const current = state.sessions[sessionId];
        if (!current) return state;
        return {
          sessions: {
            ...state.sessions,
            [sessionId]: { ...current, loading: false, error: errorMessage(error) },
          },
        };
      });
    }
  },

  observeActivity: (sessionId, workspace, activity) => {
    if (!activity.locations?.length) return;
    const now = Date.now();
    set((state) => {
      const current = state.sessions[sessionId] ?? emptySession();
      const activities = { ...current.activities };
      for (const location of activity.locations ?? []) {
        const path = relativePath(workspace, location.path);
        activities[path] = {
          activityId: activity.id,
          path,
          operation: activity.operation ?? null,
          status: activity.status,
          title: activity.title,
          updatedAt: now,
        };
      }
      const shouldFollow = current.followAgent && !current.pinned;
      return {
        sessions: {
          ...state.sessions,
          [sessionId]: {
            ...current,
            activities,
            open: shouldFollow ? true : current.open,
            activeTab: shouldFollow ? "files" : current.activeTab,
            selectedPath: shouldFollow
              ? relativePath(workspace, activity.locations![0].path)
              : current.selectedPath,
            unseenChanges: shouldFollow ? 0 : current.unseenChanges + 1,
          },
        },
      };
    });

    const current = get().sessions[sessionId];
    const firstPath = activity.locations[0].path;
    if (current?.followAgent && !current.pinned && activity.status !== "pending") {
      if (activity.operation === "delete") {
        void get().openChange(sessionId, workspace, relativePath(workspace, firstPath));
      } else {
        void get().openFile(sessionId, workspace, firstPath);
      }
    }
    if (["completed", "failed", "cancelled"].includes(activity.status)) {
      void get().refresh(sessionId, workspace);
    }
  },

  restoreActivities: (sessionId, workspace, activities) => {
    set((state) => {
      const current = state.sessions[sessionId] ?? emptySession();
      const restored = { ...current.activities };
      activities.forEach((activity, index) => {
        for (const location of activity.locations ?? []) {
          const path = relativePath(workspace, location.path);
          restored[path] = {
            activityId: activity.id,
            path,
            operation: activity.operation ?? null,
            status: activity.status,
            title: activity.title,
            updatedAt: index,
          };
        }
      });
      return {
        sessions: {
          ...state.sessions,
          [sessionId]: { ...current, activities: restored },
        },
      };
    });
  },

  clearSession: (sessionId) => {
    requestVersions.delete(sessionId);
    refreshVersions.delete(sessionId);
    set((state) => {
      const sessions = { ...state.sessions };
      delete sessions[sessionId];
      return { sessions };
    });
  },
}));
