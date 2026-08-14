import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowUp,
  Bot,
  ChevronDown,
  Command,
  Folder,
  Gauge,
  LockKeyhole,
  Search,
  Settings2,
  Square,
} from "lucide-react";
import type { DriverConfigOption } from "../drivers/types";
import type { NekoSession } from "../stores/neko-session-store";
import {
  CLIENT_COMMANDS,
  type ClientCommandName,
} from "../command-items";

interface SlashSuggestion {
  name: string;
  description: string;
  source: "Neko Chill" | "Agent";
  inputHint?: string;
  clientCommand?: ClientCommandName;
}

export interface ComposerInsertRequest {
  text: string;
  token: number;
}

interface NekoComposerProps {
  session: NekoSession;
  disabled: boolean;
  streaming: boolean;
  onSend: (text: string) => void;
  onCancel: () => void;
  onSetConfigOption: (optionId: string, value: string | boolean) => void;
  onClientCommand: (command: ClientCommandName) => void;
  insertRequest?: ComposerInsertRequest | null;
}

function controlLabel(option: DriverConfigOption): string {
  if (typeof option.currentValue === "boolean") return option.currentValue ? "Bật" : "Tắt";
  return option.choices?.find((choice) => choice.value === option.currentValue)?.label
    ?? option.currentValue;
}

function ControlSelect({
  option,
  disabled,
  pending,
  onChange,
}: {
  option: DriverConfigOption;
  disabled: boolean;
  pending: boolean;
  onChange(value: string): void;
}) {
  const Icon = option.category === "mode" ? Gauge : Bot;
  return (
    <label
      className="relative flex h-7 max-w-[190px] items-center gap-1.5 rounded-md px-1.5 text-[11.5px] text-[var(--nk-text-3)] transition-colors hover:bg-[var(--nk-overlay)]"
      title={option.description ?? option.label}
    >
      <Icon aria-hidden="true" className="h-3.5 w-3.5 shrink-0" />
      <span className="truncate">{pending ? "Đang đổi…" : controlLabel(option)}</span>
      <ChevronDown aria-hidden="true" className="h-3 w-3 shrink-0" />
      <select
        aria-label={option.label}
        className="absolute inset-0 cursor-pointer opacity-0 disabled:cursor-not-allowed"
        value={String(option.currentValue)}
        disabled={disabled || pending}
        onChange={(event) => onChange(event.target.value)}
      >
        {(option.choices ?? []).map((choice) => (
          <option key={choice.value} value={choice.value}>{choice.label}</option>
        ))}
      </select>
    </label>
  );
}

export function NekoComposer({
  session,
  disabled,
  streaming,
  onSend,
  onCancel,
  onSetConfigOption,
  onClientCommand,
  insertRequest,
}: NekoComposerProps) {
  const [draft, setDraft] = useState("");
  const [highlight, setHighlight] = useState(0);
  const [slashDismissed, setSlashDismissed] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const mode = session.controls.find((option) => option.category === "mode" && option.kind === "select");
  const model = session.controls.find((option) => option.category === "model" && option.kind === "select");
  const controlsDisabled =
    session.status !== "idle" || disabled || streaming || Boolean(session.pendingPermission);
  const slashQuery = draft.startsWith("/") && !draft.includes("\n")
    ? draft.slice(1).toLocaleLowerCase("vi")
    : null;
  const suggestions = useMemo<SlashSuggestion[]>(() => {
    if (slashQuery === null) return [];
    const agent: SlashSuggestion[] = session.commands.map((command) => ({
      ...command,
      source: "Agent" as const,
    }));
    return [...CLIENT_COMMANDS, ...agent]
      .filter((command) =>
        !slashQuery
        || command.name.toLocaleLowerCase("vi").includes(slashQuery)
        || command.description.toLocaleLowerCase("vi").includes(slashQuery),
      )
      .slice(0, 8);
  }, [session.commands, slashQuery]);
  const slashOpen = slashQuery !== null && !slashDismissed && !controlsDisabled;

  useEffect(() => {
    if (!insertRequest) return;
    setDraft(insertRequest.text);
    setSlashDismissed(true);
    requestAnimationFrame(() => textareaRef.current?.focus());
  }, [insertRequest?.token]);

  const runSuggestion = (suggestion: SlashSuggestion) => {
    if (suggestion.clientCommand) {
      setDraft("");
      setSlashDismissed(true);
      onClientCommand(suggestion.clientCommand);
      return;
    }
    setDraft(`/${suggestion.name}${suggestion.inputHint ? " " : ""}`);
    setSlashDismissed(true);
    requestAnimationFrame(() => textareaRef.current?.focus());
  };

  const submit = () => {
    const text = draft.trim();
    if (!text || controlsDisabled) return;
    const local = CLIENT_COMMANDS.find((command) => `/${command.name}` === text);
    setDraft("");
    setSlashDismissed(false);
    if (local?.clientCommand) onClientCommand(local.clientCommand);
    else onSend(text);
  };

  return (
    <div className="shrink-0 px-5 pb-4 pt-1">
      <div className="relative mx-auto w-full max-w-[780px]">
        {slashOpen ? (
          <div
            className="absolute bottom-[calc(100%-2px)] left-3 right-3 z-30 overflow-hidden rounded-xl border border-[var(--nk-border-strong)] bg-[var(--nk-composer)] shadow-[0_14px_35px_rgba(0,0,0,0.12)]"
            role="listbox"
            aria-label="Lệnh slash"
            data-testid="slash-command-menu"
          >
            <div className="flex items-center gap-2 border-b border-[var(--nk-border)] px-3 py-2 text-[10.5px] text-[var(--nk-text-3)]">
              <Command aria-hidden="true" className="h-3.5 w-3.5" />
              Lệnh cho phiên này
              <span className="ml-auto">↑↓ chọn · Enter chèn</span>
            </div>
            <div className="max-h-[280px] overflow-y-auto p-1.5">
              {suggestions.length ? suggestions.map((suggestion, index) => (
                <button
                  key={`${suggestion.source}:${suggestion.name}`}
                  type="button"
                  role="option"
                  aria-selected={index === highlight}
                  className={`flex min-h-10 w-full items-center gap-3 rounded-lg px-2.5 text-left ${
                    index === highlight ? "bg-[var(--nk-item-active)]" : "hover:bg-[var(--nk-overlay)]"
                  }`}
                  onMouseEnter={() => setHighlight(index)}
                  onClick={() => runSuggestion(suggestion)}
                >
                  <code className="w-[120px] shrink-0 truncate text-[12px] text-[var(--nk-text)]">
                    /{suggestion.name}
                  </code>
                  <span className="min-w-0 flex-1 truncate text-[11.5px] text-[var(--nk-text-3)]">
                    {suggestion.description}
                  </span>
                  <span className="rounded bg-[var(--nk-inset)] px-1.5 py-0.5 text-[9.5px] text-[var(--nk-ghost)]">
                    {suggestion.source}
                  </span>
                </button>
              )) : (
                <p className="px-3 py-4 text-center text-[11.5px] text-[var(--nk-text-3)]">
                  Không có lệnh phù hợp.
                </p>
              )}
            </div>
          </div>
        ) : null}

        <div className="mx-3 -mb-2 flex h-10 items-center gap-2 rounded-t-xl border border-b-0 border-[var(--nk-border)] bg-[var(--nk-sidebar)] px-3 pb-2 text-[11.5px] text-[var(--nk-text-3)]">
          <Folder aria-hidden="true" className="h-3.5 w-3.5 shrink-0" />
          <span className="min-w-0 flex-1 truncate" title={session.workspace?.path}>
            {session.workspace?.name ?? "Chưa gắn dự án"}
          </span>
          {!session.workspace ? (
            <button
              type="button"
              className="rounded px-1.5 py-0.5 text-[var(--nk-accent)] hover:bg-[var(--nk-overlay)]"
              onClick={() => onClientCommand("project")}
            >
              Chọn thư mục
            </button>
          ) : (
            <span className="max-w-[50%] truncate text-[10px] text-[var(--nk-ghost)]">
              {session.workspace.path}
            </span>
          )}
        </div>

        <div className="relative rounded-[14px] border border-[var(--nk-border-strong)] bg-[var(--nk-composer)] p-2.5 shadow-[0_4px_18px_rgba(30,30,28,0.05)] focus-within:ring-2 focus-within:ring-[var(--nk-focus-soft)]">
          <textarea
            ref={textareaRef}
            className="max-h-44 min-h-[48px] w-full resize-none bg-transparent px-1 pt-0.5 text-[13.5px] leading-[20px] text-[var(--nk-text)] placeholder:text-[var(--nk-ghost)] focus:outline-none"
            rows={Math.min(draft.split("\n").length || 1, 6)}
            placeholder={session.workspace ? "Nhắn cho agent… Gõ / để xem lệnh" : "Gắn dự án trước khi nhắn…"}
            value={draft}
            disabled={controlsDisabled || !session.workspace}
            data-testid="neko-composer-input"
            onChange={(event) => {
              setDraft(event.target.value);
              setHighlight(0);
              setSlashDismissed(false);
            }}
            onKeyDown={(event) => {
              if (slashOpen && suggestions.length) {
                if (event.key === "ArrowDown") {
                  event.preventDefault();
                  setHighlight((current) => (current + 1) % suggestions.length);
                  return;
                }
                if (event.key === "ArrowUp") {
                  event.preventDefault();
                  setHighlight((current) => (current - 1 + suggestions.length) % suggestions.length);
                  return;
                }
                if (event.key === "Tab" || (event.key === "Enter" && !event.shiftKey)) {
                  event.preventDefault();
                  runSuggestion(suggestions[Math.min(highlight, suggestions.length - 1)]);
                  return;
                }
              }
              if (event.key === "Escape" && slashOpen) {
                event.preventDefault();
                setSlashDismissed(true);
                return;
              }
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                submit();
              }
            }}
          />
          <div className="mt-1.5 flex min-h-7 items-center gap-1 text-[11.5px]">
            <span className="flex h-7 max-w-[150px] items-center gap-1.5 truncate rounded-md px-1.5 text-[var(--nk-text-3)]" title={session.agentName}>
              <Bot aria-hidden="true" className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate">{session.agentName}</span>
            </span>
            {mode ? (
              <ControlSelect
                option={mode}
                disabled={controlsDisabled}
                pending={session.pendingControlId === mode.id}
                onChange={(value) => onSetConfigOption(mode.id, value)}
              />
            ) : null}
            {model ? (
              <ControlSelect
                option={model}
                disabled={controlsDisabled}
                pending={session.pendingControlId === model.id}
                onChange={(value) => onSetConfigOption(model.id, value)}
              />
            ) : session.launchProfile ? (
              <button
                type="button"
                className="flex h-7 max-w-[190px] items-center gap-1.5 rounded-md px-1.5 text-[11.5px] text-[var(--nk-text-3)] hover:bg-[var(--nk-overlay)]"
                title={`Model ${session.launchProfile.model ?? session.launchProfile.id} được chọn khi khởi động. Tạo phiên mới để đổi.`}
                onClick={() => onClientCommand("info")}
              >
                <LockKeyhole aria-hidden="true" className="h-3.5 w-3.5 shrink-0" />
                <span className="truncate">{session.launchProfile.model ?? session.launchProfile.id}</span>
              </button>
            ) : null}
            <button
              type="button"
              className="flex h-7 items-center gap-1.5 rounded-md px-1.5 text-[11.5px] text-[var(--nk-text-3)] hover:bg-[var(--nk-overlay)]"
              title="Tìm phiên (Ctrl+K)"
              onClick={() => onClientCommand("search")}
            >
              <Search aria-hidden="true" className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              className="flex h-7 items-center gap-1.5 rounded-md px-1.5 text-[11.5px] text-[var(--nk-text-3)] hover:bg-[var(--nk-overlay)]"
              title="Thông tin phiên"
              onClick={() => onClientCommand("info")}
            >
              <Settings2 aria-hidden="true" className="h-3.5 w-3.5" />
            </button>
            <div className="flex-1" />
            {streaming ? (
              <button
                type="button"
                className="flex h-[28px] w-[28px] items-center justify-center rounded-full bg-[var(--nk-danger-soft)] text-[var(--nk-danger)] transition-colors hover:bg-[var(--nk-danger)] hover:text-[var(--nk-on-inverse)]"
                onClick={onCancel}
                title="Dừng"
                aria-label="Dừng lượt đang chạy"
                data-testid="neko-cancel"
              >
                <Square aria-hidden="true" className="h-2.5 w-2.5 fill-current" />
              </button>
            ) : (
              <button
                type="button"
                className="flex h-[28px] w-[28px] items-center justify-center rounded-full bg-[var(--nk-inverse)] text-[var(--nk-on-inverse)] disabled:opacity-30"
                disabled={controlsDisabled || !session.workspace || !draft.trim()}
                onClick={submit}
                title="Gửi"
                aria-label="Gửi tin nhắn"
                data-testid="neko-send"
              >
                <ArrowUp aria-hidden="true" className="h-3 w-3" strokeWidth={1.8} />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
