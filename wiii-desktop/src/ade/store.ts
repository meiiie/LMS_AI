import { create } from "zustand";
import { immer } from "zustand/middleware/immer";
import { v4 as uuidv4 } from "uuid";
import type { NekoExecutionBinding } from "@/neko/control-client";
import type { WorkspaceRef } from "@/neko-chill/workspace";
import {
  type AdeAgentSession,
  type AdeGraph,
  type AdeRunState,
} from "./domain";
import { validateAdeRunTransition } from "./lifecycle";
import {
  emptyAdeGraph,
  loadAdeWorkSnapshot,
  saveAdeWorkGraph,
} from "./persistence";

export interface CreateTaskRunInput {
  workspace: WorkspaceRef;
  title: string;
  description?: string;
  acceptanceCriteria?: string[];
}

export interface CreatedTaskRun {
  projectId: string;
  workspaceId: string;
  taskId: string;
  specId: string;
  environmentId: string;
  runId: string;
  execution: NekoExecutionBinding;
}

export interface AttachAgentSessionInput {
  id: string;
  runId: string;
  providerId: string;
  providerSessionId: string | null;
}

interface AdeWorkState {
  graph: AdeGraph;
  hydrated: boolean;
  hydrating: boolean;
  error: string | null;
  hydrate: () => Promise<void>;
  createTaskRun: (input: CreateTaskRunInput) => Promise<CreatedTaskRun>;
  attachAgentSession: (input: AttachAgentSessionInput) => Promise<AdeAgentSession>;
  transitionRun: (runId: string, state: AdeRunState) => Promise<void>;
}

let mutationTail: Promise<void> = Promise.resolve();

function serializeMutation<T>(operation: () => Promise<T>): Promise<T> {
  const result = mutationTail.catch(() => {}).then(operation);
  mutationTail = result.then(() => {}, () => {});
  return result;
}

function cloneGraph(graph: AdeGraph): AdeGraph {
  return structuredClone(graph);
}

function normalizedRoot(path: string): string {
  const windows = /^(?:[A-Za-z]:[\\/]|\\\\)/.test(path);
  const normalized = windows ? path.replaceAll("/", "\\") : path;
  const withoutTrailing = normalized.length > 1 ? normalized.replace(/[\\/]+$/, "") : normalized;
  return windows ? withoutTrailing.toLocaleLowerCase("en-US") : withoutTrailing;
}

function taskStateForRun(state: AdeRunState) {
  if (state === "completed") return "completed" as const;
  if (state === "review") return "review" as const;
  if (state === "cancelled") return "cancelled" as const;
  if (state === "failed" || state === "unknown_outcome") return "blocked" as const;
  return "running" as const;
}

export const useAdeWorkStore = create<AdeWorkState>()(
  immer((set, get) => ({
    graph: emptyAdeGraph(),
    hydrated: false,
    hydrating: false,
    error: null,

    hydrate: async () => serializeMutation(async () => {
      if (get().hydrated || get().hydrating) return;
      set((state) => {
        state.hydrating = true;
        state.error = null;
      });
      try {
        const snapshot = await loadAdeWorkSnapshot();
        set((state) => {
          state.graph = snapshot?.graph ?? emptyAdeGraph();
          state.hydrated = true;
          state.hydrating = false;
        });
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        set((state) => {
          state.hydrating = false;
          state.error = message;
        });
        throw error;
      }
    }),

    createTaskRun: async (input) => serializeMutation(async () => {
      const title = input.title.trim();
      if (!title) throw new Error("Hãy mô tả công việc Wiii cần hoàn thành.");
      if (!input.workspace.path || !input.workspace.name) {
        throw new Error("Hãy chọn một thư mục dự án trước khi tạo công việc.");
      }
      const graph = cloneGraph(get().graph);
      const rootKey = normalizedRoot(input.workspace.path);
      let workspace = graph.workspaces.find((item) =>
        item.roots.some((root) => normalizedRoot(root) === rootKey));
      let project = workspace
        ? graph.projects.find((item) => item.id === workspace?.projectId)
        : undefined;
      const now = new Date().toISOString();
      if (!workspace || !project) {
        project = {
          id: uuidv4(),
          name: input.workspace.name,
          createdAt: now,
          updatedAt: now,
        };
        workspace = {
          id: uuidv4(),
          projectId: project.id,
          kind: "local",
          roots: [input.workspace.path],
        };
        graph.projects.push(project);
        graph.workspaces.push(workspace);
      } else {
        project.updatedAt = now;
      }

      const taskId = uuidv4();
      const specId = uuidv4();
      const environmentId = uuidv4();
      const runId = uuidv4();
      graph.tasks.push({
        id: taskId,
        projectId: project.id,
        title,
        description: input.description?.trim() || undefined,
        state: "running",
      });
      graph.specs.push({
        id: specId,
        taskId,
        revision: 1,
        requirements: [title],
        constraints: [],
        acceptanceCriteria: (input.acceptanceCriteria ?? [])
          .map((criterion) => criterion.trim())
          .filter(Boolean),
      });
      graph.environments.push({
        id: environmentId,
        projectId: project.id,
        workspaceId: workspace.id,
        kind: "local_workspace",
        state: "busy",
      });
      graph.runs.push({
        id: runId,
        taskId,
        environmentId,
        state: "starting",
        strategy: "single",
      });

      await saveAdeWorkGraph(graph);
      set((state) => {
        state.graph = graph;
        state.error = null;
      });
      return {
        projectId: project.id,
        workspaceId: workspace.id,
        taskId,
        specId,
        environmentId,
        runId,
        execution: { taskId, runId, environmentId },
      };
    }),

    attachAgentSession: async (input) => serializeMutation(async () => {
      const graph = cloneGraph(get().graph);
      const run = graph.runs.find((item) => item.id === input.runId);
      if (!run) {
        throw new Error(`Không tìm thấy Run ${input.runId} để gắn agent.`);
      }
      const existing = graph.agentSessions.find((session) => session.id === input.id);
      if (existing && existing.runId !== input.runId) {
        throw new Error(`AgentSession ${input.id} đã thuộc một Run khác.`);
      }
      const transition = validateAdeRunTransition(run.state, "running");
      if (transition) {
        throw new Error(`Không thể gắn agent khi Run đang ở trạng thái ${run.state}.`);
      }
      const session: AdeAgentSession = existing ?? {
          id: input.id,
          runId: input.runId,
          providerId: input.providerId,
          providerSessionId: input.providerSessionId,
          role: "primary",
        };
      if (!existing) graph.agentSessions.push(session);
      run.state = "running";
      const task = graph.tasks.find((item) => item.id === run.taskId);
      if (task) task.state = "running";
      const environment = graph.environments.find((item) => item.id === run.environmentId);
      if (environment) environment.state = "busy";
      if (!existing || get().graph.runs.find((item) => item.id === input.runId)?.state !== "running") {
        await saveAdeWorkGraph(graph);
      }
      set((state) => {
        state.graph = graph;
        state.error = null;
      });
      return session;
    }),

    transitionRun: async (runId, nextState) => serializeMutation(async () => {
      const graph = cloneGraph(get().graph);
      const run = graph.runs.find((item) => item.id === runId);
      if (!run) throw new Error(`Không tìm thấy Run ${runId}.`);
      const diagnostic = validateAdeRunTransition(run.state, nextState);
      if (diagnostic) {
        throw new Error(`Không thể chuyển Run từ ${diagnostic.from} sang ${diagnostic.to}.`);
      }
      run.state = nextState;
      const task = graph.tasks.find((item) => item.id === run.taskId);
      if (task) task.state = taskStateForRun(nextState);
      const environment = graph.environments.find((item) => item.id === run.environmentId);
      if (environment) {
        environment.state = ["completed", "failed", "cancelled", "unknown_outcome"].includes(nextState)
          ? "stopped"
          : "busy";
      }
      await saveAdeWorkGraph(graph);
      set((state) => {
        state.graph = graph;
        state.error = null;
      });
    }),
  })),
);

export function resetAdeWorkStoreForTests(): void {
  mutationTail = Promise.resolve();
  useAdeWorkStore.setState({
    graph: emptyAdeGraph(),
    hydrated: false,
    hydrating: false,
    error: null,
  });
}
