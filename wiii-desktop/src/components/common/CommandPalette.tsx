/**
 * Command Palette — Ctrl+K quick-access overlay.
 * Sprint 81: cmdk-style command palette for conversations + actions.
 */
import { useState, useEffect, useRef, useMemo } from "react";
import {
  Search,
  MessageSquare,
  Plus,
  Settings,
  Moon,
  Sun,
  Sidebar,
  Sparkles,
  PlugZap,
} from "lucide-react";
import { useChatStore } from "@/stores/chat-store";
import { useUIStore } from "@/stores/ui-store";
import { useSettingsStore } from "@/stores/settings-store";
import { useDomainStore } from "@/stores/domain-store";
import { useOrgStore } from "@/stores/org-store";
import { setTheme } from "@/lib/theme";

interface CommandItem {
  id: string;
  label: string;
  description?: string;
  icon: React.ReactNode;
  action: () => void;
  category: "action" | "conversation";
}

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
}

export function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const { conversations, setActiveConversation, createConversation } = useChatStore();
  const { toggleSidebar, openSettings, openWiiiConnect } = useUIStore();
  const theme = useSettingsStore((s) => s.settings.theme);
  const { activeDomainId } = useDomainStore();
  const { activeOrgId } = useOrgStore();

  // Build items list
  const items = useMemo(() => {
    const actions: CommandItem[] = [
      {
        id: "new-chat",
        label: "Cuộc trò chuyện mới",
        description: "Tạo cuộc trò chuyện mới",
        icon: <Plus size={16} />,
        action: () => { createConversation(activeDomainId, activeOrgId || undefined); onClose(); },
        category: "action",
      },
      {
        id: "toggle-sidebar",
        label: "Ẩn/hiện thanh bên",
        description: "Ctrl+B",
        icon: <Sidebar size={16} />,
        action: () => { toggleSidebar(); onClose(); },
        category: "action",
      },
      {
        id: "open-settings",
        label: "Mở cài đặt",
        description: "Ctrl+,",
        icon: <Settings size={16} />,
        action: () => { openSettings(); onClose(); },
        category: "action",
      },
      {
        id: "open-wiii-connect",
        label: "Wiii Connect",
        description: "Quản lý kết nối",
        icon: <PlugZap size={16} />,
        action: () => { openWiiiConnect(); onClose(); },
        category: "action",
      },
      {
        id: "toggle-theme",
        label: theme === "dark" ? "Chuyển sang chế độ sáng" : "Chuyển sang chế độ tối",
        description: "Đổi giao diện",
        icon: theme === "dark" ? <Sun size={16} /> : <Moon size={16} />,
        action: () => {
          const newTheme = theme === "dark" ? "light" : "dark";
          useSettingsStore.getState().updateSettings({ theme: newTheme });
          setTheme(newTheme);
          onClose();
        },
        category: "action",
      },
      {
        id: "toggle-thinking",
        label: "Ẩn/hiện suy luận",
        description: "Ctrl+/",
        icon: <Sparkles size={16} />,
        action: () => {
          const current = useSettingsStore.getState().settings.show_thinking;
          useSettingsStore.getState().updateSettings({ show_thinking: !current });
          onClose();
        },
        category: "action",
      },
    ];

    const convItems: CommandItem[] = conversations.map((conv) => ({
      id: `conv-${conv.id}`,
      label: conv.title,
      description: conv.organization_id
        ? `${conv.organization_id} · ${conv.domain_id ?? ""}`
        : conv.domain_id ?? undefined,
      icon: <MessageSquare size={16} />,
      action: () => { setActiveConversation(conv.id); onClose(); },
      category: "conversation" as const,
    }));

    return [...actions, ...convItems];
  }, [conversations, theme, createConversation, toggleSidebar, openSettings, openWiiiConnect, setActiveConversation, onClose, activeDomainId, activeOrgId]);

  // Filter by query
  const filtered = useMemo(() => {
    if (!query.trim()) return items;
    const q = query.trim().toLowerCase();
    return items.filter(
      (item) =>
        item.label.toLowerCase().includes(q) ||
        (item.description?.toLowerCase().includes(q))
    );
  }, [items, query]);

  // Reset on open
  useEffect(() => {
    if (open) {
      setQuery("");
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  // Keep selected index in bounds
  useEffect(() => {
    if (selectedIndex >= filtered.length) {
      setSelectedIndex(Math.max(0, filtered.length - 1));
    }
  }, [filtered.length, selectedIndex]);

  // Scroll selected item into view
  useEffect(() => {
    if (listRef.current) {
      const selected = listRef.current.children[selectedIndex] as HTMLElement;
      selected?.scrollIntoView({ block: "nearest" });
    }
  }, [selectedIndex]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((i) => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      filtered[selectedIndex]?.action();
    } else if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    }
  };

  if (!open) return null;

  // Separate categories
  const actionItems = filtered.filter((i) => i.category === "action");
  const convItems = filtered.filter((i) => i.category === "conversation");

  let globalIndex = 0;

  return (
    <div
      className="fixed inset-0 z-[80] flex items-start justify-center pt-[15vh] bg-black/40 animate-fade-in"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Bảng lệnh"
    >
      <div
        className="bg-surface rounded-xl shadow-2xl w-full max-w-md mx-4 border border-border animate-scale-in overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search input */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-border">
          <Search size={16} className="text-text-tertiary shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIndex(0);
            }}
            onKeyDown={handleKeyDown}
            placeholder="Tìm kiếm lệnh, cuộc trò chuyện..."
            className="flex-1 bg-transparent text-sm text-text placeholder:text-text-tertiary focus:outline-none"
          />
          <kbd className="text-[10px] text-text-tertiary bg-surface-tertiary px-1.5 py-0.5 rounded">
            ESC
          </kbd>
        </div>

        {/* Results */}
        <div ref={listRef} className="max-h-[300px] overflow-y-auto py-1">
          {filtered.length === 0 && (
            <div className="text-center text-text-tertiary text-sm py-8">
              Không tìm thấy kết quả
            </div>
          )}

          {actionItems.length > 0 && (
            <>
              <div className="px-4 py-1 text-[10px] font-semibold text-text-tertiary uppercase tracking-wider">
                Thao tác
              </div>
              {actionItems.map((item) => {
                const idx = globalIndex++;
                return (
                  <button
                    key={item.id}
                    onClick={item.action}
                    onMouseEnter={() => setSelectedIndex(idx)}
                    className={`w-full flex items-center gap-3 px-4 py-2.5 text-sm transition-colors ${
                      idx === selectedIndex
                        ? "bg-[var(--accent-light)] text-[var(--accent)]"
                        : "text-text-secondary hover:bg-surface-tertiary"
                    }`}
                  >
                    <span className="shrink-0 text-text-tertiary">{item.icon}</span>
                    <span className="flex-1 text-left truncate">{item.label}</span>
                    {item.description && (
                      <span className="text-[11px] text-text-tertiary">{item.description}</span>
                    )}
                  </button>
                );
              })}
            </>
          )}

          {convItems.length > 0 && (
            <>
              <div className="px-4 py-1 text-[10px] font-semibold text-text-tertiary uppercase tracking-wider mt-1">
                Cuộc trò chuyện
              </div>
              {convItems.map((item) => {
                const idx = globalIndex++;
                return (
                  <button
                    key={item.id}
                    onClick={item.action}
                    onMouseEnter={() => setSelectedIndex(idx)}
                    className={`w-full flex items-center gap-3 px-4 py-2.5 text-sm transition-colors ${
                      idx === selectedIndex
                        ? "bg-[var(--accent-light)] text-[var(--accent)]"
                        : "text-text-secondary hover:bg-surface-tertiary"
                    }`}
                  >
                    <span className="shrink-0 text-text-tertiary">{item.icon}</span>
                    <span className="flex-1 text-left truncate">{item.label}</span>
                    {item.description && (
                      <span className="text-[9px] font-bold px-1 py-0.5 rounded bg-surface-tertiary text-text-tertiary">
                        {item.description}
                      </span>
                    )}
                  </button>
                );
              })}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center gap-4 px-4 py-2 border-t border-border text-[10px] text-text-tertiary">
          <span>↑↓ điều hướng</span>
          <span>↵ chọn</span>
          <span>esc đóng</span>
        </div>
      </div>
    </div>
  );
}
