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
  const normalizedWorkspace = workspacePath.replaceAll("\\", "/").replace(/\/+$/, "");
  const scope = uuidv5(
    normalizedWorkspace,
    "ce6c70a7-cb49-5fd8-992f-a10e1459fa8e",
  );
  return {
    workspacePath,
    clientSessionId: `codex-account-bootstrap-${scope}`,
  };
}
