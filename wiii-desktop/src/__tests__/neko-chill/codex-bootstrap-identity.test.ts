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

  it("uses one identity for Windows drive and UNC casing aliases", () => {
    expect(codexBootstrapIdentity("C:\\Work\\Wiii").clientSessionId).toBe(
      codexBootstrapIdentity("c:/work/wiii/").clientSessionId,
    );
    expect(codexBootstrapIdentity("\\\\SERVER\\Share\\Wiii").clientSessionId).toBe(
      codexBootstrapIdentity("//server/share/wiii/").clientSessionId,
    );
  });

  it("preserves case for POSIX paths where casing may identify another workspace", () => {
    expect(codexBootstrapIdentity("/srv/Wiii").clientSessionId).not.toBe(
      codexBootstrapIdentity("/srv/wiii").clientSessionId,
    );
  });

  it("preserves backslashes that are legal POSIX filename characters", () => {
    expect(codexBootstrapIdentity("/srv/a\\b").clientSessionId).not.toBe(
      codexBootstrapIdentity("/srv/a/b").clientSessionId,
    );
  });
});
