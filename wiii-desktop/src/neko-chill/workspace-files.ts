import { invoke } from "@tauri-apps/api/core";

export interface WorkspaceEntry {
  path: string;
  name: string;
  size: number;
  modifiedAt: number | null;
  language: string;
}

export interface WorkspaceListing {
  entries: WorkspaceEntry[];
  truncated: boolean;
}

export interface WorkspaceFile {
  path: string;
  name: string;
  kind: "text" | "image" | "pdf";
  language: string;
  mimeType: string;
  size: number;
  modifiedAt: number | null;
  content: string | null;
  dataUrl: string | null;
}

export interface WorkspaceChange {
  path: string;
  status: "added" | "modified" | "deleted" | "renamed" | "untracked";
  staged: boolean;
}

export interface WorkspaceChanges {
  isGit: boolean;
  changes: WorkspaceChange[];
}

export interface WorkspaceDiff {
  path: string;
  status: WorkspaceChange["status"];
  language: string;
  original: string;
  modified: string;
  binary: boolean;
}

export function listWorkspaceFiles(workspace: string): Promise<WorkspaceListing> {
  return invoke("neko_list_workspace_files", { workspace });
}

export function readWorkspaceFile(workspace: string, path: string): Promise<WorkspaceFile> {
  return invoke("neko_read_workspace_file", { workspace, path });
}

export function listWorkspaceChanges(workspace: string): Promise<WorkspaceChanges> {
  return invoke("neko_workspace_changes", { workspace });
}

export function readWorkspaceDiff(workspace: string, path: string): Promise<WorkspaceDiff> {
  return invoke("neko_workspace_diff", { workspace, path });
}
