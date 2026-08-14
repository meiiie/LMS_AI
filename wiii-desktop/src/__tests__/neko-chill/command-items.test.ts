import { describe, expect, it } from "vitest";
import {
  buildNekoCommandItems,
  filterNekoCommandItems,
} from "@/neko-chill/command-items";
import type { NekoSession } from "@/neko-chill/stores/neko-session-store";

function session(index: number, overrides: Partial<NekoSession> = {}): NekoSession {
  return {
    id: `session-${index}`,
    agentId: "neko",
    agentName: "Neko Core",
    title: `Phiên ${index}`,
    createdAt: index,
    updatedAt: index,
    workspace: { path: `C:/work/project-${index % 7}`, name: `Project ${index % 7}` },
    launchProfile: null,
    controls: [],
    commands: [],
    pendingControlId: null,
    lastActivityAt: index,
    status: "exited",
    messages: [],
    events: [],
    runtime: null,
    pendingPermission: null,
    resolvingPermissionId: null,
    cancelPending: false,
    deletePending: false,
    ...overrides,
  };
}

describe("Neko command items", () => {
  it("keeps all 200 persisted sessions reachable and searches transcript text", () => {
    const sessions = Array.from({ length: 200 }, (_, index) => session(index));
    sessions[0] = session(0, {
      title: "Phiên mục tiêu",
      messages: [{ id: "m-0", role: "user", text: "hải đồ sao trời hiếm" }],
    });

    const items = buildNekoCommandItems(sessions, null, true);
    expect(items.filter((item) => item.kind === "session")).toHaveLength(200);
    expect(filterNekoCommandItems(items, "hải đồ sao trời").map((item) => item.label))
      .toEqual(["Phiên mục tiêu"]);
  });

  it("projects honest agent commands and model/profile metadata", () => {
    const active = session(1, {
      launchProfile: {
        id: "reasoning",
        provider: "deepseek",
        model: "deepseek-reasoner",
        active: true,
      },
      commands: [{ name: "memory show", description: "Hiện bộ nhớ đang dùng" }],
    });
    const items = buildNekoCommandItems([active], active, false);

    const command = items.find((item) => item.kind === "command");
    expect(command?.label).toBe("/memory show");
    expect(command && command.kind === "command" ? command.commandText : null)
      .toBe("/memory show");
    expect(filterNekoCommandItems(items, "deepseek-reasoner").map((item) => item.label))
      .toEqual(["Phiên 1"]);
    expect(items.find((item) => item.id === "action:toggle-sidebar")?.label)
      .toBe("Hiện cây dự án và phiên");
  });

  it("searches Vietnamese text without requiring an exact diacritic sequence", () => {
    const items = buildNekoCommandItems([
      session(1, { title: "gãy đi" }),
    ], null, true);

    expect(filterNekoCommandItems(items, "gay").map((item) => item.label))
      .toEqual(["gãy đi"]);
    expect(filterNekoCommandItems(items, "gẫy").map((item) => item.label))
      .toEqual(["gãy đi"]);
  });
});
