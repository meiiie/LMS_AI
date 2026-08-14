/**
 * Local session persistence (T501, FR-008) — tauri plugin-store via the
 * shared storage wrapper (localStorage fallback in browser dev).
 *
 * Layout (versioned for future migration):
 *   neko-chill-sessions.json / "index"        → SessionIndexEntry[]
 *   neko-chill-sessions.json / "session:{id}" → { v: 2, messages, events }
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
}

export interface LoadedSessionSnapshot {
  messages: NekoMessage[];
  events: NekoSessionEvent[];
  /** v1/corrupt event data needs a deterministic audit-log backfill. */
  needsEventMigration: boolean;
}

const timers = new Map<string, ReturnType<typeof setTimeout>>();
let writeChain: Promise<void> = Promise.resolve();

async function writeSession(session: NekoSession, strict: boolean): Promise<void> {
  const index = await loadStore<SessionIndexEntry[]>(STORE, INDEX_KEY, []);
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
  const next = [entry, ...index.filter((item) => item.id !== session.id)];
  // Log-bearing snapshot first: a crash may leave stale index metadata, but
  // must never expose newer model-visible state without its durable event.
  const write = strict ? saveStoreStrict : saveStore;
  await write<PersistedTranscript>(STORE, `session:${session.id}`, {
    v: SCHEMA_VERSION,
    messages: session.messages,
    events: session.events,
  });
  await write(STORE, INDEX_KEY, next);
}

/** Serialize index+transcript writes so an older debounce can never win. */
function enqueueWrite(session: NekoSession, strict = false): Promise<void> {
  const operation = writeChain.catch(() => {}).then(() => writeSession(session, strict));
  writeChain = operation.catch(() => {});
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
  await enqueueWrite(session).catch(() => {});
}

/**
 * Durability barrier for model-visible facts. Unlike background persistence,
 * failure propagates so callers can fail closed before invoking a driver.
 */
export async function persistSessionBeforeDispatch(session: NekoSession): Promise<void> {
  const timer = timers.get(session.id);
  if (timer) {
    clearTimeout(timer);
    timers.delete(session.id);
  }
  await enqueueWrite(session, true);
}

export async function loadSessionIndex(): Promise<SessionIndexEntry[]> {
  const index = await loadStore<SessionIndexEntry[]>(STORE, INDEX_KEY, []);
  return Array.isArray(index) ? index : [];
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
  await writeChain.catch(() => {});
  const index = await loadSessionIndex();
  await saveStore(
    STORE,
    INDEX_KEY,
    index.filter((item) => item.id !== sessionId),
  );
  await deleteStore(STORE, `session:${sessionId}`).catch(() => {});
}
