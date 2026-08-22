/**
 * Dependency-free Wiii ADE work ontology.
 *
 * These records describe product/work identity, not provider conversation
 * state. Keep them JSON-compatible so the same contract can later cross the
 * Neko Control boundary or be mapped to SQLite without UI dependencies.
 */

export interface AdeProject {
  id: string;
  name: string;
  createdAt?: string;
  updatedAt?: string;
}

export interface AdeWorkspace {
  id: string;
  projectId: string;
  kind: "local" | "git" | "remote";
  roots: string[];
}

export type AdeTaskState =
  | "draft"
  | "ready"
  | "running"
  | "blocked"
  | "review"
  | "completed"
  | "cancelled";

export interface AdeTask {
  id: string;
  projectId: string;
  title: string;
  description?: string;
  state: AdeTaskState;
}

export interface AdeSpec {
  id: string;
  taskId: string;
  revision: number;
  requirements: string[];
  constraints: string[];
  acceptanceCriteria: string[];
}

export type AdeRunState =
  | "queued"
  | "starting"
  | "running"
  | "waiting"
  | "verifying"
  | "review"
  | "completed"
  | "failed"
  | "cancelled"
  | "unknown_outcome";

export type AdeRunStrategy =
  | "single"
  | "best_of_n"
  | "specialist"
  | "writer_reviewer"
  | "plan_implement_verify"
  | "provider_native";

export interface AdeRun {
  id: string;
  taskId: string;
  environmentId: string;
  state: AdeRunState;
  strategy: AdeRunStrategy;
}

export type AdeAgentRole =
  | "primary"
  | "planner"
  | "implementer"
  | "reviewer"
  | "specialist"
  | "subagent";

export interface AdeAgentSession {
  id: string;
  runId: string;
  providerId: string;
  /** Opaque provider-owned identity; never used as Task or Run identity. */
  providerSessionId: string | null;
  role: AdeAgentRole;
}

export type AdeEnvironmentKind =
  | "local_workspace"
  | "worktree"
  | "wsl"
  | "ssh"
  | "container"
  | "wiii_cloud"
  | "external_cloud";

export interface AdeEnvironment {
  id: string;
  projectId: string;
  workspaceId?: string;
  kind: AdeEnvironmentKind;
  state: "preparing" | "ready" | "busy" | "stopped" | "failed";
}

export interface AdeArtifact {
  id: string;
  runId: string;
  kind: "diff" | "log" | "report" | "screenshot" | "video" | "package" | "pr" | "other";
  uri: string;
  mediaType?: string;
  sha256?: string;
  byteSize?: number;
}

export interface AdeEvidence {
  id: string;
  runId: string;
  kind: "test" | "build" | "lint" | "typecheck" | "security" | "review" | "manual";
  outcome: "passed" | "failed" | "warning" | "not_run";
  summary: string;
  command?: string;
  artifactIds?: string[];
}

export interface AdeApproval {
  id: string;
  runId: string;
  agentSessionId?: string;
  request: string;
  risk: "low" | "medium" | "high" | "critical";
  state: "pending" | "approved" | "rejected" | "expired" | "cancelled";
}

export type AdeAttentionReason =
  | "approval"
  | "question"
  | "authentication"
  | "test_failure"
  | "ci_failure"
  | "conflict"
  | "stalled"
  | "budget"
  | "review_ready"
  | "unknown_outcome";

export interface AdeAttentionItem {
  id: string;
  projectId: string;
  taskId: string;
  runId?: string;
  agentSessionId?: string;
  reason: AdeAttentionReason;
  state: "open" | "resolved" | "dismissed";
}

export interface AdeGraph {
  projects: AdeProject[];
  workspaces: AdeWorkspace[];
  tasks: AdeTask[];
  specs: AdeSpec[];
  runs: AdeRun[];
  agentSessions: AdeAgentSession[];
  environments: AdeEnvironment[];
  artifacts: AdeArtifact[];
  evidence: AdeEvidence[];
  approvals: AdeApproval[];
  attentionItems: AdeAttentionItem[];
}

export type AdeGraphDiagnosticCode =
  | "duplicate_id"
  | "missing_project"
  | "missing_workspace"
  | "cross_project_workspace"
  | "missing_task"
  | "missing_environment"
  | "cross_project_environment"
  | "missing_run"
  | "missing_agent_session"
  | "missing_artifact"
  | "cross_run_artifact"
  | "inconsistent_approval_reference"
  | "inconsistent_attention_reference";

export interface AdeGraphDiagnostic {
  code: AdeGraphDiagnosticCode;
  entityKind: string;
  entityId: string;
  field: string;
  referenceId?: string;
}

function indexById<T extends { id: string }>(
  kind: string,
  values: T[],
  diagnostics: AdeGraphDiagnostic[],
): Map<string, T> {
  const index = new Map<string, T>();
  for (const value of values) {
    if (index.has(value.id)) {
      diagnostics.push({
        code: "duplicate_id",
        entityKind: kind,
        entityId: value.id,
        field: "id",
        referenceId: value.id,
      });
      continue;
    }
    index.set(value.id, value);
  }
  return index;
}

function missing(
  diagnostics: AdeGraphDiagnostic[],
  code: AdeGraphDiagnosticCode,
  entityKind: string,
  entityId: string,
  field: string,
  referenceId: string,
): void {
  diagnostics.push({ code, entityKind, entityId, field, referenceId });
}

/** Validate references without mutating or guessing repairs for the graph. */
export function validateAdeGraph(graph: AdeGraph): AdeGraphDiagnostic[] {
  const diagnostics: AdeGraphDiagnostic[] = [];
  const projects = indexById("project", graph.projects, diagnostics);
  const workspaces = indexById("workspace", graph.workspaces, diagnostics);
  const tasks = indexById("task", graph.tasks, diagnostics);
  indexById("spec", graph.specs, diagnostics);
  const environments = indexById("environment", graph.environments, diagnostics);
  const runs = indexById("run", graph.runs, diagnostics);
  const sessions = indexById("agent_session", graph.agentSessions, diagnostics);
  const artifacts = indexById("artifact", graph.artifacts, diagnostics);
  indexById("evidence", graph.evidence, diagnostics);
  indexById("approval", graph.approvals, diagnostics);
  indexById("attention_item", graph.attentionItems, diagnostics);

  for (const workspace of graph.workspaces) {
    if (!projects.has(workspace.projectId)) {
      missing(diagnostics, "missing_project", "workspace", workspace.id, "projectId", workspace.projectId);
    }
  }
  for (const task of graph.tasks) {
    if (!projects.has(task.projectId)) {
      missing(diagnostics, "missing_project", "task", task.id, "projectId", task.projectId);
    }
  }
  for (const spec of graph.specs) {
    if (!tasks.has(spec.taskId)) {
      missing(diagnostics, "missing_task", "spec", spec.id, "taskId", spec.taskId);
    }
  }
  for (const environment of graph.environments) {
    if (!projects.has(environment.projectId)) {
      missing(diagnostics, "missing_project", "environment", environment.id, "projectId", environment.projectId);
    }
    if (environment.workspaceId && !workspaces.has(environment.workspaceId)) {
      missing(diagnostics, "missing_workspace", "environment", environment.id, "workspaceId", environment.workspaceId);
    } else if (
      environment.workspaceId &&
      workspaces.get(environment.workspaceId)?.projectId !== environment.projectId
    ) {
      missing(
        diagnostics,
        "cross_project_workspace",
        "environment",
        environment.id,
        "workspaceId",
        environment.workspaceId,
      );
    }
  }
  for (const run of graph.runs) {
    const task = tasks.get(run.taskId);
    const environment = environments.get(run.environmentId);
    if (!task) missing(diagnostics, "missing_task", "run", run.id, "taskId", run.taskId);
    if (!environment) {
      missing(diagnostics, "missing_environment", "run", run.id, "environmentId", run.environmentId);
    } else if (task && environment.projectId !== task.projectId) {
      missing(
        diagnostics,
        "cross_project_environment",
        "run",
        run.id,
        "environmentId",
        run.environmentId,
      );
    }
  }
  for (const session of graph.agentSessions) {
    if (!runs.has(session.runId)) {
      missing(diagnostics, "missing_run", "agent_session", session.id, "runId", session.runId);
    }
  }
  for (const artifact of graph.artifacts) {
    if (!runs.has(artifact.runId)) {
      missing(diagnostics, "missing_run", "artifact", artifact.id, "runId", artifact.runId);
    }
  }
  for (const item of graph.evidence) {
    if (!runs.has(item.runId)) {
      missing(diagnostics, "missing_run", "evidence", item.id, "runId", item.runId);
    }
    for (const artifactId of item.artifactIds ?? []) {
      const artifact = artifacts.get(artifactId);
      if (!artifact) {
        missing(diagnostics, "missing_artifact", "evidence", item.id, "artifactIds", artifactId);
      } else if (artifact.runId !== item.runId) {
        missing(diagnostics, "cross_run_artifact", "evidence", item.id, "artifactIds", artifactId);
      }
    }
  }
  for (const approval of graph.approvals) {
    if (!runs.has(approval.runId)) {
      missing(diagnostics, "missing_run", "approval", approval.id, "runId", approval.runId);
    }
    if (approval.agentSessionId) {
      const session = sessions.get(approval.agentSessionId);
      if (!session) {
        missing(
          diagnostics,
          "missing_agent_session",
          "approval",
          approval.id,
          "agentSessionId",
          approval.agentSessionId,
        );
      } else if (session.runId !== approval.runId) {
        missing(
          diagnostics,
          "inconsistent_approval_reference",
          "approval",
          approval.id,
          "agentSessionId",
          approval.agentSessionId,
        );
      }
    }
  }
  for (const item of graph.attentionItems) {
    const task = tasks.get(item.taskId);
    const run = item.runId ? runs.get(item.runId) : undefined;
    const session = item.agentSessionId ? sessions.get(item.agentSessionId) : undefined;
    let inconsistent = false;

    if (!projects.has(item.projectId)) {
      missing(diagnostics, "missing_project", "attention_item", item.id, "projectId", item.projectId);
    }
    if (!task) {
      missing(diagnostics, "missing_task", "attention_item", item.id, "taskId", item.taskId);
    } else if (task.projectId !== item.projectId) {
      inconsistent = true;
    }
    if (item.runId && !run) {
      missing(diagnostics, "missing_run", "attention_item", item.id, "runId", item.runId);
    } else if (run && run.taskId !== item.taskId) {
      inconsistent = true;
    }
    if (item.agentSessionId && !session) {
      missing(
        diagnostics,
        "missing_agent_session",
        "attention_item",
        item.id,
        "agentSessionId",
        item.agentSessionId,
      );
    } else if (session && (!item.runId || session.runId !== item.runId)) {
      inconsistent = true;
    }
    if (inconsistent) {
      diagnostics.push({
        code: "inconsistent_attention_reference",
        entityKind: "attention_item",
        entityId: item.id,
        field: "references",
      });
    }
  }

  return diagnostics;
}
