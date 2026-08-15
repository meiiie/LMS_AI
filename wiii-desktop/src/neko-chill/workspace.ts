/** Workspace selection helpers for the local-only Neko Chill shell. */

export interface WorkspaceRef {
  path: string;
  name: string;
}

/** Accept Windows drive/UNC paths and POSIX roots without touching the filesystem. */
export function isAbsoluteWorkspacePath(path: string): boolean {
  return /^(?:[A-Za-z]:[\\/]|\\\\[^\\]+\\[^\\]+(?:\\|$)|\/)/.test(path);
}

export function workspaceName(path: string): string {
  const parts = path.replace(/[\\/]+$/, "").split(/[\\/]/).filter(Boolean);
  return parts.length ? parts[parts.length - 1] : path;
}

export function workspaceFromPath(path: string): WorkspaceRef {
  return { path, name: workspaceName(path) };
}

/** Opens Tauri's native directory chooser. Browser/test environments return null. */
export async function chooseWorkspaceFolder(): Promise<WorkspaceRef | null> {
  try {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const selected = await open({
      directory: true,
      multiple: false,
      title: "Chọn thư mục dự án cho Neko Chill",
    });
    return typeof selected === "string" && selected ? workspaceFromPath(selected) : null;
  } catch {
    return null;
  }
}
