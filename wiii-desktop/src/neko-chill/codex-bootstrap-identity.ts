import { v4 as uuidv4, v5 as uuidv5 } from "uuid";

export interface CodexBootstrapIdentity {
  workspacePath: string;
  clientSessionId: string;
  clientRunId: string;
}

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
    clientSessionId: `codex-account-bootstrap-${scope}`,
    clientRunId: `codex-account-bootstrap-run-${uuidv4()}`,
  };
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
