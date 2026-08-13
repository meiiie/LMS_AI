import { open } from "@tauri-apps/plugin-dialog";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  chooseWorkspaceFolder,
  isAbsoluteWorkspacePath,
  workspaceFromPath,
  workspaceName,
} from "@/neko-chill/workspace";

vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));

describe("Neko Chill workspace selection", () => {
  beforeEach(() => {
    vi.mocked(open).mockReset();
  });

  it("preserves the exact selected path and derives a cross-platform label", () => {
    expect(workspaceFromPath("E:\\Sach\\Sua\\NekoChill\\wiii")).toEqual({
      path: "E:\\Sach\\Sua\\NekoChill\\wiii",
      name: "wiii",
    });
    expect(workspaceName("/tmp/neko-project/")).toBe("neko-project");
    expect(isAbsoluteWorkspacePath("E:\\work\\neko")).toBe(true);
    expect(isAbsoluteWorkspacePath("\\\\server\\share\\neko")).toBe(true);
    expect(isAbsoluteWorkspacePath("/tmp/neko")).toBe(true);
    expect(isAbsoluteWorkspacePath("relative/neko")).toBe(false);
  });

  it("opens a single-directory native dialog and returns its exact path", async () => {
    vi.mocked(open).mockResolvedValue("C:\\work\\neko" as never);

    await expect(chooseWorkspaceFolder()).resolves.toEqual({
      path: "C:\\work\\neko",
      name: "neko",
    });
    expect(open).toHaveBeenCalledWith({
      directory: true,
      multiple: false,
      title: "Chọn thư mục dự án cho Neko Chill",
    });
  });

  it("preserves current UI state when the folder dialog is cancelled", async () => {
    vi.mocked(open).mockResolvedValue(null);
    await expect(chooseWorkspaceFolder()).resolves.toBeNull();
  });
});
