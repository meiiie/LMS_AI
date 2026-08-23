import { v4 as uuidv4, v5 as uuidv5 } from "uuid";
import type {
  NekoControlClient,
  NekoNativeSessionRecord,
  NekoSpawnedProvider,
} from "@/neko/control-client";

export interface CodexBootstrapIdentity {
  workspacePath: string;
  clientSessionId: string;
  clientRunId: string;
}

interface RetainedStartControl {
  listSessions(runId?: string): Promise<NekoNativeSessionRecord[]>;
  unresolvedStartSessionIds(): string[];
  cancelUnresolvedStarts(clientSessionId: string): Promise<number>;
}

const CODEX_BOOTSTRAP_SESSION_PREFIX = "codex-account-bootstrap-";
const LEGACY_LOCAL_TASK_PREFIX = "legacy-local/task/";
const NATIVE_TERMINAL_STATES = new Set(["completed", "failed", "cancelled"]);

/**
 * Derive the account-probe caller from durable workspace identity rather than
 * React component lifetime. Remounting NewSessionView or reloading the WebView
 * therefore reaches the same unresolved native start while it remains
 * non-terminal. Each invocation still receives a fresh Run identity so a
 * later bootstrap after a proven terminal attempt cannot reuse its lifecycle.
 */
export function codexBootstrapIdentity(workspacePath: string): CodexBootstrapIdentity {
  const normalizedWorkspace = canonicalWorkspaceIdentity(workspacePath);
  const scope = uuidv5(
    normalizedWorkspace,
    "ce6c70a7-cb49-5fd8-992f-a10e1459fa8e",
  );
  return {
    workspacePath,
    clientSessionId: `${CODEX_BOOTSTRAP_SESSION_PREFIX}${scope}`,
    clientRunId: `codex-account-bootstrap-run-${uuidv4()}`,
  };
}

/**
 * A lost start response can leave native authority without an account-session
 * object in React. Before a different workspace receives a fresh bootstrap
 * identity, reconcile and cancel every older Codex bootstrap retained by the
 * control client. Failure is intentionally propagated so no second App Server
 * can be launched beside an active or uncertain first one.
 */
export async function cancelOtherCodexBootstrapStarts(
  control: RetainedStartControl,
  currentClientSessionId: string,
): Promise<number> {
  const failures: unknown[] = [];
  const candidates = new Set(control.unresolvedStartSessionIds());
  try {
    for (const session of await control.listSessions()) {
      const clientSessionId = codexBootstrapClientSessionId(session);
      if (clientSessionId) candidates.add(clientSessionId);
    }
  } catch (error) {
    failures.push(error);
  }

  let cancelled = 0;
  const prior = [...candidates]
    .filter((sessionId) => (
      sessionId.startsWith(CODEX_BOOTSTRAP_SESSION_PREFIX) &&
      sessionId !== currentClientSessionId
    ))
    .sort();
  for (const sessionId of prior) {
    try {
      cancelled += await control.cancelUnresolvedStarts(sessionId);
    } catch (error) {
      failures.push(error);
    }
  }
  if (failures.length > 0) {
    if (failures.length === 1) throw failures[0];
    throw new AggregateError(
      failures,
      `Neko could not safely reconcile ${failures.length} older Codex bootstrap operation(s).`,
    );
  }
  return cancelled;
}

function codexBootstrapClientSessionId(
  session: NekoNativeSessionRecord,
): string | null {
  if (
    session.providerId !== "codex" ||
    NATIVE_TERMINAL_STATES.has(session.state) ||
    !session.taskId.startsWith(LEGACY_LOCAL_TASK_PREFIX)
  ) {
    return null;
  }
  const clientSessionId = session.taskId.slice(LEGACY_LOCAL_TASK_PREFIX.length);
  return clientSessionId.startsWith(CODEX_BOOTSTRAP_SESSION_PREFIX)
    ? clientSessionId
    : null;
}

/** Fail-closed workspace handoff followed by the one authorized launch. */
export async function spawnCodexAccountBootstrap(
  control: Pick<
    NekoControlClient,
    | "listSessions"
    | "unresolvedStartSessionIds"
    | "cancelUnresolvedStarts"
    | "spawnProvider"
  >,
  identity: CodexBootstrapIdentity,
): Promise<NekoSpawnedProvider> {
  await cancelOtherCodexBootstrapStarts(control, identity.clientSessionId);
  return control.spawnProvider({
    providerId: "codex",
    clientSessionId: identity.clientSessionId,
    clientRunId: identity.clientRunId,
    workspacePath: identity.workspacePath,
  });
}

/**
 * Produce a stable logical identity for a host path without filesystem I/O.
 * Windows drive and UNC namespaces are case-insensitive by default, so casing
 * and separator aliases must not mint a second bootstrap Run. POSIX casing is
 * preserved because it can identify different directories there.
 */
export function canonicalWorkspaceIdentity(workspacePath: string): string {
  const nfc = workspacePath.normalize("NFC");
  const hadUncPrefix = /^[\\/]{2}[^\\/]/.test(nfc);
  const isWindowsNamespace = hadUncPrefix || /^[A-Za-z]:[\\/]/.test(nfc);
  let normalized = isWindowsNamespace
    ? nfc.replaceAll("\\", "/").replace(/\/{2,}/g, "/")
    : nfc.replace(/\/{2,}/g, "/");
  if (hadUncPrefix) normalized = `/${normalized}`;
  if (normalized !== "/" && !/^[A-Za-z]:\/$/.test(normalized)) {
    normalized = normalized.replace(/\/+$/, "");
  }
  return isWindowsNamespace ? normalized.toLocaleLowerCase("en-US") : normalized;
}
