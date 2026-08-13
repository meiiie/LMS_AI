/**
 * Neko Chill mode shell — v0 skeleton (T204, #886).
 *
 * No-login local-agent surface. This component mounts INSTEAD of the cloud
 * app (see ModeGate in App.tsx), so no auth/org/backend init can run while
 * the mode is active (FR-002). Full chat surface arrives with Phase 3;
 * this skeleton proves the seam: mode entry, agent detection, mode exit.
 */
import { useEffect, useState } from "react";
import { useModeStore } from "./stores/mode-store";

export interface DetectedAgent {
  id: string;
  name: string;
  binary: string;
  version: string | null;
  found: boolean;
}

/** Rust-side detection; resolves empty in browser dev (no Tauri runtime). */
async function detectAgents(): Promise<DetectedAgent[]> {
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    return await invoke<DetectedAgent[]>("neko_detect_agents");
  } catch {
    return [];
  }
}

export default function NekoChillApp() {
  const { setMode } = useModeStore();
  const [agents, setAgents] = useState<DetectedAgent[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    void detectAgents().then((found) => {
      if (!cancelled) setAgents(found);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="flex flex-col h-screen bg-surface text-text-primary">
      <header className="flex items-center justify-between px-6 py-4 border-b border-border">
        <div>
          <h1 className="text-lg font-semibold">Neko Chill</h1>
          <p className="text-sm text-text-tertiary">
            Agent chạy ngay trên máy bạn — không cần tài khoản.
          </p>
        </div>
        <button
          type="button"
          className="text-sm text-text-tertiary hover:text-text-primary transition-colors"
          onClick={() => void setMode("wiii")}
        >
          ← Về chế độ Wiii
        </button>
      </header>

      <main className="flex-1 overflow-y-auto px-6 py-6">
        <h2 className="text-sm font-medium text-text-tertiary uppercase tracking-wide mb-3">
          Agent trên máy này
        </h2>
        {agents === null ? (
          <p className="text-sm text-text-tertiary">Đang dò tìm agent…</p>
        ) : (
          <ul className="space-y-2" data-testid="agent-list">
            {agents.map((agent) => (
              <li
                key={agent.id}
                className="flex items-center justify-between rounded-lg border border-border px-4 py-3"
              >
                <div>
                  <span className="font-medium">{agent.name}</span>
                  {agent.found && agent.version ? (
                    <span className="ml-2 text-xs text-text-tertiary">{agent.version}</span>
                  ) : null}
                </div>
                <span
                  className={
                    agent.found ? "text-xs text-green-500" : "text-xs text-text-tertiary"
                  }
                >
                  {agent.found ? "Sẵn sàng" : "Chưa cài"}
                </span>
              </li>
            ))}
            {agents.length === 0 ? (
              <li className="text-sm text-text-tertiary">
                Chưa phát hiện agent ACP nào. Cài{" "}
                <span className="font-medium">neko-core</span> (neko.holilihu.online) hoặc{" "}
                <span className="font-medium">Gemini CLI</span> rồi mở lại chế độ này.
              </li>
            ) : null}
          </ul>
        )}
        <p className="mt-6 text-xs text-text-tertiary">
          Phiên trò chuyện với agent sẽ có ở bản kế tiếp — khung này xác nhận chế độ
          hoạt động hoàn toàn không cần đăng nhập.
        </p>
      </main>
    </div>
  );
}
