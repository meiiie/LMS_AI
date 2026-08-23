import { v5 as uuidv5 } from "uuid";

export interface CodexBootstrapIdentity {
  workspacePath: string;
  clientSessionId: string;
}

/**
 * Derive the account-probe caller from durable workspace identity rather than
 * React component lifetime. Remounting NewSessionView or reloading the WebView
 * therefore reaches the same native Run and cannot silently create a second
 * App Server while the first start remains non-terminal.
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
