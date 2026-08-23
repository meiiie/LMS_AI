import { describe, expect, it, vi } from "vitest";
import type { AcpTransport } from "@/neko-chill/drivers/acp/client";
import {
  CodexAccountBootstrapOwner,
  CodexAccountSession,
} from "@/neko-chill/drivers/codex/account";

class AccountTransport implements AcpTransport {
  readonly sent: Array<Record<string, unknown>> = [];
  private onLineHandler: ((line: string) => void) | null = null;
  private onExitHandler: ((code: number | null) => void) | null = null;
  account: Record<string, unknown> | null = null;
  failInitialize = false;
  killed = false;
  killCalls = 0;
  killFailures = 0;

  async send(line: string): Promise<void> {
    const frame = JSON.parse(line) as Record<string, unknown>;
    this.sent.push(frame);
    if (typeof frame.id !== "number") return;
    if (frame.method === "initialize") {
      if (this.failInitialize) {
        this.emit({
          jsonrpc: "2.0",
          id: frame.id,
          error: { code: -32603, message: "bootstrap failed" },
        });
      } else {
        this.response(frame.id, {});
      }
    }
    if (frame.method === "account/read") {
      this.response(frame.id, { account: this.account, requiresOpenaiAuth: true });
    }
    if (frame.method === "account/login/start") {
      this.response(frame.id, {
        type: "chatgpt",
        loginId: "login-1",
        authUrl: "https://auth.example.test/codex",
      });
    }
  }

  onLine(handler: (line: string) => void): void {
    this.onLineHandler = handler;
  }

  onExit(handler: (code: number | null) => void): void {
    this.onExitHandler = handler;
  }

  async kill(): Promise<void> {
    this.killCalls += 1;
    if (this.killFailures > 0) {
      this.killFailures -= 1;
      throw new Error("cleanup failed");
    }
    this.killed = true;
  }

  response(id: number, result: unknown): void {
    this.emit({ jsonrpc: "2.0", id, result });
  }

  emit(frame: unknown): void {
    this.onLineHandler?.(JSON.stringify(frame));
  }
}

describe("Codex provider-owned account session", () => {
  it("reads only public account state and never persists credentials", async () => {
    const transport = new AccountTransport();
    transport.account = { type: "chatgpt", planType: "plus" };
    const session = new CodexAccountSession(transport);
    await expect(session.start()).resolves.toEqual({
      authenticated: true,
      requiresOpenaiAuth: true,
      accountType: "chatgpt",
      planType: "plus",
    });
    expect(JSON.stringify(transport.sent)).not.toMatch(/"accessToken"|"apiKey"|"refreshToken":"/);
  });

  it("surfaces the browser challenge and completes from Codex notification", async () => {
    const transport = new AccountTransport();
    const session = new CodexAccountSession(transport);
    await session.start();
    const challenge = await session.beginChatGptLogin();
    expect(challenge).toEqual({
      loginId: "login-1",
      authUrl: "https://auth.example.test/codex",
    });
    const waiting = session.waitForLogin(challenge.loginId);
    transport.account = { type: "chatgpt", planType: "team" };
    transport.emit({
      jsonrpc: "2.0",
      method: "account/login/completed",
      params: { loginId: "login-1", success: true, error: null },
    });
    await expect(waiting).resolves.toBeUndefined();
    await expect(session.read()).resolves.toEqual(expect.objectContaining({
      authenticated: true,
      planType: "team",
    }));
  });

  it("reports provider login failures without converting them to success", async () => {
    const transport = new AccountTransport();
    const session = new CodexAccountSession(transport);
    await session.start();
    const waiting = session.waitForLogin("login-2");
    transport.emit({
      jsonrpc: "2.0",
      method: "account/login/completed",
      params: { loginId: "login-2", success: false, error: "denied" },
    });
    await expect(waiting).rejects.toThrow("denied");
  });

  it("disposes the App Server process when bootstrap fails", async () => {
    const transport = new AccountTransport();
    transport.failInitialize = true;
    const session = new CodexAccountSession(transport);

    await expect(session.start()).rejects.toThrow("bootstrap failed");
    expect(transport.killed).toBe(true);
    await expect(session.dispose()).resolves.toBeUndefined();
  });

  it("keeps disposal retryable until native cleanup succeeds", async () => {
    const transport = new AccountTransport();
    transport.killFailures = 1;
    const session = new CodexAccountSession(transport);

    await expect(session.dispose()).rejects.toThrow("cleanup failed");
    expect(transport.killed).toBe(false);
    await expect(session.dispose()).resolves.toBeUndefined();
    expect(transport.killCalls).toBe(2);
    expect(transport.killed).toBe(true);
  });

  it("does not replace a bootstrap whose cleanup remains unproven", async () => {
    const owner = new CodexAccountBootstrapOwner();
    const firstTransport = new AccountTransport();
    firstTransport.killFailures = 2;
    const first = new CodexAccountSession(firstTransport);
    await owner.replace(async () => first);

    await expect(owner.release(first)).rejects.toThrow("cleanup failed");
    expect(owner.current()).toBe(first);
    let replacementCreated = false;
    await expect(owner.replace(async () => {
      replacementCreated = true;
      return new CodexAccountSession(new AccountTransport());
    })).rejects.toThrow("cleanup failed");
    expect(replacementCreated).toBe(false);
    expect(owner.current()).toBe(first);

    const replacement = new CodexAccountSession(new AccountTransport());
    await expect(owner.replace(async () => {
      replacementCreated = true;
      return replacement;
    })).resolves.toBe(replacement);
    expect(firstTransport.killCalls).toBe(3);
    expect(owner.current()).toBe(replacement);
    await owner.release(replacement);
  });
});
