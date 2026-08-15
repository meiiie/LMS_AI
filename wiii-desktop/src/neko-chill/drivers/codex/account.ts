import { APP_VERSION } from "@/lib/constants";
import {
  AcpJsonRpcClient,
  UnsupportedMethodError,
  type AcpTransport,
} from "../acp/client";

type JsonRecord = Record<string, unknown>;

export interface CodexAccountSummary {
  authenticated: boolean;
  requiresOpenaiAuth: boolean;
  accountType: "chatgpt" | "apiKey" | "amazonBedrock" | null;
  planType: string | null;
}

export interface CodexLoginChallenge {
  loginId: string;
  authUrl: string;
}

interface LoginCompletion {
  success: boolean;
  error: string | null;
}

function record(value: unknown): JsonRecord | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as JsonRecord
    : null;
}

export class CodexAccountSession {
  private readonly client: AcpJsonRpcClient;
  private disposed = false;
  private readonly completed = new Map<string, LoginCompletion>();
  private readonly waiters = new Map<
    string,
    { resolve: (result: LoginCompletion) => void; reject: (error: Error) => void }
  >();

  constructor(transport: AcpTransport) {
    this.client = new AcpJsonRpcClient(transport, {
      onAgentRequest: async (method) => {
        throw new UnsupportedMethodError(`Account bootstrap không hỗ trợ ${method}`);
      },
      onNotification: (method, params) => this.handleNotification(method, params),
      onProtocolError: () => {},
    });
    transport.onExit(() => {
      for (const [, waiter] of this.waiters) {
        waiter.reject(new Error("Codex App Server đã dừng trong lúc đăng nhập"));
      }
      this.waiters.clear();
    });
  }

  async start(): Promise<CodexAccountSummary> {
    try {
      await this.client.request("initialize", {
        clientInfo: {
          name: "wiii-workbench",
          title: "Wiii Workbench",
          version: APP_VERSION,
        },
        capabilities: { experimentalApi: true, requestAttestation: false },
      });
      await this.client.notify("initialized", {});
      return await this.read();
    } catch (cause) {
      await this.dispose();
      throw cause;
    }
  }

  async read(): Promise<CodexAccountSummary> {
    const result = record(await this.client.request("account/read", {
      refreshToken: false,
    }));
    const account = record(result?.account);
    const accountType =
      account?.type === "chatgpt" ||
      account?.type === "apiKey" ||
      account?.type === "amazonBedrock"
        ? account.type
        : null;
    return {
      authenticated: accountType !== null,
      requiresOpenaiAuth: result?.requiresOpenaiAuth === true,
      accountType,
      planType: typeof account?.planType === "string" ? account.planType : null,
    };
  }

  async beginChatGptLogin(): Promise<CodexLoginChallenge> {
    const result = record(await this.client.request("account/login/start", {
      type: "chatgpt",
      codexStreamlinedLogin: true,
      useHostedLoginSuccessPage: true,
      appBrand: "codex",
    }));
    if (
      result?.type !== "chatgpt" ||
      typeof result.loginId !== "string" ||
      typeof result.authUrl !== "string"
    ) {
      throw new Error("Codex không trả về URL đăng nhập hợp lệ");
    }
    return { loginId: result.loginId, authUrl: result.authUrl };
  }

  async waitForLogin(loginId: string): Promise<void> {
    const known = this.completed.get(loginId);
    if (known) {
      this.completed.delete(loginId);
      if (!known.success) throw new Error(known.error ?? "Đăng nhập Codex thất bại");
      return;
    }
    const result = await new Promise<LoginCompletion>((resolve, reject) => {
      this.waiters.set(loginId, { resolve, reject });
    });
    if (!result.success) throw new Error(result.error ?? "Đăng nhập Codex thất bại");
  }

  async dispose(): Promise<void> {
    if (this.disposed) return;
    this.disposed = true;
    await this.client.dispose();
  }

  private handleNotification(method: string, value: unknown): void {
    if (method !== "account/login/completed") return;
    const params = record(value);
    const loginId = typeof params?.loginId === "string" ? params.loginId : null;
    if (!loginId) return;
    const result: LoginCompletion = {
      success: params?.success === true,
      error: typeof params?.error === "string" ? params.error : null,
    };
    const waiter = this.waiters.get(loginId);
    if (waiter) {
      this.waiters.delete(loginId);
      waiter.resolve(result);
    } else {
      this.completed.set(loginId, result);
    }
  }
}
