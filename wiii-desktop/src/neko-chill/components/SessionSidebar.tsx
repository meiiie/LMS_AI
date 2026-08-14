import { useMemo, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Folder,
  History,
  Plus,
  Search,
  X,
} from "lucide-react";
import {
  useNekoSessionStore,
  type NekoSession,
} from "../stores/neko-session-store";
import { sessionSearchableText } from "../command-items";

interface SessionGroup {
  key: string;
  name: string;
  path: string | null;
  updatedAt: number;
  sessions: NekoSession[];
}

function groupSessions(sessions: NekoSession[], query: string): SessionGroup[] {
  const normalized = query.trim().toLocaleLowerCase("vi");
  const visible = normalized
    ? sessions.filter((session) => sessionSearchableText(session).includes(normalized))
    : sessions;
  const groups = new Map<string, SessionGroup>();
  for (const session of visible) {
    const workspacePath = session.workspace?.path;
    const key = workspacePath
      ? (/^(?:[A-Za-z]:[\\/]|\\\\)/.test(workspacePath)
          ? workspacePath.toLocaleLowerCase("en-US")
          : workspacePath)
      : "__legacy__";
    const existing = groups.get(key) ?? {
      key,
      name: session.workspace?.name ?? "Phiên chưa gắn dự án",
      path: session.workspace?.path ?? null,
      updatedAt: 0,
      sessions: [],
    };
    existing.sessions.push(session);
    existing.updatedAt = Math.max(existing.updatedAt, session.updatedAt);
    groups.set(key, existing);
  }
  return [...groups.values()]
    .map((group) => ({
      ...group,
      sessions: group.sessions.sort((a, b) => b.updatedAt - a.updatedAt),
    }))
    .sort((a, b) => {
      if (a.key === "__legacy__") return 1;
      if (b.key === "__legacy__") return -1;
      return b.updatedAt - a.updatedAt;
    });
}

function statusClass(session: NekoSession): string {
  if (session.status === "streaming") return "bg-[var(--nk-accent)] animate-pulse";
  if (session.status === "idle") return "bg-[var(--nk-success)]";
  if (session.status === "error") return "bg-[var(--nk-danger)]";
  return "bg-[var(--nk-ghost)]";
}

export function SessionSidebar() {
  const sessionsById = useNekoSessionStore((state) => state.sessions);
  const activeSessionId = useNekoSessionStore((state) => state.activeSessionId);
  const { deleteSession, setActiveSession } = useNekoSessionStore();
  const [query, setQuery] = useState("");
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set());
  const sessions = useMemo(() => Object.values(sessionsById), [sessionsById]);
  const groups = useMemo(() => groupSessions(sessions, query), [query, sessions]);

  return (
    <aside
      className="flex w-[276px] shrink-0 flex-col border-r border-[var(--nk-border)] bg-[var(--nk-sidebar)]"
      data-testid="session-sidebar"
    >
      <div className="flex h-9 items-center justify-between px-3 pt-1 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-[var(--nk-ghost)]">
        <span>Dự án và phiên</span>
        <span className="font-normal tabular-nums">{sessions.length}</span>
      </div>
      <div className="px-2 pb-2">
        <button
          type="button"
          className="flex h-8 w-full items-center gap-2 rounded-lg px-2.5 text-[12.5px] font-medium text-[var(--nk-text-2)] transition-colors hover:bg-[var(--nk-overlay)] hover:text-[var(--nk-text)]"
          onClick={() => setActiveSession(null)}
          data-testid="new-session"
        >
          <Plus aria-hidden="true" className="h-3.5 w-3.5 text-[var(--nk-text-3)]" />
          Phiên mới
        </button>
        <label className="mt-1 flex h-8 items-center gap-2 rounded-lg bg-[var(--nk-inset)] px-2.5 text-[var(--nk-text-3)] focus-within:ring-1 focus-within:ring-[var(--nk-border-strong)]">
          <Search aria-hidden="true" className="h-3.5 w-3.5 shrink-0" />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="min-w-0 flex-1 bg-transparent text-[12px] text-[var(--nk-text)] placeholder:text-[var(--nk-ghost)] focus:outline-none"
            placeholder="Tìm phiên, dự án…"
            aria-label="Tìm phiên Neko Chill"
          />
          {query ? (
            <button
              type="button"
              aria-label="Xoá tìm kiếm"
              className="rounded p-0.5 hover:bg-[var(--nk-overlay)]"
              onClick={() => setQuery("")}
            >
              <X aria-hidden="true" className="h-3 w-3" />
            </button>
          ) : (
            <span className="text-[9px] text-[var(--nk-ghost)]">Lọc</span>
          )}
        </label>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {groups.length === 0 ? (
          <p className="px-2.5 py-3 text-[12px] leading-5 text-[var(--nk-text-3)]">
            {query ? "Không tìm thấy phiên phù hợp." : "Chưa có phiên nào."}
          </p>
        ) : (
          <div className="space-y-1" data-testid="project-session-tree">
            {groups.map((group) => {
              const isCollapsed = collapsed.has(group.key) && !query;
              const GroupIcon = group.path ? Folder : History;
              return (
                <section key={group.key} data-testid={`session-group-${group.key}`}>
                  <button
                    type="button"
                    className="flex h-[30px] w-full items-center gap-1.5 rounded-md px-2 text-left text-[12.5px] text-[var(--nk-text-2)] transition-colors hover:bg-[var(--nk-overlay)] hover:text-[var(--nk-text)]"
                    aria-expanded={!isCollapsed}
                    title={group.path ?? "Các phiên được tạo trước khi có workspace"}
                    onClick={() =>
                      setCollapsed((current) => {
                        const next = new Set(current);
                        if (next.has(group.key)) next.delete(group.key);
                        else next.add(group.key);
                        return next;
                      })
                    }
                  >
                    {isCollapsed ? (
                      <ChevronRight aria-hidden="true" className="h-3 w-3 shrink-0" />
                    ) : (
                      <ChevronDown aria-hidden="true" className="h-3 w-3 shrink-0" />
                    )}
                    <GroupIcon aria-hidden="true" className="h-3.5 w-3.5 shrink-0" />
                    <span className="min-w-0 flex-1 truncate font-medium">{group.name}</span>
                    <span className="text-[10px] tabular-nums text-[var(--nk-ghost)]">
                      {group.sessions.length}
                    </span>
                  </button>
                  {!isCollapsed ? (
                    <div className="space-y-px pb-1">
                      {group.sessions.map((session) => (
                        <div
                          key={session.id}
                          className={`nk-session-row group flex h-8 items-center rounded-md pl-7 pr-1 transition-colors ${
                            session.id === activeSessionId
                              ? "bg-[var(--nk-item-active)]"
                              : "hover:bg-[var(--nk-overlay)]"
                          }`}
                        >
                          <button
                            type="button"
                            className="flex min-w-0 flex-1 items-center gap-2 text-left"
                            aria-current={session.id === activeSessionId ? "page" : undefined}
                            aria-label={`Mở phiên ${session.title}`}
                            onClick={() => setActiveSession(session.id)}
                          >
                            <span
                              aria-hidden="true"
                              className={`h-1.5 w-1.5 shrink-0 rounded-full ${statusClass(session)}`}
                            />
                            <span className="min-w-0 flex-1 truncate text-[12.5px] font-normal text-[var(--nk-text)]">
                              {session.title}
                            </span>
                          </button>
                          <button
                            type="button"
                            className="nk-row-action rounded p-1 text-[var(--nk-ghost)] transition-colors hover:text-[var(--nk-danger)]"
                            title="Xoá phiên"
                            aria-label={`Xoá phiên ${session.title}`}
                            onClick={() => void deleteSession(session.id)}
                          >
                            <X aria-hidden="true" className="h-3 w-3" />
                          </button>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </section>
              );
            })}
          </div>
        )}
      </div>
      <div className="border-t border-[var(--nk-border)] px-3 py-2 text-[10.5px] text-[var(--nk-ghost)]">
        {sessions.length} phiên · lưu cục bộ
      </div>
    </aside>
  );
}
