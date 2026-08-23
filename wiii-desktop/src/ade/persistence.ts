import { loadStoreStrict, saveStoreStrict } from "@/lib/storage";
import {
  validateAdeGraph,
  type AdeGraph,
} from "./domain";

const STORE = "wiii-ade-work.json";
const SNAPSHOT_KEY = "snapshot";
const SCHEMA_VERSION = 1 as const;

export interface AdeWorkSnapshot {
  v: typeof SCHEMA_VERSION;
  updatedAt: string;
  graph: AdeGraph;
}

export function emptyAdeGraph(): AdeGraph {
  return {
    projects: [],
    workspaces: [],
    tasks: [],
    specs: [],
    runs: [],
    agentSessions: [],
    environments: [],
    artifacts: [],
    evidence: [],
    approvals: [],
    attentionItems: [],
  };
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function text(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function optionalText(value: unknown): boolean {
  return value === undefined || typeof value === "string";
}

function oneOf(value: unknown, values: readonly string[]): boolean {
  return typeof value === "string" && values.includes(value);
}

function arrayOfRecords(value: unknown, validate: (item: Record<string, unknown>) => boolean): boolean {
  return Array.isArray(value) && value.every((item) => {
    const candidate = record(item);
    return candidate !== null && validate(candidate);
  });
}

function stringArray(value: unknown): boolean {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isAdeGraph(value: unknown): value is AdeGraph {
  const graph = record(value);
  if (!graph) return false;
  return (
    arrayOfRecords(graph.projects, (item) =>
      text(item.id) && text(item.name) && optionalText(item.createdAt) && optionalText(item.updatedAt)) &&
    arrayOfRecords(graph.workspaces, (item) =>
      text(item.id) && text(item.projectId) && oneOf(item.kind, ["local", "git", "remote"]) &&
      stringArray(item.roots)) &&
    arrayOfRecords(graph.tasks, (item) =>
      text(item.id) && text(item.projectId) && text(item.title) && optionalText(item.description) &&
      oneOf(item.state, ["draft", "ready", "running", "blocked", "review", "completed", "cancelled"])) &&
    arrayOfRecords(graph.specs, (item) =>
      text(item.id) && text(item.taskId) && Number.isSafeInteger(item.revision) &&
      (item.revision as number) > 0 && stringArray(item.requirements) &&
      stringArray(item.constraints) && stringArray(item.acceptanceCriteria)) &&
    arrayOfRecords(graph.runs, (item) =>
      text(item.id) && text(item.taskId) && text(item.environmentId) &&
      oneOf(item.state, ["queued", "starting", "running", "waiting", "verifying", "review", "completed", "failed", "cancelled", "unknown_outcome"]) &&
      oneOf(item.strategy, ["single", "best_of_n", "specialist", "writer_reviewer", "plan_implement_verify", "provider_native"])) &&
    arrayOfRecords(graph.agentSessions, (item) =>
      text(item.id) && text(item.runId) && text(item.providerId) &&
      (item.providerSessionId === null || text(item.providerSessionId)) &&
      oneOf(item.role, ["primary", "planner", "implementer", "reviewer", "specialist", "subagent"])) &&
    arrayOfRecords(graph.environments, (item) =>
      text(item.id) && text(item.projectId) && optionalText(item.workspaceId) &&
      oneOf(item.kind, ["local_workspace", "worktree", "wsl", "ssh", "container", "wiii_cloud", "external_cloud"]) &&
      oneOf(item.state, ["preparing", "ready", "busy", "stopped", "failed"])) &&
    arrayOfRecords(graph.artifacts, (item) =>
      text(item.id) && text(item.runId) &&
      oneOf(item.kind, ["diff", "log", "report", "screenshot", "video", "package", "pr", "other"]) &&
      text(item.uri) && optionalText(item.mediaType) && optionalText(item.sha256) &&
      (item.byteSize === undefined || (Number.isSafeInteger(item.byteSize) && (item.byteSize as number) >= 0))) &&
    arrayOfRecords(graph.evidence, (item) =>
      text(item.id) && text(item.runId) &&
      oneOf(item.kind, ["test", "build", "lint", "typecheck", "security", "review", "manual"]) &&
      oneOf(item.outcome, ["passed", "failed", "warning", "not_run"]) && text(item.summary) &&
      optionalText(item.command) && (item.artifactIds === undefined || stringArray(item.artifactIds))) &&
    arrayOfRecords(graph.approvals, (item) =>
      text(item.id) && text(item.runId) && optionalText(item.agentSessionId) && text(item.request) &&
      oneOf(item.risk, ["low", "medium", "high", "critical"]) &&
      oneOf(item.state, ["pending", "approved", "rejected", "expired", "cancelled"])) &&
    arrayOfRecords(graph.attentionItems, (item) =>
      text(item.id) && text(item.projectId) && text(item.taskId) && optionalText(item.runId) &&
      optionalText(item.agentSessionId) &&
      oneOf(item.reason, ["approval", "question", "authentication", "test_failure", "ci_failure", "conflict", "stalled", "budget", "review_ready", "unknown_outcome"]) &&
      oneOf(item.state, ["open", "resolved", "dismissed"]))
  );
}

export function parseAdeWorkSnapshot(value: unknown): AdeWorkSnapshot | null {
  if (value === undefined) return null;
  const snapshot = record(value);
  if (
    !snapshot ||
    snapshot.v !== SCHEMA_VERSION ||
    !text(snapshot.updatedAt) ||
    Number.isNaN(Date.parse(snapshot.updatedAt)) ||
    !isAdeGraph(snapshot.graph)
  ) {
    throw new Error("Dữ liệu công việc Wiii có schema không hợp lệ hoặc chưa được hỗ trợ.");
  }
  const graph = snapshot.graph;
  const diagnostics = validateAdeGraph(graph);
  if (diagnostics.length > 0) {
    const first = diagnostics[0];
    throw new Error(
      `Dữ liệu công việc Wiii không nhất quán: ${first.code} tại ${first.entityKind}/${first.entityId}.`,
    );
  }
  return snapshot as unknown as AdeWorkSnapshot;
}

export async function loadAdeWorkSnapshot(): Promise<AdeWorkSnapshot | null> {
  return parseAdeWorkSnapshot(
    await loadStoreStrict<unknown>(STORE, SNAPSHOT_KEY, undefined),
  );
}

export async function saveAdeWorkGraph(graph: AdeGraph): Promise<AdeWorkSnapshot> {
  const diagnostics = validateAdeGraph(graph);
  if (diagnostics.length > 0) {
    const first = diagnostics[0];
    throw new Error(
      `Không thể lưu công việc Wiii không nhất quán: ${first.code} tại ${first.entityKind}/${first.entityId}.`,
    );
  }
  const snapshot: AdeWorkSnapshot = {
    v: SCHEMA_VERSION,
    updatedAt: new Date().toISOString(),
    graph,
  };
  await saveStoreStrict(STORE, SNAPSHOT_KEY, snapshot);
  return snapshot;
}
