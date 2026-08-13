/**
 * Local session persistence (T501, FR-008) — tauri plugin-store via the
 * shared storage wrapper (localStorage fallback in browser dev).
 *
 * Layout (versioned for future migration):
 *   neko-chill-sessions.json / "index"        → SessionIndexEntry[]
 *   neko-chill-sessions.json / "session:{id}" → { v: 1, messages }
 *
 * Writes are debounced per session so token streaming never causes a
 * full-store rewrite per delta (spec edge case: long transcripts).
 */
import { loadStore, saveStore, deleteStore } from "@/lib/storage";
import type { NekoMessage, NekoSession } from "./stores/neko-session-store";

const STORE = "neko-chill-sessions.json";
const INDEX_KEY = "index";
const SCHEMA_VERSION = 1;
const DEBOUNCE_MS = 400;

export interface SessionIndexEntry {
  id: string;
  agentId: string;
  agentName: string;
  title: string;
  createdAt: number;
  updatedAt: number;
}

interface PersistedTranscript {
  v: number;
  messages: NekoMessage[];
}

const timers = new Map<string, ReturnType<typeof setTimeout>>();

async function writeSession(session: NekoSession): Promise<void> {
  const index = await loadStore<SessionIndexEntry[]>(STORE, INDEX_KEY, []);
  const entry: SessionIndexEntry = {
    id: session.id,
    agentId: session.agentId,
    agentName: session.agentName,
    title: session.title,
    createdAt: session.createdAt,
    updatedAt: Date.now(),
  };
  const next = [entry, ...index.filter((item) => item.id !== session.id)];
  await saveStore(STORE, INDEX_KEY, next);
  await saveStore<PersistedTranscript>(STORE, `session:${session.id}`, {
    v: SCHEMA_VERSION,
    messages: session.messages,
  });
}

/** Debounced per-session persist; trailing write wins. */
export function persistSessionDebounced(session: NekoSession): void {
  const existing = timers.get(session.id);
  if (existing) clearTimeout(existing);
  timers.set(
    session.id,
    setTimeout(() => {
      timers.delete(session.id);
      void writeSession(session).catch(() => {
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
  await writeSession(session).catch(() => {});
}

export async function loadSessionIndex(): Promise<SessionIndexEntry[]> {
  const index = await loadStore<SessionIndexEntry[]>(STORE, INDEX_KEY, []);
  return Array.isArray(index) ? index : [];
}

export async function loadSessionTranscript(sessionId: string): Promise<NekoMessage[]> {
  const stored = await loadStore<PersistedTranscript | null>(
    STORE,
    `session:${sessionId}`,
    null,
  );
  if (!stored || stored.v !== SCHEMA_VERSION || !Array.isArray(stored.messages)) {
    return [];
  }
  return stored.messages;
}

export async function deletePersistedSession(sessionId: string): Promise<void> {
  const index = await loadSessionIndex();
  await saveStore(
    STORE,
    INDEX_KEY,
    index.filter((item) => item.id !== sessionId),
  );
  await deleteStore(STORE, `session:${sessionId}`).catch(() => {});
}
