import { describe, expect, it } from "vitest";
import { codexBootstrapIdentity } from "@/neko-chill/codex-bootstrap-identity";

describe("Codex account bootstrap identity", () => {
  it("derives one caller identity across retries and component remounts", () => {
    const first = codexBootstrapIdentity("C:/workspace");
    const remounted = codexBootstrapIdentity("C:/workspace");

    expect(remounted).not.toBe(first);
    expect(remounted).toEqual(first);
    expect(first.clientSessionId).toMatch(/^codex-account-bootstrap-[0-9a-f-]{36}$/);
  });

  it("normalizes Windows separators but isolates different workspaces", () => {
    const slash = codexBootstrapIdentity("C:/workspace-a/");
    const backslash = codexBootstrapIdentity("C:\\workspace-a");
    const next = codexBootstrapIdentity("C:/workspace-b");

    expect(backslash.clientSessionId).toBe(slash.clientSessionId);
    expect(next.clientSessionId).not.toBe(slash.clientSessionId);
  });
});
