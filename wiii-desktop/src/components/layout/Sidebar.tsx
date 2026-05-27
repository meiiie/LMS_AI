/**
 * Sidebar — conversation list with time groups, search, pins, domain badges.
 * Sprint 82b: Icon-rail collapsed mode (48px) with tooltips.
 * Full mode: 256px conversation list (unchanged).
 */
import { useState, useRef, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "motion/react";
import { Plus, Trash2, Settings, MessageSquare, Search, Pin, PinOff, Pencil, Shield, Building2, LogOut, User, Network, PlugZap, PanelLeftClose, PanelLeft, MoreHorizontal } from "lucide-react";
import { useChatStore } from "@/stores/chat-store";
import { useUIStore } from "@/stores/ui-store";
import { useDomainStore } from "@/stores/domain-store";
import { useOrgStore } from "@/stores/org-store";
import { useToastStore } from "@/stores/toast-store";
import { useAuthStore } from "@/stores/auth-store";
import { useSettingsStore } from "@/stores/settings-store";
import { ConnectionBadge } from "@/components/common/ConnectionBadge";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { WiiiAvatar } from "@/components/common/WiiiAvatar";
import { WorkspaceSelector } from "@/components/layout/WorkspaceSelector";
import { groupConversations, DOMAIN_BADGES } from "@/lib/conversation-groups";
import { getOrgIcon, getOrgDisplayName } from "@/lib/org-config";
import { sidebarItemEntry } from "@/lib/animations";
import { useReducedMotion, motionSafe } from "@/hooks/useReducedMotion";
import { useLongPress } from "@/hooks/useLongPress";
import { PERSONAL_ORG_ID } from "@/lib/constants";
import type { Conversation } from "@/api/types";

export function Sidebar() {
  const reduced = useReducedMotion();
  const {
    conversations,
    activeConversationId,
    searchQuery,
    createConversation,
    deleteConversation,
    renameConversation,
    setActiveConversation,
    setSearchQuery,
    pinConversation,
    unpinConversation,
  } = useChatStore();
  const { sidebarOpen, toggleSidebar, activeView, openSettings, openAdminPanel, openOrgManagerPanel, openSoulBridge, openWiiiConnect, navigateToChat } = useUIStore();
  const { isSystemAdmin, isOrgAdmin } = useOrgStore();
  const { activeDomainId } = useDomainStore();
  const { activeOrgId } = useOrgStore();
  const { addToast } = useToastStore();

  // Sprint 193: User profile + logout
  const { user, logout, isAuthenticated } = useAuthStore();
  const displayUserName = user?.name || useSettingsStore.getState().settings.display_name || "";

  const handleLogout = async () => {
    await logout();
    addToast("success", "Đã đăng xuất");
  };

  // Sprint 231h: User profile dropdown menu state
  const [userMenuOpen, setUserMenuOpen] = useState(false);

  // Close transient profile UI whenever the main surface changes. Otherwise
  // its backdrop can keep intercepting clicks after keyboard navigation.
  useEffect(() => {
    setUserMenuOpen(false);
  }, [activeView, sidebarOpen]);

  // Sprint 85: Debounce search to prevent O(n) filter on every keystroke
  const [localSearch, setLocalSearch] = useState(searchQuery);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  const handleSearchChange = useCallback((value: string) => {
    setLocalSearch(value);
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setSearchQuery(value), 300);
  }, [setSearchQuery]);

  // Sync local state if store search changes externally
  useEffect(() => {
    setLocalSearch(searchQuery);
  }, [searchQuery]);

  // Cleanup debounce on unmount
  useEffect(() => () => clearTimeout(debounceRef.current), []);

  // Sprint 156: Filter conversations by active org
  const orgFilterId = activeOrgId || PERSONAL_ORG_ID;
  const groups = groupConversations(conversations, searchQuery, orgFilterId);

  // Confirm delete state
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const handleConfirmDelete = () => {
    if (deleteTarget) {
      deleteConversation(deleteTarget);
      addToast("success", "Wiii đã quên cuộc trò chuyện này");
      setDeleteTarget(null);
    }
  };

  // Sprint 156: Create conversation with org context
  const currentOrg = useOrgStore.getState().activeOrg();
  const displayName = currentOrg ? getOrgDisplayName(currentOrg) : "Wiii Cá nhân";

  const handleNewChat = () => {
    const orgId = activeOrgId || undefined;
    createConversation(activeDomainId, orgId);
  };

  // Sprint 192: Helper for active icon styling
  const iconBtnClass = (isActive: boolean) =>
    `flex items-center justify-center w-9 h-9 rounded-lg transition-colors ${
      isActive
        ? "bg-[var(--accent)]/10 text-[var(--accent)]"
        : "text-text-secondary hover:text-text hover:bg-surface-tertiary"
    }`;

  // Collapsed icon-rail mode (48px)
  if (!sidebarOpen) {
    const CollapsedOrgIcon = getOrgIcon(activeOrgId || PERSONAL_ORG_ID);
    const isInAdminView = activeView !== "chat";

    return (
      <div className="flex flex-col h-full w-[50px] bg-surface-secondary border-r border-border items-center py-3 gap-1">
        {/* Sprint 192: Chat quick-switch when in admin views */}
        {isInAdminView ? (
          <>
            <button
              onClick={navigateToChat}
              className={iconBtnClass(false)}
              title="Quay lại trò chuyện"
              aria-label="Quay lại trò chuyện"
            >
              <MessageSquare size={18} />
            </button>
            <div className="w-6 border-t border-border my-1" />
          </>
        ) : (
          <>
            {/* Sprint 231: Open sidebar button — first icon in rail */}
            <button
              onClick={() => useUIStore.getState().setSidebarOpen(true)}
              className={iconBtnClass(false)}
              title="Mở sidebar"
              aria-label="Mở sidebar"
            >
              <PanelLeft size={18} />
            </button>

            {/* New chat */}
            <button
              onClick={handleNewChat}
              className={iconBtnClass(false)}
              title="Cuộc trò chuyện mới"
              aria-label="Tạo cuộc trò chuyện mới"
              data-wiii-id="new-chat-button"
            >
              <Plus size={18} />
            </button>

            {/* Search (visual only — opens sidebar) */}
            <button
              onClick={() => useUIStore.getState().setSidebarOpen(true)}
              className={iconBtnClass(false)}
              title="Tìm kiếm"
              aria-label="Mở tìm kiếm"
            >
              <Search size={18} />
            </button>
          </>
        )}

        {/* Spacer */}
        <div className="flex-1" />
        <span className="sr-only">{displayName}</span>
        <div
          className="mb-1 grid h-9 w-9 place-items-center rounded-lg border border-border bg-surface text-text-secondary"
          title={displayName}
          aria-label={displayName}
        >
          <CollapsedOrgIcon size={16} />
        </div>

        {/* Connection badge — compact */}
        <div className="mb-1" title="Trạng thái kết nối">
          <ConnectionBadge compact />
        </div>

        {/* Sprint 193: Logout button (compact) */}
        {isAuthenticated && (
          <button
            onClick={handleLogout}
            className="flex items-center justify-center w-9 h-9 rounded-lg text-text-secondary hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors"
            title="Đăng xuất"
            aria-label="Đăng xuất"
          >
            <LogOut size={18} />
          </button>
        )}

        {/* Sprint 192: Admin buttons with active highlighting */}
        {isSystemAdmin() && (
          <button
            onClick={openAdminPanel}
            className={iconBtnClass(activeView === "system-admin")}
            title="Quản trị hệ thống"
            aria-label="Mở bảng quản trị hệ thống"
          >
            <Shield size={18} />
          </button>
        )}
        {(isOrgAdmin() || isSystemAdmin()) && activeOrgId && activeOrgId !== "personal" && (
          <button
            onClick={() => openOrgManagerPanel(activeOrgId)}
            className={iconBtnClass(activeView === "org-admin")}
            title="Quản lý tổ chức"
            aria-label="Mở bảng quản lý tổ chức"
          >
            <Building2 size={18} />
          </button>
        )}

        {/* Wiii Connect */}
        <button
          onClick={openWiiiConnect}
          className={iconBtnClass(activeView === "wiii-connect")}
          title="Wiii Connect"
          aria-label="Mở Wiii Connect"
        >
          <PlugZap size={18} />
        </button>

        {/* Sprint 216: Soul Bridge */}
        <button
          onClick={openSoulBridge}
          className={iconBtnClass(activeView === "soul-bridge")}
          title="Mạng Linh Hồn"
          aria-label="Mở mạng linh hồn"
        >
          <Network size={18} />
        </button>

        {/* Settings */}
        <button
          onClick={openSettings}
          className={iconBtnClass(activeView === "settings")}
          title="Cài đặt"
          aria-label="Mở cài đặt"
        >
          <Settings size={18} />
        </button>
      </div>
    );
  }

  // Full expanded mode (256px)
  return (
    <div className="flex flex-col h-full w-[260px] bg-surface-secondary border-r border-border">
      {/* Sprint 231: Workspace selector + sidebar close button */}
      <div className="flex items-center gap-1 px-3 pt-3 pb-1">
        <div className="flex-1 min-w-0">
          <WorkspaceSelector />
        </div>
        <button
          onClick={toggleSidebar}
          className="shrink-0 p-1 rounded-md hover:bg-surface-tertiary transition-colors"
          title="Ẩn sidebar"
          aria-label="Ẩn sidebar"
          data-wiii-id="sidebar-toggle"
        >
          <PanelLeftClose size={16} className="text-text-tertiary" />
        </button>
      </div>

      {/* New chat button */}
      <div className="px-3 pb-1">
        <button
          onClick={handleNewChat}
          className="flex items-center gap-2 w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--surface)] text-text hover:bg-[var(--surface-tertiary)] active:scale-[0.985] transition-all duration-300 text-sm font-medium"
          aria-label="Tạo cuộc trò chuyện mới"
          data-wiii-id="new-chat-button"
        >
          <Plus size={16} />
          ✨ Trò chuyện mới
        </button>
      </div>

      {/* Search */}
      <div className="px-3 pb-2">
        <div className="relative">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-tertiary" />
          <input
            type="text"
            value={localSearch}
            onChange={(e) => handleSearchChange(e.target.value)}
            placeholder="Mình tìm gì nhỉ?"
            className="w-full pl-8 pr-3 py-1.5 rounded-lg border border-border bg-surface text-text text-xs focus:outline-none focus:ring-1 focus:ring-[var(--accent)] placeholder:text-text-tertiary"
            aria-label="Tìm kiếm cuộc trò chuyện"
            data-wiii-id="conversation-search"
          />
        </div>
      </div>

      {/* Conversation list with groups */}
      <div className="flex-1 overflow-y-auto px-2" role="list" aria-label="Danh sách cuộc trò chuyện">
        {groups.length === 0 ? (
          <div className="flex flex-col items-center text-center text-text-tertiary text-xs mt-8 px-4 gap-3">
            {!searchQuery && <WiiiAvatar state="idle" size={32} />}
            <span>
              {searchQuery
                ? "Mình không tìm thấy gì. Thử từ khác nhé?"
                : "Chưa có cuộc trò chuyện nào. Nhấn ✨ để bắt đầu nha!"}
            </span>
          </div>
        ) : (
          <div className="space-y-3">
            {groups.map((group) => (
              <div key={group.label}>
                {/* Group label */}
                <div className="px-3 py-1 text-[10px] font-semibold text-text-tertiary uppercase tracking-wider">
                  {group.label === "Ghim" && <Pin size={10} className="inline mr-1" />}
                  {group.label}
                </div>
                {/* Items */}
                <AnimatePresence initial={false}>
                  <div className="space-y-0.5">
                    {group.conversations.map((conv) => (
                      <motion.div
                        key={conv.id}
                        variants={motionSafe(reduced, sidebarItemEntry)}
                        initial={reduced ? false : "hidden"}
                        animate="visible"
                        exit={reduced ? undefined : "exit"}
                        layout={!reduced}
                      >
                        <ConversationItem
                          conv={conv}
                          isActive={conv.id === activeConversationId}
                          onSelect={() => setActiveConversation(conv.id)}
                          onDelete={() => setDeleteTarget(conv.id)}
                          onRename={(title) => {
                            renameConversation(conv.id, title);
                            addToast("success", "Wiii nhớ tên mới rồi!");
                          }}
                          onPin={() =>
                            conv.pinned
                              ? unpinConversation(conv.id)
                              : pinConversation(conv.id)
                          }
                        />
                      </motion.div>
                    ))}
                  </div>
                </AnimatePresence>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Sprint 231h: User profile footer — click avatar → dropdown menu (Claude.ai pattern) */}
      <div className="px-2 py-2 border-t border-border relative">
        <button
          onClick={openWiiiConnect}
          className={`mb-1 flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-sm transition-colors ${
            activeView === "wiii-connect"
              ? "bg-[var(--accent)]/10 text-[var(--accent)] font-medium"
              : "text-text-secondary hover:bg-surface-tertiary hover:text-text"
          }`}
          aria-current={activeView === "wiii-connect" ? "page" : undefined}
        >
          <PlugZap size={15} />
          <span className="truncate">Wiii Connect</span>
        </button>
        {isAuthenticated && (
          <>
            <button
              onClick={() => setUserMenuOpen(!userMenuOpen)}
              className="flex items-center gap-2.5 w-full px-2 py-2 rounded-lg hover:bg-surface-tertiary transition-colors"
              aria-expanded={userMenuOpen}
              aria-haspopup="menu"
            >
              {user?.avatar_url ? (
                <img
                  src={user.avatar_url}
                  alt={displayUserName || "Avatar"}
                  className="w-8 h-8 rounded-full shrink-0 ring-2 ring-border"
                  referrerPolicy="no-referrer"
                />
              ) : (
                <div className="w-8 h-8 rounded-full shrink-0 bg-[var(--accent)]/10 flex items-center justify-center ring-2 ring-border">
                  <User size={16} className="text-[var(--accent)]" />
                </div>
              )}
              <span className="flex-1 text-sm font-medium text-text truncate text-left">
                {displayUserName || "Người dùng"}
              </span>
              <MoreHorizontal size={16} className="shrink-0 text-text-tertiary" />
            </button>

            {/* Dropdown menu */}
            <AnimatePresence>
              {userMenuOpen && (
                <>
                  {/* Backdrop to close menu */}
                  <div
                    className="fixed inset-0 z-40"
                    onClick={() => setUserMenuOpen(false)}
                    aria-hidden="true"
                  />
                  <motion.div
                    initial={{ opacity: 0, y: 8, scale: 0.95 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, y: 8, scale: 0.95 }}
                    transition={{ duration: 0.15 }}
                    className="absolute bottom-full left-2 right-2 mb-1 z-50 bg-surface border border-border rounded-xl shadow-lg overflow-hidden"
                    role="menu"
                  >
                    <div className="py-1">
                      <button
                        onClick={() => { openSettings(); setUserMenuOpen(false); }}
                        className="flex items-center gap-2.5 w-full px-3 py-2 text-sm text-text-secondary hover:bg-surface-tertiary transition-colors"
                        role="menuitem"
                      >
                        <Settings size={15} />
                        Cài đặt
                      </button>
                      {isSystemAdmin() && (
                        <button
                          onClick={() => { openAdminPanel(); setUserMenuOpen(false); }}
                          className="flex items-center gap-2.5 w-full px-3 py-2 text-sm text-text-secondary hover:bg-surface-tertiary transition-colors"
                          role="menuitem"
                        >
                          <Shield size={15} />
                          Quản trị hệ thống
                        </button>
                      )}
                      {(isOrgAdmin() || isSystemAdmin()) && activeOrgId && activeOrgId !== "personal" && (
                        <button
                          onClick={() => { openOrgManagerPanel(activeOrgId); setUserMenuOpen(false); }}
                          className="flex items-center gap-2.5 w-full px-3 py-2 text-sm text-text-secondary hover:bg-surface-tertiary transition-colors"
                          role="menuitem"
                        >
                          <Building2 size={15} />
                          Quản lý tổ chức
                        </button>
                      )}
                      <button
                        onClick={() => { openWiiiConnect(); setUserMenuOpen(false); }}
                        className="flex items-center gap-2.5 w-full px-3 py-2 text-sm text-text-secondary hover:bg-surface-tertiary transition-colors"
                        role="menuitem"
                      >
                        <PlugZap size={15} />
                        Wiii Connect
                      </button>
                      <button
                        onClick={() => { openSoulBridge(); setUserMenuOpen(false); }}
                        className="flex items-center gap-2.5 w-full px-3 py-2 text-sm text-text-secondary hover:bg-surface-tertiary transition-colors"
                        role="menuitem"
                      >
                        <Network size={15} />
                        Mạng Linh Hồn
                      </button>
                      <div className="border-t border-border my-1" />
                      <button
                        onClick={() => { handleLogout(); setUserMenuOpen(false); }}
                        className="flex items-center gap-2.5 w-full px-3 py-2 text-sm text-red-600 hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors"
                        role="menuitem"
                      >
                        <LogOut size={15} />
                        Đăng xuất
                      </button>
                    </div>
                  </motion.div>
                </>
              )}
            </AnimatePresence>
          </>
        )}
      </div>

      {/* Delete confirmation dialog */}
      <ConfirmDialog
        open={deleteTarget !== null}
        title="Quên cuộc trò chuyện này?"
        message="Wiii sẽ quên cuộc trò chuyện này vĩnh viễn. Bạn chắc chứ?"
        confirmLabel="Quên đi"
        cancelLabel="Thôi, giữ lại"
        variant="danger"
        onConfirm={handleConfirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}

function ConversationItem({
  conv,
  isActive,
  onSelect,
  onDelete,
  onRename,
  onPin,
}: {
  conv: Conversation;
  isActive: boolean;
  onSelect: () => void;
  onDelete: () => void;
  onRename: (title: string) => void;
  onPin: () => void;
}) {
  const domainBadge = conv.domain_id ? DOMAIN_BADGES[conv.domain_id] : null;
  const msgCount = conv.message_count ?? conv.messages?.length ?? 0;

  // Inline rename state
  const [isEditing, setIsEditing] = useState(false);
  const [editTitle, setEditTitle] = useState(conv.title);
  const inputRef = useRef<HTMLInputElement>(null);

  // Touch context menu state
  const [touchMenuOpen, setTouchMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  const longPressHandlers = useLongPress(() => setTouchMenuOpen(true), { delay: 500 });

  // Close touch menu on outside click
  useEffect(() => {
    if (!touchMenuOpen) return;
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setTouchMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("touchstart", handleClick as EventListener);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("touchstart", handleClick as EventListener);
    };
  }, [touchMenuOpen]);

  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [isEditing]);

  const handleSubmitRename = () => {
    const trimmed = editTitle.trim();
    if (trimmed && trimmed !== conv.title) {
      onRename(trimmed);
    }
    setIsEditing(false);
  };

  const handleDoubleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    setEditTitle(conv.title);
    setIsEditing(true);
  };

  return (
    <div
      className={`group relative flex items-center gap-2 px-3 py-2 rounded-md cursor-pointer transition-all duration-150 text-sm ${
        isActive
          ? "bg-[var(--border-secondary)] text-text font-medium"
          : "hover:bg-[var(--surface-tertiary)] text-text-secondary"
      }`}
      onClick={onSelect}
      title={conv.summary || conv.title}
      role="listitem"
      aria-selected={isActive}
      {...longPressHandlers}
    >
      <MessageSquare size={14} className="shrink-0" />

      {isEditing ? (
        <input
          ref={inputRef}
          value={editTitle}
          onChange={(e) => setEditTitle(e.target.value)}
          onBlur={handleSubmitRename}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleSubmitRename();
            if (e.key === "Escape") setIsEditing(false);
          }}
          onClick={(e) => e.stopPropagation()}
          className="flex-1 bg-surface border border-border rounded px-1.5 py-0.5 text-sm text-text focus:outline-none focus:ring-1 focus:ring-[var(--accent)]"
        />
      ) : (
        <span
          className="flex-1 truncate"
          onDoubleClick={handleDoubleClick}
          title={conv.title}
        >
          {conv.title}
        </span>
      )}

      {/* Domain badge */}
      {domainBadge && !isEditing && (
        <span className="shrink-0 text-[9px] font-bold px-1 py-0.5 rounded bg-surface-tertiary text-text-tertiary">
          {domainBadge}
        </span>
      )}

      {/* Message count */}
      {msgCount > 0 && !isEditing && (
        <span className="shrink-0 text-[10px] text-text-tertiary opacity-0 group-hover:opacity-100 transition-opacity">
          {msgCount}
        </span>
      )}

      {/* Rename button (hover — desktop) */}
      {!isEditing && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            setEditTitle(conv.title);
            setIsEditing(true);
          }}
          className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-surface-tertiary transition-all"
          title="Đặt tên mới"
          aria-label="Đặt tên mới cho cuộc trò chuyện"
        >
          <Pencil size={12} />
        </button>
      )}

      {/* Pin/Unpin button (hover — desktop) */}
      {!isEditing && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onPin();
          }}
          className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-surface-tertiary transition-all"
          title={conv.pinned ? "Bỏ ghim" : "Ghim"}
          aria-label={conv.pinned ? "Bỏ ghim" : "Ghim cuộc trò chuyện"}
        >
          {conv.pinned ? <PinOff size={12} /> : <Pin size={12} />}
        </button>
      )}

      {/* Delete button (hover — desktop) */}
      {!isEditing && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-red-100 dark:hover:bg-red-900/30 hover:text-red-600 transition-all"
          title="Quên cuộc trò chuyện này"
          aria-label="Xoá cuộc trò chuyện"
        >
          <Trash2 size={12} />
        </button>
      )}

      {/* Touch context menu (long-press — touch devices) */}
      {touchMenuOpen && !isEditing && (
        <div
          ref={menuRef}
          className="absolute right-0 top-full z-50 mt-1 w-40 rounded-lg border border-[var(--border)] bg-[var(--surface)] shadow-lg py-1 text-xs"
          onClick={(e) => e.stopPropagation()}
          role="menu"
          aria-label="Thao tác cuộc trò chuyện"
        >
          <button
            className="flex items-center gap-2 w-full px-3 py-2 hover:bg-[var(--surface-tertiary)] text-text-secondary transition-colors"
            onClick={() => {
              setEditTitle(conv.title);
              setIsEditing(true);
              setTouchMenuOpen(false);
            }}
            role="menuitem"
          >
            <Pencil size={12} /> Đặt tên mới
          </button>
          <button
            className="flex items-center gap-2 w-full px-3 py-2 hover:bg-[var(--surface-tertiary)] text-text-secondary transition-colors"
            onClick={() => {
              onPin();
              setTouchMenuOpen(false);
            }}
            role="menuitem"
          >
            {conv.pinned ? <PinOff size={12} /> : <Pin size={12} />}
            {conv.pinned ? "Bỏ ghim" : "Ghim"}
          </button>
          <button
            className="flex items-center gap-2 w-full px-3 py-2 hover:bg-red-100 dark:hover:bg-red-900/30 text-red-600 transition-colors"
            onClick={() => {
              onDelete();
              setTouchMenuOpen(false);
            }}
            role="menuitem"
          >
            <Trash2 size={12} /> Xoá
          </button>
        </div>
      )}
    </div>
  );
}
