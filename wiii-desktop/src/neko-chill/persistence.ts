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
import type { NekoMessage, NekoSession } from "./stores/neko-session-store";
import type { DriverCommand, DriverConfigOption } from "./drivers/types";
import type { AgentLaunchProfile } from "./stores/neko-agent-store";
import type { WorkspaceRef } from "./workspace";
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
  controls?: DriverConfigOption[];
  commands?: DriverCommand[];
}

interface PersistedTranscript {
  v: number;
  messages: NekoMessage[];
  events?: NekoSessionEvent[];
  /** Authoritative materialized metadata; index is only a discovery cache. */
  entry?: SessionIndexEntry;
}

export interface LoadedSessionSnapshot {
  messages: NekoMessage[];
  events: NekoSessionEvent[];
  /** v1/corrupt event data needs a deterministic audit-log backfill. */
  needsEventMigration: boolean;
}

const timers = new Map<string, ReturnType<typeof setTimeout>>();
const writeChains = new Map<string, Promise<void>>();
const deleteChains = new Map<string, Promise<void>>();
const publishedIds = new Set<string>();
let catalogWriteChain: Promise<void> = Promise.resolve();
let indexWriteChain: Promise<void> = Promise.resolve();

function isSessionIndexEntry(value: unknown, expectedId?: string): value is SessionIndexEntry {
  if (!value || typeof value !== "object") return false;
  const entry = value as Partial<SessionIndexEntry>;
  return (
    typeof entry.id === "string" &&
    (!expectedId || entry.id === expectedId) &&
    typeof entry.agentId === "string" &&
    typeof entry.agentName === "string" &&
    typeof entry.title === "string" &&
    typeof entry.createdAt === "number" &&
    Number.isFinite(entry.createdAt) &&
    typeof entry.updatedAt === "number" &&
    Number.isFinite(entry.updatedAt) &&
    (entry.controls === undefined || Array.isArray(entry.controls)) &&
    (entry.commands === undefined || Array.isArray(entry.commands))
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

function isPersistedMessage(value: unknown): value is NekoMessage {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const message = value as Partial<NekoMessage>;
  if (
    typeof message.id !== "string" ||
    (message.role !== "user" && message.role !== "assistant") ||
    (message.text !== undefined && typeof message.text !== "string") ||
    (message.blocks !== undefined && !Array.isArray(message.blocks))
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
    if (!transcript.events.every((event, index) => event.seq === index + 1)) {
      throw new Error(`Log sự kiện phiên ${sessionId} có thứ tự không hợp lệ.`);
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
    return embedded ?? cachedById.get(sessionId) ?? null;
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
    return { messages: [], events: [], needsEventMigration: false };
  }
  if (stored.v !== SCHEMA_VERSION) {
    return { messages: stored.messages, events: [], needsEventMigration: true };
  }
  return { messages: stored.messages, events: stored.events!, needsEventMigration: false };
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
  // Delete the authoritative transcript first. If this fails, catalog/index
  // still discover the intact session and the caller can retry safely.
  await deleteStoreStrict(STORE, `session:${sessionId}`);
  const indexOperation = indexWriteChain.catch(() => {}).then(async () => {
    const rawIndex = await loadStore<unknown>(STORE, INDEX_KEY, []);
    const index = Array.isArray(rawIndex)
      ? rawIndex.filter((entry): entry is SessionIndexEntry => isSessionIndexEntry(entry))
      : [];
    await saveStoreStrict(
      STORE,
      INDEX_KEY,
      index.filter((item) => item.id !== sessionId),
    );
  });
  indexWriteChain = indexOperation.catch(() => {});
  await indexOperation;
  const catalogOperation = catalogWriteChain.catch(() => {}).then(async () => {
    const catalog = parseSessionIds(
      await loadStoreStrict<unknown>(STORE, SESSION_IDS_KEY, []),
    );
    await saveStoreStrict(
      STORE,
      SESSION_IDS_KEY,
      catalog.filter((id) => id !== sessionId),
    );
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
