import { Activity, Bot, Command, Folder, HardDrive, Settings2, X } from "lucide-react";
import type { DriverConfigOption } from "../drivers/types";
import type { NekoSession } from "../stores/neko-session-store";

interface SessionInspectorProps {
  session: NekoSession;
  onClose: () => void;
  onSetConfigOption: (optionId: string, value: string | boolean) => void;
  onInsertCommand: (text: string) => void;
}

function currentLabel(option: DriverConfigOption): string {
  if (typeof option.currentValue === "boolean") return option.currentValue ? "Bật" : "Tắt";
  return option.choices?.find((choice) => choice.value === option.currentValue)?.label
    ?? option.currentValue;
}

export function SessionInspector({
  session,
  onClose,
  onSetConfigOption,
  onInsertCommand,
}: SessionInspectorProps) {
  const controlsDisabled =
    session.status !== "idle" ||
    Boolean(session.pendingPermission) ||
    Boolean(session.pendingControlId);

  return (
    <aside
      className="absolute inset-y-0 right-0 z-30 flex w-[286px] shrink-0 flex-col border-l border-[var(--nk-border)] bg-[var(--nk-sidebar)] shadow-[-12px_0_30px_rgba(0,0,0,0.06)] xl:static xl:shadow-none"
      aria-label="Thông tin phiên"
      data-testid="session-inspector"
    >
      <header className="flex h-11 shrink-0 items-center justify-between border-b border-[var(--nk-border)] px-3.5">
        <span className="flex items-center gap-2 text-[12.5px] font-medium text-[var(--nk-text)]">
          <Settings2 aria-hidden="true" className="h-3.5 w-3.5 text-[var(--nk-text-3)]" />
          Thông tin phiên
        </span>
        <button
          type="button"
          className="rounded-md p-1 text-[var(--nk-text-3)] hover:bg-[var(--nk-overlay)] hover:text-[var(--nk-text)]"
          aria-label="Đóng thông tin phiên"
          onClick={onClose}
        >
          <X aria-hidden="true" className="h-3.5 w-3.5" />
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        <section className="rounded-xl border border-[var(--nk-border)] bg-[var(--nk-composer)] p-3">
          <h2 className="mb-3 truncate text-[13px] font-medium text-[var(--nk-text)]" title={session.title}>
            {session.title}
          </h2>
          <dl className="space-y-2.5 text-[11.5px]">
            <div className="flex gap-2.5">
              <Folder aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--nk-text-3)]" />
              <div className="min-w-0">
                <dt className="text-[10px] uppercase tracking-wide text-[var(--nk-ghost)]">Dự án</dt>
                <dd className="truncate text-[var(--nk-text-2)]" title={session.workspace?.path}>
                  {session.workspace?.name ?? "Chưa gắn dự án"}
                </dd>
                {session.workspace ? (
                  <dd className="mt-0.5 break-all text-[10px] leading-4 text-[var(--nk-ghost)]">
                    {session.workspace.path}
                  </dd>
                ) : null}
              </div>
            </div>
            <div className="flex gap-2.5">
              <Bot aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--nk-text-3)]" />
              <div className="min-w-0">
                <dt className="text-[10px] uppercase tracking-wide text-[var(--nk-ghost)]">Agent</dt>
                <dd className="truncate text-[var(--nk-text-2)]">{session.agentName}</dd>
              </div>
            </div>
            <div className="flex gap-2.5">
              <Activity aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--nk-text-3)]" />
              <div className="min-w-0">
                <dt className="text-[10px] uppercase tracking-wide text-[var(--nk-ghost)]">Trạng thái</dt>
                <dd className="truncate text-[var(--nk-text-2)]">
                  {session.status === "streaming"
                    ? "Đang làm việc"
                    : session.status === "dispatching"
                      ? "Đang lưu yêu cầu"
                    : session.status === "connecting"
                      ? "Đang kết nối"
                      : session.status === "idle"
                        ? "Sẵn sàng"
                        : session.status === "exited"
                          ? "Runtime đã dừng"
                          : "Có lỗi"}
                </dd>
              </div>
            </div>
            <div className="flex gap-2.5">
              <HardDrive aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--nk-text-3)]" />
              <div className="min-w-0">
                <dt className="text-[10px] uppercase tracking-wide text-[var(--nk-ghost)]">Model / profile</dt>
                <dd className="text-[var(--nk-text-2)]">
                  {session.launchProfile
                    ? `${session.launchProfile.provider} · ${session.launchProfile.model ?? session.launchProfile.id}`
                    : "Theo khả năng agent báo cáo"}
                </dd>
              </div>
            </div>
          </dl>
        </section>

        <section className="mt-3 rounded-xl border border-[var(--nk-border)] bg-[var(--nk-composer)] p-3">
          <h2 className="mb-2 text-[10.5px] font-semibold uppercase tracking-wide text-[var(--nk-text-3)]">
            Điều khiển phiên
          </h2>
          {session.controls.length ? (
            <div className="space-y-2">
              {session.controls.map((option) => (
                <label key={option.id} className="block">
                  <span className="mb-1 flex items-center justify-between gap-2 text-[11px] text-[var(--nk-text-3)]">
                    <span>{option.label}</span>
                    <span className="truncate text-[var(--nk-ghost)]">{currentLabel(option)}</span>
                  </span>
                  {option.kind === "boolean" ? (
                    <input
                      type="checkbox"
                      checked={Boolean(option.currentValue)}
                      disabled={controlsDisabled}
                      onChange={(event) => onSetConfigOption(option.id, event.target.checked)}
                    />
                  ) : (
                    <select
                      className="w-full rounded-md border border-[var(--nk-border)] bg-[var(--nk-raised)] px-2 py-1.5 text-[11.5px] text-[var(--nk-text)] focus:outline-none disabled:opacity-50"
                      value={String(option.currentValue)}
                      disabled={controlsDisabled}
                      onChange={(event) => onSetConfigOption(option.id, event.target.value)}
                    >
                      {(option.choices ?? []).map((choice) => (
                        <option key={choice.value} value={choice.value}>{choice.label}</option>
                      ))}
                    </select>
                  )}
                </label>
              ))}
            </div>
          ) : session.launchProfile ? (
            <p className="text-[11px] leading-4 text-[var(--nk-text-3)]">
              Model được khóa khi Neko khởi động bằng profile <strong>{session.launchProfile.id}</strong>.
              Tạo phiên mới để chọn model khác.
            </p>
          ) : (
            <p className="text-[11px] leading-4 text-[var(--nk-text-3)]">
              Agent chưa báo cáo điều khiển nào cho phiên này.
            </p>
          )}
        </section>

        <section className="mt-3 rounded-xl border border-[var(--nk-border)] bg-[var(--nk-composer)] p-3">
          <h2 className="mb-2 flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-wide text-[var(--nk-text-3)]">
            <Command aria-hidden="true" className="h-3 w-3" />
            Lệnh agent · {session.commands.length}
          </h2>
          {session.commands.length ? (
            <ul className="space-y-1.5">
              {session.commands.map((command) => (
                <li key={command.name}>
                  <button
                    type="button"
                    className="w-full rounded-lg px-1.5 py-1 text-left text-[11px] leading-4 transition-colors hover:bg-[var(--nk-overlay)]"
                    title="Chèn lệnh vào ô soạn"
                    onClick={() => onInsertCommand(`/${command.name}${command.inputHint ? " " : ""}`)}
                  >
                    <code className="text-[var(--nk-text-2)]">/{command.name}</code>
                    <span className="ml-1 text-[var(--nk-ghost)]">{command.description}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[11px] leading-4 text-[var(--nk-text-3)]">
              Agent này chưa công bố slash command qua ACP.
            </p>
          )}
        </section>
      </div>
      <footer className="border-t border-[var(--nk-border)] px-3.5 py-2.5 text-[10px] leading-4 text-[var(--nk-ghost)]">
        Transcript lưu trên máy. Phiên khôi phục có thể dùng runtime mới nếu agent không hỗ trợ resume.
      </footer>
    </aside>
  );
}
