import { v4 as uuidv4 } from "uuid";

export interface CodexBootstrapIdentity {
  workspacePath: string;
  clientSessionId: string;
}

/**
 * Keep one logical caller identity while a Codex account probe is retried.
 * Neko's control client can then recover an unresolved native start instead
 * of minting a second App Server. A workspace change is a different scope;
 * fresh native execution IDs after a proven terminal outcome remain owned by
 * the control client behind this stable caller key.
 */
export function codexBootstrapIdentity(
  current: CodexBootstrapIdentity | null,
  workspacePath: string,
  createId: () => string = uuidv4,
): CodexBootstrapIdentity {
  if (current?.workspacePath === workspacePath) return current;
  return {
    workspacePath,
    clientSessionId: `codex-account-bootstrap-${createId()}`,
  };
}
