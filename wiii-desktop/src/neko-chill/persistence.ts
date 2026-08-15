/**
 * Local session persistence (T501, FR-008) — tauri plugin-store via the
 * shared storage wrapper (localStorage fallback in browser dev).
 *
 * Layout (versioned for future migration):
 *   neko-chill-sessions.json / "session-ids"  → string[]
 *   neko-chill-sessions.json / "index"        → SessionIndexEntry[] cache
 *   neko-chill-sessions.json / "session:{id}" → self-contained snapshot
 *
 * Writes are debounced per session so token streaming never causes a
 * full-store rewrite per delta (spec edge case: long transcripts).
 */
import {
  deleteStoreStrict,
  loadStore,
  loadStoreStrict,
  saveStore,
  saveStoreStrict,
} from "@/lib/storage";
import type { ContentBlock } from "@/api/types";
import type { NekoMessage, NekoSession } from "./stores/neko-session-store";
import type { DriverCommand, DriverConfigOption } from "./drivers/types";
import type { AgentLaunchProfile } from "./stores/neko-agent-store";
import { isAbsoluteWorkspacePath, type WorkspaceRef } from "./workspace";
import { isNekoSessionEvent, type NekoSessionEvent } from "./session-events";

const STORE = "neko-chill-sessions.json";
const INDEX_KEY = "index";
const SESSION_IDS_KEY = "session-ids";
const INDEX_SCHEMA_VERSION = 2;
const SCHEMA_VERSION = 2;
const DEBOUNCE_MS = 400;

export interface SessionIndexEntry {
  v?: number;
  id: string;
  agentId: string;
  agentName: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  workspace?: WorkspaceRef | null;
  launchProfile?: AgentLaunchProfile | null;
  /** Provider-owned durable ACP id used to resume across process restarts. */
  backendSessionId?: string | null;
  controls?: DriverConfigOption[];
  commands?: DriverCommand[];
}

interface PersistedTranscript {
  v: number;
  messages: NekoMessage[];
  events?: NekoSessionEvent[];
  /** Monotonic allocator state; may exceed the surviving tail after rollback. */
  eventHighWaterMark?: number;
  /** Authoritative materialized metadata; index is only a discovery cache. */
  entry?: SessionIndexEntry;
}

export interface LoadedSessionSnapshot {
  messages: NekoMessage[];
  events: NekoSessionEvent[];
  eventHighWaterMark: number;
  /** v1/corrupt event data needs a deterministic audit-log backfill. */
  needsEventMigration: boolean;
}

const timers = new Map<string, ReturnType<typeof setTimeout>>();
const writeChains = new Map<string, Promise<void>>();
const deleteChains = new Map<string, Promise<void>>();
const publishedIds = new Set<string>();
let catalogWriteChain: Promise<void> = Promise.resolve();
let indexWriteChain: Promise<void> = Promise.resolve();

function isDriverConfigChoice(value: unknown): boolean {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const choice = value as Record<string, unknown>;
  return (
    typeof choice.value === "string" &&
    typeof choice.label === "string" &&
    (choice.description === undefined || typeof choice.description === "string")
  );
}

function isDriverConfigOption(value: unknown): value is DriverConfigOption {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const option = value as Record<string, unknown>;
  return (
    typeof option.id === "string" &&
    typeof option.label === "string" &&
    (option.description === undefined || typeof option.description === "string") &&
    ["mode", "model", "model_config", "thought_level", "other"].includes(
      option.category as string,
    ) &&
    (option.kind === "select" || option.kind === "boolean") &&
    (typeof option.currentValue === "string" || typeof option.currentValue === "boolean") &&
    (option.choices === undefined || (
      Array.isArray(option.choices) && option.choices.every(isDriverConfigChoice)
    ))
  );
}

function isDriverCommand(value: unknown): value is DriverCommand {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const command = value as Record<string, unknown>;
  return (
    typeof command.name === "string" &&
    typeof command.description === "string" &&
    (command.inputHint === undefined || typeof command.inputHint === "string")
  );
}

function isWorkspaceRef(value: unknown): value is WorkspaceRef {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const workspace = value as Record<string, unknown>;
  return (
    typeof workspace.path === "string" &&
    isAbsoluteWorkspacePath(workspace.path) &&
    typeof workspace.name === "string" &&
    workspace.name.length > 0
  );
}

function isLaunchProfile(value: unknown): value is AgentLaunchProfile {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const profile = value as Record<string, unknown>;
  return (
    typeof profile.id === "string" &&
    typeof profile.provider === "string" &&
    (profile.model === null || typeof profile.model === "string") &&
    typeof profile.active === "boolean"
  );
}

function isSessionIndexEntry(value: unknown, expectedId?: string): value is SessionIndexEntry {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const entry = value as Partial<SessionIndexEntry>;
  return (
    (entry.v === undefined || entry.v === INDEX_SCHEMA_VERSION) &&
    typeof entry.id === "string" &&
    (!expectedId || entry.id === expectedId) &&
    typeof entry.agentId === "string" &&
    typeof entry.agentName === "string" &&
    typeof entry.title === "string" &&
    typeof entry.createdAt === "number" &&
    Number.isFinite(entry.createdAt) &&
    typeof entry.updatedAt === "number" &&
    Number.isFinite(entry.updatedAt) &&
    (entry.workspace === undefined || entry.workspace === null || isWorkspaceRef(entry.workspace)) &&
    (entry.launchProfile === undefined ||
      entry.launchProfile === null ||
      isLaunchProfile(entry.launchProfile)) &&
    (entry.backendSessionId === undefined ||
      entry.backendSessionId === null ||
      typeof entry.backendSessionId === "string") &&
    (entry.controls === undefined || (
      Array.isArray(entry.controls) && entry.controls.every(isDriverConfigOption)
    )) &&
    (entry.commands === undefined || (
      Array.isArray(entry.commands) && entry.commands.every(isDriverCommand)
    ))
  );
}

function parseSessionIds(value: unknown): string[] {
  if (
    !Array.isArray(value) ||
    !value.every((item) => typeof item === "string" && item.length > 0)
  ) {
    throw new Error("Danh mục phiên Neko Chill có schema không hợp lệ.");
  }
  return [...new Set(value)];
}

function isToolCall(value: unknown): boolean {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const tool = value as Record<string, unknown>;
  return (
    typeof tool.id === "string" &&
    typeof tool.name === "string" &&
    (tool.result === undefined || typeof tool.result === "string") &&
    (tool.node === undefined || typeof tool.node === "string") &&
    (tool.args === undefined || (
      tool.args !== null && typeof tool.args === "object" && !Array.isArray(tool.args)
    ))
  );
}

function isNekoContentBlock(value: unknown): value is ContentBlock {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const block = value as Record<string, unknown>;
  if (typeof block.id !== "string") return false;
  if (block.type === "answer") return typeof block.content === "string";
  if (block.type === "thinking") {
    return (
      typeof block.content === "string" &&
      Array.isArray(block.toolCalls) &&
      block.toolCalls.every(isToolCall)
    );
  }
  if (block.type === "tool_execution") {
    return (
      (block.status === "pending" || block.status === "completed") &&
      isToolCall(block.tool)
    );
  }
  return false;
}

function isPersistedMessage(value: unknown): value is NekoMessage {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const message = value as Partial<NekoMessage>;
  if (
    typeof message.id !== "string" ||
    (message.role !== "user" && message.role !== "assistant") ||
    (message.text !== undefined && typeof message.text !== "string") ||
    (message.blocks !== undefined && (
      !Array.isArray(message.blocks) || !message.blocks.every(isNekoContentBlock)
    ))
  ) {
    return false;
  }
  return message.role === "user"
    ? typeof message.text === "string"
    : Array.isArray(message.blocks) || typeof message.text === "string";
}

function parsePersistedTranscript(
  value: unknown,
  sessionId: string,
): PersistedTranscript | null {
  if (value === undefined) return null;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`Snapshot phiên ${sessionId} có schema không hợp lệ.`);
  }
  const transcript = value as Partial<PersistedTranscript>;
  if (
    (transcript.v !== 1 && transcript.v !== SCHEMA_VERSION) ||
    !Array.isArray(transcript.messages) ||
    !transcript.messages.every(isPersistedMessage) ||
    (transcript.entry !== undefined && !isSessionIndexEntry(transcript.entry, sessionId))
  ) {
    throw new Error(`Snapshot phiên ${sessionId} có schema không hợp lệ.`);
  }
  if (transcript.v === SCHEMA_VERSION) {
    if (!Array.isArray(transcript.events) || !transcript.events.every(isNekoSessionEvent)) {
      throw new Error(`Log sự kiện phiên ${sessionId} có schema không hợp lệ.`);
    }
    if (!transcript.events.every(
      (event, index, events) => index === 0 || event.seq > events[index - 1].seq,
    )) {
      throw new Error(`Log sự kiện phiên ${sessionId} có thứ tự không hợp lệ.`);
    }
    const lastSeq = transcript.events[transcript.events.length - 1]?.seq ?? 0;
    if (
      transcript.eventHighWaterMark !== undefined &&
      (!Number.isInteger(transcript.eventHighWaterMark) ||
        transcript.eventHighWaterMark < lastSeq)
    ) {
      throw new Error(`Bộ đếm sự kiện phiên ${sessionId} không hợp lệ.`);
    }
  } else if (transcript.events !== undefined && !Array.isArray(transcript.events)) {
    throw new Error(`Snapshot phiên ${sessionId} có schema không hợp lệ.`);
  }
  return transcript as PersistedTranscript;
}

async function writeSession(session: NekoSession, strict: boolean): Promise<void> {
  const entry: SessionIndexEntry = {
    v: INDEX_SCHEMA_VERSION,
    id: session.id,
    agentId: session.agentId,
    agentName: session.agentName,
    title: session.title,
    createdAt: session.createdAt,
    updatedAt: session.updatedAt,
    workspace: session.workspace,
    launchProfile: session.launchProfile,
    backendSessionId: session.backendSessionId,
    controls: session.controls,
    commands: session.commands,
  };
  // The catalog contains IDs only, so publishing it before the snapshot never
  // exposes model-visible state. It makes a transcript recoverable when the
  // later index-cache write fails or the process crashes between keys. Only a
  // new ID enters the shared metadata chain; normal per-session barriers stay
  // independent from unrelated index I/O.
  if (!publishedIds.has(session.id)) {
    const catalogOperation = catalogWriteChain.catch(() => {}).then(async () => {
      const catalog = parseSessionIds(
        await loadStoreStrict<unknown>(STORE, SESSION_IDS_KEY, []),
      );
      if (!catalog.includes(session.id)) {
        // Discovery is part of the authoritative snapshot contract, even for
        // background writes. Never mark an ID published after a best-effort save.
        await saveStoreStrict(STORE, SESSION_IDS_KEY, [session.id, ...catalog]);
      }
    });
    catalogWriteChain = catalogOperation.catch(() => {});
    await catalogOperation;
    publishedIds.add(session.id);
  }

  // This per-session key is the authoritative, self-contained snapshot. A
  // crash may leave stale index metadata, but hydration reconciles from here.
  const write = strict ? saveStoreStrict : saveStore;
  await write<PersistedTranscript>(STORE, `session:${session.id}`, {
    v: SCHEMA_VERSION,
    messages: session.messages,
    events: session.events,
    eventHighWaterMark: session.eventHighWaterMark,
    entry,
  });
  // The shared index is only a cache. Queue it to prevent lost updates, but do
  // not make a durable model boundary wait for unrelated cache I/O.
  const indexOperation = indexWriteChain.catch(() => {}).then(async () => {
    const rawIndex = await loadStore<unknown>(STORE, INDEX_KEY, []);
    const index = Array.isArray(rawIndex)
      ? rawIndex.filter((item): item is SessionIndexEntry => isSessionIndexEntry(item))
      : [];
    const next = [entry, ...index.filter((item) => item.id !== session.id)];
    await saveStore(STORE, INDEX_KEY, next);
  });
  indexWriteChain = indexOperation.catch(() => {});
  void indexOperation.catch(() => {});
}

/** Serialize index+transcript writes so an older debounce can never win. */
function enqueueWrite(session: NekoSession, strict = false): Promise<void> {
  const previous = writeChains.get(session.id) ?? Promise.resolve();
  const operation = previous.catch(() => {}).then(() => writeSession(session, strict));
  const tail = operation.catch(() => {});
  writeChains.set(session.id, tail);
  void tail.then(() => {
    if (writeChains.get(session.id) === tail) writeChains.delete(session.id);
  });
  return operation;
}

/** Debounced per-session persist; trailing write wins. */
export function persistSessionDebounced(session: NekoSession): void {
  const existing = timers.get(session.id);
  if (existing) clearTimeout(existing);
  timers.set(
    session.id,
    setTimeout(() => {
      timers.delete(session.id);
      void enqueueWrite(session).catch(() => {
        /* persistence must never break streaming */
      });
    }, DEBOUNCE_MS),
  );
}

/** Immediate persist (session close, mode exit). */
export async function persistSessionNow(session: NekoSession): Promise<void> {
  const timer = timers.get(session.id);
  if (timer) {
    clearTimeout(timer);
    timers.delete(session.id);
  }
  await enqueueWrite(session);
}

/** Immediate strict persist for terminal audit outcomes and dispatch barriers. */
export async function persistSessionStrict(session: NekoSession): Promise<void> {
  const timer = timers.get(session.id);
  if (timer) {
    clearTimeout(timer);
    timers.delete(session.id);
  }
  await enqueueWrite(session, true);
}

/**
 * Durability barrier for model-visible facts. Unlike background persistence,
 * failure propagates so callers can fail closed before invoking a driver.
 */
export async function persistSessionBeforeDispatch(session: NekoSession): Promise<void> {
  await persistSessionStrict(session);
}

export async function loadSessionIndex(): Promise<SessionIndexEntry[]> {
  const rawIndex = await loadStore<unknown>(STORE, INDEX_KEY, []);
  const cached = Array.isArray(rawIndex)
    ? rawIndex.filter((entry): entry is SessionIndexEntry => isSessionIndexEntry(entry))
    : [];
  const catalog = parseSessionIds(
    await loadStoreStrict<unknown>(STORE, SESSION_IDS_KEY, []),
  );
  for (const sessionId of catalog) publishedIds.add(sessionId);
  const sessionIds = [...new Set([...catalog, ...cached.map((entry) => entry.id)])];
  const cachedById = new Map(cached.map((entry) => [entry.id, entry]));
  const resolved = await Promise.all(sessionIds.map(async (sessionId) => {
    const stored = parsePersistedTranscript(
      await loadStoreStrict<unknown>(STORE, `session:${sessionId}`, undefined),
      sessionId,
    );
    if (!stored) return null;
    const embedded = stored && isSessionIndexEntry(stored.entry, sessionId)
      ? stored.entry
      : null;
    const metadata = embedded ?? cachedById.get(sessionId) ?? null;
    if (!metadata && catalog.includes(sessionId)) {
      throw new Error(`Không thể khôi phục metadata phiên ${sessionId}.`);
    }
    return metadata;
  }));
  const reconciled = resolved.filter(
    (entry): entry is SessionIndexEntry => entry !== null,
  );
  return reconciled.sort((left, right) => right.updatedAt - left.updatedAt);
}

export async function loadSessionSnapshot(sessionId: string): Promise<LoadedSessionSnapshot> {
  const stored = parsePersistedTranscript(
    await loadStoreStrict<unknown>(STORE, `session:${sessionId}`, undefined),
    sessionId,
  );
  if (!stored) {
    return {
      messages: [],
      events: [],
      eventHighWaterMark: 0,
      needsEventMigration: false,
    };
  }
  if (stored.v !== SCHEMA_VERSION) {
    return {
      messages: stored.messages,
      events: [],
      eventHighWaterMark: 0,
      needsEventMigration: true,
    };
  }
  const lastSeq = stored.events![stored.events!.length - 1]?.seq ?? 0;
  return {
    messages: stored.messages,
    events: stored.events!,
    eventHighWaterMark: stored.eventHighWaterMark ?? lastSeq,
    needsEventMigration: false,
  };
}

/** Compatibility helper for callers that only need the materialized view. */
export async function loadSessionTranscript(sessionId: string): Promise<NekoMessage[]> {
  return (await loadSessionSnapshot(sessionId)).messages;
}

async function performDeletePersistedSession(sessionId: string): Promise<void> {
  const timer = timers.get(sessionId);
  if (timer) {
    clearTimeout(timer);
    timers.delete(sessionId);
  }
  await writeChains.get(sessionId)?.catch(() => {});
  const snapshotKey = `session:${sessionId}`;
  // Hold the catalog chain from validation through metadata commit. A
  // malformed catalog must fail before the destructive snapshot delete.
  const catalogOperation = catalogWriteChain.catch(() => {}).then(async () => {
    const catalog = parseSessionIds(
      await loadStoreStrict<unknown>(STORE, SESSION_IDS_KEY, []),
    );
    const snapshot = await loadStoreStrict<unknown>(STORE, snapshotKey, undefined);
    const previousIndex = await loadStoreStrict<unknown>(STORE, INDEX_KEY, undefined);
    const indexBackup = Array.isArray(previousIndex) ? previousIndex : null;
    let snapshotDeleteAttempted = false;
    try {
      snapshotDeleteAttempted = true;
      await deleteStoreStrict(STORE, snapshotKey);
      const indexOperation = indexWriteChain.catch(() => {}).then(async () => {
        let indexAttempted = false;
        let catalogAttempted = false;
        try {
          if (indexBackup) {
            indexAttempted = true;
            await saveStoreStrict(
              STORE,
              INDEX_KEY,
              indexBackup.filter((item) => (
                !item || typeof item !== "object" || Array.isArray(item) ||
                (item as Record<string, unknown>).id !== sessionId
              )),
            );
          }
          catalogAttempted = true;
          await saveStoreStrict(
            STORE,
            SESSION_IDS_KEY,
            catalog.filter((id) => id !== sessionId),
          );
        } catch (error) {
          const rollbackErrors: unknown[] = [];
          if (catalogAttempted) {
            try {
              await saveStoreStrict(STORE, SESSION_IDS_KEY, catalog);
            } catch (rollbackError) {
              rollbackErrors.push(rollbackError);
            }
          }
          if (indexAttempted) {
            try {
              await saveStoreStrict(STORE, INDEX_KEY, indexBackup);
            } catch (rollbackError) {
              rollbackErrors.push(rollbackError);
            }
          }
          if (rollbackErrors.length > 0) {
            // The catalog may no longer contain this ID. Force the next write
            // to republish it instead of trusting a stale in-memory marker.
            publishedIds.delete(sessionId);
            throw new AggregateError(
              [error, ...rollbackErrors],
              `Không thể xóa hoặc khôi phục metadata phiên ${sessionId}.`,
            );
          }
          throw error;
        }
      });
      indexWriteChain = indexOperation.catch(() => {});
      await indexOperation;
    } catch (error) {
      if (snapshotDeleteAttempted && snapshot !== undefined) {
        try {
          await saveStoreStrict(STORE, snapshotKey, snapshot);
        } catch (rollbackError) {
          throw new AggregateError(
            [error, rollbackError],
            `Không thể xóa hoặc khôi phục snapshot phiên ${sessionId}.`,
          );
        }
      }
      throw error;
    }
  });
  catalogWriteChain = catalogOperation.catch(() => {});
  await catalogOperation;
  publishedIds.delete(sessionId);
}

/** Serialize the complete delete transaction per session, including retries. */
export function deletePersistedSession(sessionId: string): Promise<void> {
  const previous = deleteChains.get(sessionId) ?? Promise.resolve();
  const operation = previous
    .catch(() => {})
    .then(() => performDeletePersistedSession(sessionId));
  const tail = operation.catch(() => {});
  deleteChains.set(sessionId, tail);
  void tail.then(() => {
    if (deleteChains.get(sessionId) === tail) deleteChains.delete(sessionId);
  });
  return operation;
}
