import { describe, expect, it } from "vitest";
import {
  validateAdeGraph,
  type AdeGraph,
} from "@/ade/domain";

function graph(): AdeGraph {
  return {
    projects: [{ id: "project-wiii", name: "Wiii" }],
    workspaces: [{
      id: "workspace-main",
      projectId: "project-wiii",
      kind: "local",
      roots: ["C:/src/wiii"],
    }],
    tasks: [{
      id: "task-auth",
      projectId: "project-wiii",
      title: "Refactor authentication",
      state: "running",
    }],
    specs: [{
      id: "spec-auth-v1",
      taskId: "task-auth",
      revision: 1,
      requirements: ["Preserve existing login behavior"],
      constraints: [],
      acceptanceCriteria: ["Authentication tests pass"],
    }],
    environments: [
      {
        id: "env-codex",
        projectId: "project-wiii",
        workspaceId: "workspace-main",
        kind: "worktree",
        state: "ready",
      },
      {
        id: "env-claude",
        projectId: "project-wiii",
        workspaceId: "workspace-main",
        kind: "worktree",
        state: "ready",
      },
    ],
    runs: [
      {
        id: "run-codex",
        taskId: "task-auth",
        environmentId: "env-codex",
        state: "running",
        strategy: "best_of_n",
      },
      {
        id: "run-claude",
        taskId: "task-auth",
        environmentId: "env-claude",
        state: "running",
        strategy: "best_of_n",
      },
    ],
    agentSessions: [
      {
        id: "session-codex",
        runId: "run-codex",
        providerId: "codex",
        providerSessionId: "thread-123",
        role: "primary",
      },
      {
        id: "session-claude",
        runId: "run-claude",
        providerId: "claude",
        providerSessionId: "session-456",
        role: "primary",
      },
      {
        id: "session-review",
        runId: "run-codex",
        providerId: "neko",
        providerSessionId: null,
        role: "reviewer",
      },
    ],
    artifacts: [],
    evidence: [],
    approvals: [],
    attentionItems: [],
  };
}

describe("Wiii ADE work graph", () => {
  it("keeps one task identity across multiple runs and provider sessions", () => {
    const value = graph();

    expect(validateAdeGraph(value)).toEqual([]);
    expect(value.runs).toHaveLength(2);
    expect(new Set(value.runs.map((run) => run.taskId))).toEqual(new Set(["task-auth"]));
    expect(value.agentSessions).toHaveLength(3);
  });

  it("rejects a run whose environment belongs to another project", () => {
    const value = graph();
    value.projects.push({ id: "project-other", name: "Other" });
    value.environments[0] = {
      ...value.environments[0],
      projectId: "project-other",
      workspaceId: undefined,
    };

    expect(validateAdeGraph(value)).toContainEqual(expect.objectContaining({
      code: "cross_project_environment",
      entityId: "run-codex",
      referenceId: "env-codex",
    }));
  });

  it("reports dangling references without inventing replacement identities", () => {
    const value = graph();
    value.runs[0] = { ...value.runs[0], environmentId: "env-missing" };
    value.agentSessions[0] = { ...value.agentSessions[0], runId: "run-missing" };

    expect(validateAdeGraph(value).map((item) => item.code)).toEqual(expect.arrayContaining([
      "missing_environment",
      "missing_run",
    ]));
  });

  it("requires attention references to describe one consistent work chain", () => {
    const value = graph();
    value.attentionItems.push({
      id: "attention-1",
      projectId: "project-wiii",
      taskId: "task-auth",
      runId: "run-claude",
      agentSessionId: "session-codex",
      reason: "approval",
      state: "open",
    });

    expect(validateAdeGraph(value)).toContainEqual(expect.objectContaining({
      code: "inconsistent_attention_reference",
      entityId: "attention-1",
    }));
  });

  it("keeps workspace and approval references inside their owning project/run", () => {
    const value = graph();
    value.projects.push({ id: "project-other", name: "Other" });
    value.workspaces.push({
      id: "workspace-other",
      projectId: "project-other",
      kind: "local",
      roots: ["C:/src/other"],
    });
    value.environments[0] = {
      ...value.environments[0],
      workspaceId: "workspace-other",
    };
    value.approvals.push({
      id: "approval-1",
      runId: "run-claude",
      agentSessionId: "session-codex",
      request: "Push the branch",
      risk: "high",
      state: "pending",
    });

    expect(validateAdeGraph(value).map((item) => item.code)).toEqual(expect.arrayContaining([
      "cross_project_workspace",
      "inconsistent_approval_reference",
    ]));
  });
});
