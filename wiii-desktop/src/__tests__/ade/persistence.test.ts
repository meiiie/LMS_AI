import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AdeGraph } from "@/ade/domain";

const storage = new Map<string, unknown>();

vi.mock("@/lib/storage", () => ({
  loadStoreStrict: vi.fn(async (store: string, key: string, fallback: unknown) =>
    structuredClone(storage.get(`${store}:${key}`) ?? fallback)),
  saveStoreStrict: vi.fn(async (store: string, key: string, value: unknown) => {
    storage.set(`${store}:${key}`, structuredClone(value));
  }),
}));

import {
  emptyAdeGraph,
  loadAdeWorkSnapshot,
  parseAdeWorkSnapshot,
  saveAdeWorkGraph,
} from "@/ade/persistence";

function validGraph(): AdeGraph {
  const graph = emptyAdeGraph();
  graph.projects.push({ id: "project-1", name: "Wiii" });
  graph.workspaces.push({
    id: "workspace-1",
    projectId: "project-1",
    kind: "local",
    roots: ["C:\\src\\wiii"],
  });
  graph.tasks.push({
    id: "task-1",
    projectId: "project-1",
    title: "Activate ADE",
    state: "running",
  });
  graph.specs.push({
    id: "spec-1",
    taskId: "task-1",
    revision: 1,
    requirements: ["Task first"],
    constraints: [],
    acceptanceCriteria: ["Visible after reload"],
  });
  graph.environments.push({
    id: "environment-1",
    projectId: "project-1",
    workspaceId: "workspace-1",
    kind: "local_workspace",
    state: "busy",
  });
  graph.runs.push({
    id: "run-1",
    taskId: "task-1",
    environmentId: "environment-1",
    state: "starting",
    strategy: "single",
  });
  return graph;
}

describe("Wiii ADE work persistence", () => {
  beforeEach(() => storage.clear());

  it("round-trips one validated versioned work graph", async () => {
    const graph = validGraph();
    await saveAdeWorkGraph(graph);

    await expect(loadAdeWorkSnapshot()).resolves.toEqual(expect.objectContaining({
      v: 1,
      graph,
    }));
  });

  it("treats a missing snapshot as empty authority without writing defaults", async () => {
    await expect(loadAdeWorkSnapshot()).resolves.toBeNull();
    expect(storage.size).toBe(0);
  });

  it("rejects unsupported or structurally malformed snapshots", () => {
    expect(() => parseAdeWorkSnapshot({
      v: 2,
      updatedAt: new Date().toISOString(),
      graph: emptyAdeGraph(),
    })).toThrow(/schema/);
    expect(() => parseAdeWorkSnapshot({
      v: 1,
      updatedAt: new Date().toISOString(),
      graph: { projects: [] },
    })).toThrow(/schema/);
  });

  it("rejects a structurally valid graph with dangling references", () => {
    const graph = validGraph();
    graph.runs[0].environmentId = "missing";
    expect(() => parseAdeWorkSnapshot({
      v: 1,
      updatedAt: new Date().toISOString(),
      graph,
    })).toThrow(/missing_environment/);
  });

  it("rejects an invalid graph before the storage write barrier", async () => {
    const graph = validGraph();
    graph.runs[0].environmentId = "missing";

    await expect(saveAdeWorkGraph(graph)).rejects.toThrow(/missing_environment/);
    expect(storage.size).toBe(0);
  });
});
