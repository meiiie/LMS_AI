import { describe, expect, it } from "vitest";
import {
  cancelOtherCodexBootstrapStarts,
  codexBootstrapIdentity,
  spawnCodexAccountBootstrap,
} from "@/neko-chill/codex-bootstrap-identity";
import type { AcpTransport } from "@/neko-chill/drivers/acp/client";

describe("Codex account bootstrap identity", () => {
  it("keeps caller identity but mints a fresh Run for each bootstrap attempt", () => {
    const first = codexBootstrapIdentity("C:/workspace");
    const remounted = codexBootstrapIdentity("C:/workspace");

    expect(remounted).not.toBe(first);
    expect(remounted.clientSessionId).toBe(first.clientSessionId);
    expect(remounted.clientRunId).not.toBe(first.clientRunId);
    expect(first.clientSessionId).toMatch(/^codex-account-bootstrap-[0-9a-f-]{36}$/);
    expect(first.clientRunId).toMatch(/^codex-account-bootstrap-run-[0-9a-f-]{36}$/);
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

  it("cancels retained bootstraps from other workspaces before a fresh launch", async () => {
    const current = codexBootstrapIdentity("C:/workspace-b").clientSessionId;
    const old = codexBootstrapIdentity("C:/workspace-a").clientSessionId;
    const cancelled: string[] = [];
    const count = await cancelOtherCodexBootstrapStarts({
      unresolvedStartSessionIds: () => [current, "ordinary-session", old, old],
      cancelUnresolvedStarts: async (sessionId) => {
        cancelled.push(sessionId);
        return 1;
      },
    }, current);

    expect(cancelled).toEqual([old]);
    expect(count).toBe(1);
  });

  it("fails closed when an older workspace bootstrap cannot be reconciled", async () => {
    const current = codexBootstrapIdentity("C:/workspace-b").clientSessionId;
    const old = codexBootstrapIdentity("C:/workspace-a").clientSessionId;

    await expect(cancelOtherCodexBootstrapStarts({
      unresolvedStartSessionIds: () => [old],
      cancelUnresolvedStarts: async () => {
        throw new Error("cancellation remains uncertain");
      },
    }, current)).rejects.toThrow("cancellation remains uncertain");
  });

  it("never spawns the new workspace before retained-start cancellation succeeds", async () => {
    const identity = codexBootstrapIdentity("C:/workspace-b");
    const old = codexBootstrapIdentity("C:/workspace-a").clientSessionId;
    const calls: string[] = [];
    const transport = {} as AcpTransport;

    const spawned = await spawnCodexAccountBootstrap({
      unresolvedStartSessionIds: () => [old],
      cancelUnresolvedStarts: async (sessionId) => {
        calls.push(`cancel:${sessionId}`);
        return 1;
      },
      spawnProvider: async (request) => {
        calls.push(`spawn:${request.clientSessionId}`);
        return {
          provider: {
            id: "codex",
            name: "Codex",
            version: "0.1.0",
            found: true,
            availability: "available",
            supportsProfiles: false,
          },
          agentSessionId: "native-session",
          runId: "native-run",
          transport,
        };
      },
    }, identity);

    expect(spawned.transport).toBe(transport);
    expect(calls).toEqual([
      `cancel:${old}`,
      `spawn:${identity.clientSessionId}`,
    ]);
  });

  it("does not spawn a new workspace after retained-start cancellation fails", async () => {
    const identity = codexBootstrapIdentity("C:/workspace-b");
    const old = codexBootstrapIdentity("C:/workspace-a").clientSessionId;
    let spawned = false;

    await expect(spawnCodexAccountBootstrap({
      unresolvedStartSessionIds: () => [old],
      cancelUnresolvedStarts: async () => {
        throw new Error("old bootstrap remains uncertain");
      },
      spawnProvider: async () => {
        spawned = true;
        throw new Error("must not launch");
      },
    }, identity)).rejects.toThrow("old bootstrap remains uncertain");
    expect(spawned).toBe(false);
  });
});
