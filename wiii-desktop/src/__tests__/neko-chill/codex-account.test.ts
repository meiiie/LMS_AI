import { describe, expect, it, vi } from "vitest";
import type { AcpTransport } from "@/neko-chill/drivers/acp/client";
import { CodexAccountSession } from "@/neko-chill/drivers/codex/account";

class AccountTransport implements AcpTransport {
  readonly sent: Array<Record<string, unknown>> = [];
  private onLineHandler: ((line: string) => void) | null = null;
  private onExitHandler: ((code: number | null) => void) | null = null;
  account: Record<string, unknown> | null = null;

  async send(line: string): Promise<void> {
    const frame = JSON.parse(line) as Record<string, unknown>;
    this.sent.push(frame);
    if (typeof frame.id !== "number") return;
    if (frame.method === "initialize") this.response(frame.id, {});
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

  async kill(): Promise<void> {}

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
});
