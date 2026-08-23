import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

const { saveGraph } = vi.hoisted(() => ({
  saveGraph: vi.fn(async (graph: unknown) => ({
    v: 1,
    updatedAt: new Date().toISOString(),
    graph,
  })),
}));

vi.mock("@/ade/persistence", async () => {
  const actual = await vi.importActual<typeof import("@/ade/persistence")>("@/ade/persistence");
  return {
    ...actual,
    loadAdeWorkSnapshot: vi.fn(async () => null),
    saveAdeWorkGraph: saveGraph,
  };
});

vi.mock("@/neko-chill/workspace", async () => {
  const actual = await vi.importActual<typeof import("@/neko-chill/workspace")>("@/neko-chill/workspace");
  return {
    ...actual,
    chooseWorkspaceFolder: vi.fn(async () => ({
      path: "C:\\src\\wiii",
      name: "Wiii",
    })),
  };
});

vi.mock("@/neko-chill/NekoChillApp", () => ({
  default: ({ taskLaunch, onOpenWork }: {
    taskLaunch?: { title: string; execution: { taskId: string; runId: string } } | null;
    onOpenWork: () => void;
  }) => (
    <div data-testid="mock-neko">
      <span>{taskLaunch ? `Task launch: ${taskLaunch.title}` : "Manual Neko Chill"}</span>
      {taskLaunch ? <span>Run {taskLaunch.execution.runId}</span> : null}
      <button type="button" onClick={onOpenWork}>Về công việc</button>
    </div>
  ),
}));

import WiiiAdeApp from "@/ade/WiiiAdeApp";
import { resetAdeWorkStoreForTests, useAdeWorkStore } from "@/ade/store";
import { useNekoSessionStore } from "@/neko-chill/stores/neko-session-store";

describe("Wiii task-first desktop shell", () => {
  beforeEach(() => {
    saveGraph.mockClear();
    resetAdeWorkStoreForTests();
    useAdeWorkStore.setState({ hydrated: true, hydrating: false, error: null });
    useNekoSessionStore.setState({ sessions: {}, activeSessionId: null, hydrated: true });
  });

  it("opens on Wiii work and keeps manual Neko Chill one action away", () => {
    render(<WiiiAdeApp />);

    expect(screen.getByTestId("work-home")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Công việc" })).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /Công việc mới/i }).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByTestId("open-neko"));
    expect(screen.getByText("Manual Neko Chill")).toBeTruthy();
  });

  it("commits Project, Task and Run before handing execution to Neko", async () => {
    render(<WiiiAdeApp />);

    fireEvent.click(screen.getByTestId("new-task"));
    fireEvent.click(screen.getByTestId("choose-task-workspace"));
    await screen.findByText("C:\\src\\wiii");
    fireEvent.change(screen.getByTestId("task-title"), {
      target: { value: "Activate task-first desktop" },
    });
    fireEvent.click(screen.getByTestId("continue-task"));

    await screen.findByText("Task launch: Activate task-first desktop");
    expect(saveGraph).toHaveBeenCalledTimes(1);
    const graph = useAdeWorkStore.getState().graph;
    expect(graph.tasks).toHaveLength(1);
    expect(graph.runs).toHaveLength(1);
    expect(graph.runs[0]).toMatchObject({
      taskId: graph.tasks[0].id,
      state: "starting",
    });
    expect(screen.getByText(`Run ${graph.runs[0].id}`)).toBeTruthy();
  });
});
