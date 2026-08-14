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
import { loadStore, saveStore, saveStoreStrict, deleteStore } from "@/lib/storage";
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

function validSessionIds(value: unknown): string[] {
  return Array.isArray(value)
    ? [...new Set(value.filter((item): item is string => typeof item === "string"))]
    : [];
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
  const write = strict ? saveStoreStrict : saveStore;
  // The catalog contains IDs only, so publishing it before the snapshot never
  // exposes model-visible state. It makes a transcript recoverable when the
  // later index-cache write fails or the process crashes between keys.
  const catalogOperation = indexWriteChain.catch(() => {}).then(async () => {
    const catalog = validSessionIds(await loadStore<unknown>(STORE, SESSION_IDS_KEY, []));
    if (!catalog.includes(session.id)) {
      await write(STORE, SESSION_IDS_KEY, [session.id, ...catalog]);
    }
  });
  indexWriteChain = catalogOperation.catch(() => {});
  await catalogOperation;

  // This per-session key is the authoritative, self-contained snapshot. A
  // crash may leave stale index metadata, but hydration reconciles from here.
  await write<PersistedTranscript>(STORE, `session:${session.id}`, {
    v: SCHEMA_VERSION,
    messages: session.messages,
    events: session.events,
    entry,
  });
  // The shared index needs its own short critical section to prevent lost
  // updates, but a slow transcript write in another session must not block
  // this session's durability barrier.
  const indexOperation = indexWriteChain.catch(() => {}).then(async () => {
    const index = await loadStore<SessionIndexEntry[]>(STORE, INDEX_KEY, []);
    const next = [entry, ...index.filter((item) => item.id !== session.id)];
    await write(STORE, INDEX_KEY, next);
  });
  indexWriteChain = indexOperation.catch(() => {});
  await indexOperation;
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
  const catalog = validSessionIds(await loadStore<unknown>(STORE, SESSION_IDS_KEY, []));
  const sessionIds = [...new Set([...catalog, ...cached.map((entry) => entry.id)])];
  const reconciled: SessionIndexEntry[] = [];
  for (const sessionId of sessionIds) {
    const stored = await loadStore<PersistedTranscript | null>(
      STORE,
      `session:${sessionId}`,
      null,
    );
    const embedded = stored && isSessionIndexEntry(stored.entry, sessionId)
      ? stored.entry
      : null;
    const fallback = cached.find((entry) => entry.id === sessionId) ?? null;
    const recovered = embedded ?? fallback;
    if (recovered) reconciled.push(recovered);
  }
  return reconciled.sort((left, right) => right.updatedAt - left.updatedAt);
}

export async function loadSessionSnapshot(sessionId: string): Promise<LoadedSessionSnapshot> {
  const stored = await loadStore<PersistedTranscript | null>(
    STORE,
    `session:${sessionId}`,
    null,
  );
  if (!stored || !Array.isArray(stored.messages)) {
    return { messages: [], events: [], needsEventMigration: false };
  }
  if (stored.v !== SCHEMA_VERSION || !Array.isArray(stored.events)) {
    return { messages: stored.messages, events: [], needsEventMigration: true };
  }
  const events = stored.events.filter(isNekoSessionEvent);
  const hasStableSequence = events.every((event, index) => event.seq === index + 1);
  if (events.length !== stored.events.length || !hasStableSequence) {
    return { messages: stored.messages, events: [], needsEventMigration: true };
  }
  return { messages: stored.messages, events, needsEventMigration: false };
}

/** Compatibility helper for callers that only need the materialized view. */
export async function loadSessionTranscript(sessionId: string): Promise<NekoMessage[]> {
  return (await loadSessionSnapshot(sessionId)).messages;
}

export async function deletePersistedSession(sessionId: string): Promise<void> {
  const timer = timers.get(sessionId);
  if (timer) {
    clearTimeout(timer);
    timers.delete(sessionId);
  }
  await writeChains.get(sessionId)?.catch(() => {});
  const indexOperation = indexWriteChain.catch(() => {}).then(async () => {
    const rawIndex = await loadStore<unknown>(STORE, INDEX_KEY, []);
    const index = Array.isArray(rawIndex)
      ? rawIndex.filter((entry): entry is SessionIndexEntry => isSessionIndexEntry(entry))
      : [];
    const catalog = validSessionIds(await loadStore<unknown>(STORE, SESSION_IDS_KEY, []));
    await saveStore(
      STORE,
      INDEX_KEY,
      index.filter((item) => item.id !== sessionId),
    );
    await saveStore(
      STORE,
      SESSION_IDS_KEY,
      catalog.filter((id) => id !== sessionId),
    );
  });
  indexWriteChain = indexOperation.catch(() => {});
  await indexOperation;
  await deleteStore(STORE, `session:${sessionId}`).catch(() => {});
}
