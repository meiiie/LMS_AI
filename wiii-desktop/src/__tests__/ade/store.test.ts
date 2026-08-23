import { beforeEach, describe, expect, it, vi } from "vitest";

const saved: unknown[] = [];
let failWrite = false;

vi.mock("@/ade/persistence", async () => {
  const actual = await vi.importActual<typeof import("@/ade/persistence")>("@/ade/persistence");
  return {
    ...actual,
    loadAdeWorkSnapshot: vi.fn(async () => null),
    saveAdeWorkGraph: vi.fn(async (graph: unknown) => {
      if (failWrite) throw new Error("disk unavailable");
      saved.push(structuredClone(graph));
      return { v: 1, updatedAt: new Date().toISOString(), graph };
    }),
  };
});

import { resetAdeWorkStoreForTests, useAdeWorkStore } from "@/ade/store";

describe("Wiii ADE work store", () => {
  beforeEach(async () => {
    failWrite = false;
    saved.length = 0;
    resetAdeWorkStoreForTests();
    await useAdeWorkStore.getState().hydrate();
  });

  it("rejects every mutation until the durable snapshot has been hydrated", async () => {
    resetAdeWorkStoreForTests();
    await expect(useAdeWorkStore.getState().createTaskRun({
      workspace: { name: "Wiii", path: "C:\\src\\wiii" },
      title: "Do not overwrite unread state",
    })).rejects.toThrow(/chưa được nạp/i);
    await expect(useAdeWorkStore.getState().attachAgentSession({
      id: "session-1",
      runId: "run-1",
      providerId: "codex",
      providerSessionId: null,
    })).rejects.toThrow(/chưa được nạp/i);
    await expect(
      useAdeWorkStore.getState().transitionRun("run-1", "failed"),
    ).rejects.toThrow(/chưa được nạp/i);
    expect(saved).toHaveLength(0);
  });

  it("commits the complete Task/Run chain and returns its execution binding", async () => {
    const created = await useAdeWorkStore.getState().createTaskRun({
      workspace: { name: "Wiii", path: "C:\\src\\wiii" },
      title: "Activate task-first desktop",
      acceptanceCriteria: ["Task survives reload"],
    });

    expect(saved).toHaveLength(1);
    const graph = useAdeWorkStore.getState().graph;
    expect(graph.projects).toHaveLength(1);
    expect(graph.tasks[0]).toMatchObject({ id: created.taskId, state: "running" });
    expect(graph.runs[0]).toMatchObject({ id: created.runId, state: "starting" });
    expect(created.execution).toEqual({
      taskId: created.taskId,
      runId: created.runId,
      environmentId: created.environmentId,
    });
  });

  it("does not publish in-memory work when the durability barrier fails", async () => {
    failWrite = true;
    await expect(useAdeWorkStore.getState().createTaskRun({
      workspace: { name: "Wiii", path: "C:\\src\\wiii" },
      title: "Must be durable",
    })).rejects.toThrow("disk unavailable");
    expect(useAdeWorkStore.getState().graph.tasks).toEqual([]);
  });

  it("reuses a Windows workspace identity but never merges task identities", async () => {
    const first = await useAdeWorkStore.getState().createTaskRun({
      workspace: { name: "Wiii", path: "C:\\src\\wiii\\" },
      title: "Same title",
    });
    const second = await useAdeWorkStore.getState().createTaskRun({
      workspace: { name: "Wiii", path: "c:/SRC/wiii" },
      title: "Same title",
    });

    expect(first.projectId).toBe(second.projectId);
    expect(first.workspaceId).toBe(second.workspaceId);
    expect(first.taskId).not.toBe(second.taskId);
    expect(first.runId).not.toBe(second.runId);
  });

  it("records provider identity then validates run lifecycle separately", async () => {
    const created = await useAdeWorkStore.getState().createTaskRun({
      workspace: { name: "Wiii", path: "C:\\src\\wiii" },
      title: "Bind Codex",
    });
    await useAdeWorkStore.getState().attachAgentSession({
      id: "native-agent-session",
      runId: created.runId,
      providerId: "codex",
      providerSessionId: "thread-1",
    });
    expect(useAdeWorkStore.getState().graph.agentSessions[0]).toMatchObject({
      runId: created.runId,
      providerId: "codex",
      providerSessionId: "thread-1",
    });
    expect(saved).toHaveLength(2);
    expect(useAdeWorkStore.getState().graph.runs[0].state).toBe("running");

    await useAdeWorkStore.getState().attachAgentSession({
      id: "native-agent-session",
      runId: created.runId,
      providerId: "codex",
      providerSessionId: "thread-2",
    });
    expect(saved).toHaveLength(3);
    expect(useAdeWorkStore.getState().graph.agentSessions[0]).toMatchObject({
      providerId: "codex",
      providerSessionId: "thread-2",
    });
    await expect(
      useAdeWorkStore.getState().transitionRun(created.runId, "completed"),
    ).rejects.toThrow(/không thể chuyển/i);
  });
});
