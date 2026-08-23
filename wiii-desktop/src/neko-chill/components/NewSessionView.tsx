import { useEffect, useMemo, useState } from "react";
import { Bot, Check, FolderOpen, LoaderCircle, ShieldCheck } from "lucide-react";
import {
  loadAgentProfiles,
  useNekoAgentStore,
  type AgentLaunchProfile,
  type DetectedAgent,
} from "../stores/neko-agent-store";
import { useNekoSessionStore } from "../stores/neko-session-store";
import { getNekoControlClient } from "@/neko/control-client";
import {
  CodexAccountSession,
  getCodexAccountBootstrapOwner,
  type CodexAccountSummary,
} from "../drivers/codex/account";
import {
  chooseWorkspaceFolder,
  type WorkspaceRef,
} from "../workspace";
import {
  codexBootstrapIdentity,
} from "../codex-bootstrap-identity";

function recentWorkspaces(): WorkspaceRef[] {
  const seen = new Set<string>();
  return Object.values(useNekoSessionStore.getState().sessions)
    .sort((a, b) => b.updatedAt - a.updatedAt)
    .flatMap((session) => {
      const workspace = session.workspace;
      if (!workspace || seen.has(workspace.path)) return [];
      seen.add(workspace.path);
      return [workspace];
    });
}

export function NewSessionView() {
  const { agents, isLoading, error: discoveryError, detect } = useNekoAgentStore();
  const createSession = useNekoSessionStore((state) => state.createSession);
  const sessions = useNekoSessionStore((state) => state.sessions);
  const [workspace, setWorkspace] = useState<WorkspaceRef | null>(null);
  const [profiles, setProfiles] = useState<AgentLaunchProfile[]>([]);
  const [profileLoading, setProfileLoading] = useState(false);
  const [selectedProfileId, setSelectedProfileId] = useState("");
  const [startingAgentId, setStartingAgentId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [codexAccount, setCodexAccount] = useState<CodexAccountSummary | null>(null);
  const [codexAccountState, setCodexAccountState] = useState<
    "idle" | "checking" | "signed-out" | "signed-in" | "logging-in" | "error"
  >("idle");
  const [codexLoginUrl, setCodexLoginUrl] = useState<string | null>(null);
  const [codexBootstrapAttempt, setCodexBootstrapAttempt] = useState(0);
  const codexAccountOwner = getCodexAccountBootstrapOwner();
  const recent = useMemo(() => recentWorkspaces(), [sessions]);
  const neko = agents.find((agent) => agent.id === "neko" && agent.found);
  const codex = agents.find((agent) => agent.id === "codex" && agent.found);

  useEffect(() => {
    let cancelled = false;
    if (!workspace || !neko) {
      setProfiles([]);
      setSelectedProfileId("");
      setProfileLoading(false);
      return;
    }
    setProfileLoading(true);
    void loadAgentProfiles(neko, workspace.path)
      .then((items) => {
        if (cancelled) return;
        setProfiles(items);
        const active = items.find((item) => item.active) ?? items[0];
        setSelectedProfileId(active?.id ?? "");
      })
      .catch((cause) => {
        if (cancelled) return;
        setProfiles([]);
        setSelectedProfileId("");
        setError(cause instanceof Error ? cause.message : String(cause));
      })
      .finally(() => {
        if (!cancelled) setProfileLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [neko?.found, workspace?.path]);

  useEffect(() => {
    let cancelled = false;
    let bootstrapSession: CodexAccountSession | null = null;
    setCodexAccount(null);
    setCodexLoginUrl(null);
    if (!workspace || !codex?.found) {
      setCodexAccountState("idle");
      void codexAccountOwner.release().catch(() => {
        // Ownership remains in the module-level owner and the next bootstrap
        // retries cleanup before it can launch another App Server.
      });
      return;
    }

    setCodexAccountState("checking");
    const bootstrapIdentity = codexBootstrapIdentity(workspace.path);
    void codexAccountOwner
      .replace(async () => {
        const { transport } = await getNekoControlClient().spawnProvider({
          providerId: "codex",
          // Retry the same logical caller identity until Neko proves the previous
          // start terminal while every proven attempt receives a fresh Run.
          clientSessionId: bootstrapIdentity.clientSessionId,
          clientRunId: bootstrapIdentity.clientRunId,
          workspacePath: workspace.path,
        });
        return new CodexAccountSession(transport);
      })
      .then(async (session) => {
        bootstrapSession = session;
        if (cancelled) {
          await codexAccountOwner.release(session);
          return;
        }
        const account = await session.start();
        if (cancelled) return;
        setCodexAccount(account);
        setCodexAccountState(account.authenticated ? "signed-in" : "signed-out");
      })
      .catch(async (cause) => {
        const failed = bootstrapSession;
        let reported = cause;
        if (failed) {
          try {
            await codexAccountOwner.release(failed);
          } catch (cleanup) {
            const detail = cleanup instanceof Error ? cleanup.message : String(cleanup);
            const original = cause instanceof Error ? cause.message : String(cause);
            reported = new Error(`${original}; cleanup vẫn chưa hoàn tất: ${detail}`);
          }
        }
        if (cancelled) return;
        setCodexAccountState("error");
        setError(reported instanceof Error ? reported.message : String(reported));
      });

    return () => {
      cancelled = true;
      if (bootstrapSession) {
        void codexAccountOwner.release(bootstrapSession).catch(() => {
          // A failed cleanup stays owned and is retried before replacement.
        });
      }
    };
  }, [codex?.found, workspace?.path, codexBootstrapAttempt]);

  const chooseWorkspace = async () => {
    const selected = await chooseWorkspaceFolder();
    if (selected) {
      setWorkspace(selected);
      setError(null);
    }
  };

  const start = async (agent: DetectedAgent) => {
    if (!workspace || !agent.found) return;
    const profile =
      agent.id === "neko"
        ? profiles.find((item) => item.id === selectedProfileId) ?? null
        : null;
    setStartingAgentId(agent.id);
    setError(null);
    try {
      await createSession(agent, workspace, profile);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setStartingAgentId(null);
    }
  };

  const loginCodex = async () => {
    const session = codexAccountOwner.current();
    if (!session) return;
    setCodexAccountState("logging-in");
    setError(null);
    try {
      const challenge = await session.beginChatGptLogin();
      setCodexLoginUrl(challenge.authUrl);
      const { open } = await import("@tauri-apps/plugin-shell");
      await open(challenge.authUrl);
      await session.waitForLogin(challenge.loginId);
      const account = await session.read();
      setCodexAccount(account);
      setCodexLoginUrl(null);
      setCodexAccountState(account.authenticated ? "signed-in" : "signed-out");
    } catch (cause) {
      setCodexAccountState("error");
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  };

  return (
    <main className="min-w-0 flex-1 overflow-y-auto" data-testid="new-session-view">
      <div className="mx-auto w-full max-w-[760px] px-7 pb-12 pt-[8vh]">
        <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-[var(--nk-accent)]">
          Phiên cục bộ mới
        </p>
        <h1
          className="text-[27px] font-normal tracking-[-0.025em] text-[var(--nk-text)]"
          style={{ fontFamily: "var(--font-serif)" }}
        >
          Bạn muốn Neko làm việc ở đâu?
        </h1>
        <p className="mt-2 max-w-[600px] text-[13px] leading-5 text-[var(--nk-text-2)]">
          Thư mục dự án là ranh giới làm việc của agent. Neko Chill không tự dùng thư mục
          home và không gửi dữ liệu phiên lên Wiii Cloud.
        </p>

        <section className="mt-7">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-[11.5px] font-semibold uppercase tracking-wide text-[var(--nk-text-3)]">
              1 · Chọn dự án
            </h2>
            {workspace ? (
              <span className="flex items-center gap-1 text-[11px] text-[var(--nk-success)]">
                <Check aria-hidden="true" className="h-3 w-3" /> Đã chọn
              </span>
            ) : null}
          </div>
          <button
            type="button"
            className={`flex min-h-[62px] w-full items-center gap-3 rounded-xl border px-4 text-left transition-colors ${
              workspace
                ? "border-[var(--nk-border-strong)] bg-[var(--nk-raised)]"
                : "border-dashed border-[var(--nk-border-strong)] bg-[var(--nk-composer)] hover:bg-[var(--nk-raised)]"
            }`}
            onClick={() => void chooseWorkspace()}
            data-testid="choose-workspace"
          >
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--nk-overlay-strong)] text-[var(--nk-text-2)]">
              <FolderOpen aria-hidden="true" className="h-4 w-4" />
            </span>
            <span className="min-w-0 flex-1">
              <strong className="block truncate text-[13.5px] font-medium text-[var(--nk-text)]">
                {workspace?.name ?? "Mở một thư mục dự án"}
              </strong>
              <small className="block truncate text-[11.5px] text-[var(--nk-text-3)]">
                {workspace?.path ?? "Neko chỉ nhận quyền trong thư mục bạn chọn"}
              </small>
            </span>
            <span className="text-[11px] text-[var(--nk-text-3)]">
              {workspace ? "Đổi" : "Chọn thư mục"}
            </span>
          </button>
          {!workspace && recent.length ? (
            <div className="mt-2 flex flex-wrap gap-1.5" aria-label="Dự án gần đây">
              {recent.slice(0, 6).map((item) => (
                <button
                  key={item.path}
                  type="button"
                  title={item.path}
                  className="max-w-[210px] truncate rounded-md bg-[var(--nk-overlay)] px-2.5 py-1 text-[11.5px] text-[var(--nk-text-2)] hover:bg-[var(--nk-overlay-strong)]"
                  onClick={() => setWorkspace(item)}
                >
                  {item.name}
                </button>
              ))}
            </div>
          ) : null}
        </section>

        <section className="mt-7">
          <h2 className="mb-2 text-[11.5px] font-semibold uppercase tracking-wide text-[var(--nk-text-3)]">
            2 · Chọn agent và model
          </h2>
          {!workspace ? (
            <div className="flex min-h-[74px] items-center gap-3 rounded-xl border border-dashed border-[var(--nk-border)] px-4 text-[12px] leading-5 text-[var(--nk-text-3)]">
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-[var(--nk-inset)]">
                <Bot aria-hidden="true" className="h-3.5 w-3.5" />
              </span>
              Chọn một dự án trước. Neko Chill sẽ chỉ sau đó đọc các agent,
              profile và model thật sự có trên máy bạn.
            </div>
          ) : discoveryError ? (
            <div
              role="alert"
              className="rounded-xl border border-[var(--nk-danger)]/30 bg-[var(--nk-composer)] p-4 text-[12.5px] leading-5 text-[var(--nk-danger)]"
            >
              <p>{discoveryError}</p>
              <button
                type="button"
                className="mt-3 rounded-lg border border-[var(--nk-border-strong)] px-2.5 py-1.5 text-[11.5px] text-[var(--nk-text-2)] hover:bg-[var(--nk-raised)]"
                onClick={() => void detect()}
              >
                Thử dò lại
              </button>
            </div>
          ) : isLoading ? (
            <p className="flex items-center gap-2 py-4 text-[13px] text-[var(--nk-text-3)]">
              <LoaderCircle aria-hidden="true" className="h-4 w-4 animate-spin" /> Đang dò agent…
            </p>
          ) : (
            <div className="space-y-2" data-testid="agent-list">
              {agents.map((agent) => {
                const selectedProfile = profiles.find((item) => item.id === selectedProfileId);
                return (
                  <article
                    key={agent.id}
                    className="rounded-xl border border-[var(--nk-border)] bg-[var(--nk-composer)] p-3.5"
                  >
                    <div className="flex items-center gap-3">
                      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--nk-inset)] text-[var(--nk-text-2)]">
                        <Bot aria-hidden="true" className="h-4 w-4" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <strong className="block text-[13.5px] font-medium text-[var(--nk-text)]">
                          {agent.name}
                        </strong>
                        <span className="block truncate text-[11px] text-[var(--nk-text-3)]">
                          {agent.found
                            ? agent.version
                            : agent.availability === "host_unsupported"
                              ? "Máy này chưa có cơ chế cô lập process được Wiii chấp thuận"
                              : "Chưa cài trên máy này"}
                        </span>
                      </div>
                      <button
                        type="button"
                        className="rounded-lg bg-[var(--nk-inverse)] px-3 py-1.5 text-[12px] font-medium text-[var(--nk-on-inverse)] disabled:cursor-not-allowed disabled:opacity-30"
                        disabled={
                          !agent.found
                          || !workspace
                          || startingAgentId !== null
                          || (agent.id === "neko" && profileLoading)
                          || (agent.id === "codex" && codexAccountState !== "signed-in")
                        }
                        onClick={() => void start(agent)}
                        data-testid={`start-${agent.id}`}
                      >
                        {startingAgentId === agent.id ? "Đang mở…" : "Bắt đầu"}
                      </button>
                    </div>
                    {agent.id === "neko" && agent.found ? (
                      <div className="mt-3 border-t border-[var(--nk-border)] pt-3">
                        <label className="flex items-center gap-3">
                          <span className="text-[11.5px] text-[var(--nk-text-3)]">Profile / model</span>
                          {profileLoading ? (
                            <span className="text-[11px] text-[var(--nk-ghost)]">Đang đọc profiles…</span>
                          ) : profiles.length ? (
                            <select
                              value={selectedProfileId}
                              onChange={(event) => setSelectedProfileId(event.target.value)}
                              className="min-w-0 flex-1 rounded-lg border border-[var(--nk-border)] bg-[var(--nk-raised)] px-2.5 py-1.5 text-[12px] text-[var(--nk-text)] focus:outline-none"
                              aria-label="Chọn profile và model Neko Core"
                            >
                              {profiles.map((profile) => (
                                <option key={profile.id} value={profile.id}>
                                  {profile.id} · {profile.model ?? profile.provider}
                                  {profile.active ? " · đang dùng" : ""}
                                </option>
                              ))}
                            </select>
                          ) : (
                            <span className="text-[11px] text-[var(--nk-text-3)]">
                              Dùng cấu hình mặc định của Neko
                            </span>
                          )}
                        </label>
                        {selectedProfile ? (
                          <p className="mt-1.5 pl-[94px] text-[10.5px] text-[var(--nk-ghost)]">
                            Provider {selectedProfile.provider} · {selectedProfile.model ?? "model do profile quyết định"}
                          </p>
                        ) : null}
                      </div>
                    ) : null}
                    {agent.id === "codex" && agent.found ? (
                      <div className="mt-3 border-t border-[var(--nk-border)] pt-3">
                        <div className="flex items-center justify-between gap-3">
                          <div className="min-w-0">
                            <p className="text-[11.5px] font-medium text-[var(--nk-text-2)]">
                              {codexAccountState === "checking"
                                ? "Đang kiểm tra tài khoản Codex…"
                                : codexAccountState === "signed-in"
                                  ? `Codex đã sẵn sàng${codexAccount?.planType ? ` · ${codexAccount.planType}` : ""}`
                                  : codexAccountState === "logging-in"
                                    ? "Hoàn tất đăng nhập trong trình duyệt…"
                                    : "Cần kết nối tài khoản Codex"}
                            </p>
                            <p className="mt-0.5 text-[10.5px] text-[var(--nk-ghost)]">
                              Codex sở hữu token, model và chi phí; Wiii không đọc hoặc lưu thông tin đăng nhập.
                            </p>
                          </div>
                          {codexAccountState === "signed-out" || codexAccountState === "error" ? (
                            <button
                              type="button"
                              className="shrink-0 rounded-lg border border-[var(--nk-border-strong)] px-2.5 py-1.5 text-[11.5px] text-[var(--nk-text-2)] hover:bg-[var(--nk-raised)]"
                              onClick={() => {
                                if (codexAccountState === "error") {
                                  setError(null);
                                  setCodexBootstrapAttempt((attempt) => attempt + 1);
                                } else {
                                  void loginCodex();
                                }
                              }}
                            >
                              {codexAccountState === "error" ? "Thử lại" : "Đăng nhập"}
                            </button>
                          ) : null}
                        </div>
                        {codexLoginUrl && codexAccountState === "logging-in" ? (
                          <button
                            type="button"
                            className="mt-2 max-w-full truncate text-left text-[10.5px] text-[var(--nk-accent)] underline underline-offset-2"
                            title={codexLoginUrl}
                            onClick={() => void import("@tauri-apps/plugin-shell").then(({ open }) => open(codexLoginUrl))}
                          >
                            Mở lại trang đăng nhập Codex
                          </button>
                        ) : null}
                      </div>
                    ) : null}
                  </article>
                );
              })}
              {agents.length === 0 ? (
                <div className="rounded-xl border border-dashed border-[var(--nk-border-strong)] p-4 text-[12.5px] leading-5 text-[var(--nk-text-3)]">
                  Chưa phát hiện agent ACP. Cài Neko Core hoặc Gemini CLI rồi mở lại chế độ này.
                </div>
              ) : null}
            </div>
          )}
          {error ? <p className="mt-3 text-[12px] text-[var(--nk-danger)]">{error}</p> : null}
        </section>

        <p className="mt-7 flex items-center gap-2 text-[10.5px] text-[var(--nk-ghost)]">
          <ShieldCheck aria-hidden="true" className="h-3.5 w-3.5" />
          Profile chỉ được đọc để khởi động phiên; Neko Chill không sửa cấu hình Neko.
        </p>
      </div>
    </main>
  );
}
