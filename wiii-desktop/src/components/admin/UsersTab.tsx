/**
 * Users tab - search + table + pagination + action menu.
 * System admin semantics:
 * - platform_role is the primary Wiii account type
 * - legacy role is shown only as compatibility/debug context
 */
import { useState, useEffect, useRef, useCallback } from "react";
import {
  Search,
  ChevronLeft,
  ChevronRight,
  MoreHorizontal,
} from "lucide-react";

import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { useAuthStore } from "@/stores/auth-store";
import { useAdminStore } from "@/stores/admin-store";

const PAGE_SIZE = 20;

const PLATFORM_ROLE_LABELS: Record<string, string> = {
  user: "Wiii User",
  platform_admin: "Platform Admin",
};

const LEGACY_ROLE_LABELS: Record<string, string> = {
  student: "Compatibility: Student",
  teacher: "Compatibility: Teacher",
  admin: "Compatibility: Admin",
};

const PLATFORM_ROLE_OPTIONS = [
  { value: "user", label: "Wiii User" },
  { value: "platform_admin", label: "Platform Admin" },
] as const;

function getPlatformRoleLabel(platformRole?: string): string {
  if (!platformRole) return PLATFORM_ROLE_LABELS.user;
  return PLATFORM_ROLE_LABELS[platformRole] || platformRole;
}

function getLegacyRoleLabel(role?: string): string {
  if (!role) return "Compatibility: unknown";
  return LEGACY_ROLE_LABELS[role] || `Compatibility: ${role}`;
}

export function UsersTab() {
  const {
    users,
    usersTotal,
    usersPage,
    usersSort,
    loading,
    fetchUsers,
    deactivateUser,
    reactivateUser,
    changeUserPlatformRole,
  } = useAdminStore();
  const currentUserId = useAuthStore((state) => state.user?.id);
  const [localSearch, setLocalSearch] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  const [openMenuUserId, setOpenMenuUserId] = useState<string | null>(null);
  const [showRoleSubmenu, setShowRoleSubmenu] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  const [confirmTarget, setConfirmTarget] = useState<{
    userId: string;
    name: string;
  } | null>(null);

  useEffect(() => {
    fetchUsers({ page: 0 });
  }, [fetchUsers]);

  const handleSearch = useCallback(
    (value: string) => {
      setLocalSearch(value);
      clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => {
        fetchUsers({ search: value, page: 0 });
      }, 300);
    },
    [fetchUsers],
  );

  useEffect(() => () => clearTimeout(debounceRef.current), []);

  useEffect(() => {
    if (!openMenuUserId) return;
    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setOpenMenuUserId(null);
        setShowRoleSubmenu(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [openMenuUserId]);

  const handleSort = (column: string) => {
    const currentBase = usersSort.replace(/_(?:asc|desc)$/, "");
    const currentDirection = usersSort.endsWith("_asc") ? "asc" : "desc";
    const nextSort =
      currentBase === column && currentDirection === "desc"
        ? `${column}_asc`
        : `${column}_desc`;
    fetchUsers({ sort: nextSort, page: 0 });
  };

  const handleDeactivate = (userId: string, userName: string) => {
    setOpenMenuUserId(null);
    setShowRoleSubmenu(false);
    setConfirmTarget({ userId, name: userName });
  };

  const handleConfirmDeactivate = async () => {
    if (!confirmTarget) return;
    await deactivateUser(confirmTarget.userId);
    setConfirmTarget(null);
  };

  const handleReactivate = async (userId: string) => {
    setOpenMenuUserId(null);
    setShowRoleSubmenu(false);
    await reactivateUser(userId);
  };

  const handlePlatformRoleChange = async (
    userId: string,
    platformRole: "user" | "platform_admin",
  ) => {
    setOpenMenuUserId(null);
    setShowRoleSubmenu(false);
    await changeUserPlatformRole(userId, platformRole);
  };

  const totalPages = Math.ceil(usersTotal / PAGE_SIZE);
  const startIdx = usersPage * PAGE_SIZE + 1;
  const endIdx = Math.min((usersPage + 1) * PAGE_SIZE, usersTotal);

  return (
    <div className="space-y-4">
      <div className="flex gap-3">
        <div className="relative flex-1">
          <Search
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-text-tertiary"
          />
          <input
            type="text"
            value={localSearch}
            onChange={(event) => handleSearch(event.target.value)}
            placeholder="Tìm theo tên, email..."
            className="w-full pl-9 pr-3 py-2 rounded-lg border border-border bg-surface-secondary text-text text-sm focus:outline-none focus:ring-1 focus:ring-[var(--accent)]"
          />
        </div>
        <select
          onChange={(event) =>
            fetchUsers({ platformRole: event.target.value, page: 0 })
          }
          className="px-3 py-2 rounded-lg border border-border bg-surface-secondary text-text text-sm focus:outline-none"
          defaultValue=""
        >
          <option value="">Tất cả loại tài khoản</option>
          <option value="user">Wiii User</option>
          <option value="platform_admin">Platform Admin</option>
        </select>
        <select
          onChange={(event) =>
            fetchUsers({ status: event.target.value, page: 0 })
          }
          className="px-3 py-2 rounded-lg border border-border bg-surface-secondary text-text text-sm focus:outline-none"
          defaultValue=""
        >
          <option value="">Tất cả trạng thái</option>
          <option value="active">Hoạt động</option>
          <option value="inactive">Vô hiệu</option>
        </select>
      </div>

      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-surface-secondary text-text-secondary text-left">
              <th
                className="px-4 py-2.5 font-medium cursor-pointer hover:text-text"
                onClick={() => handleSort("name")}
              >
                Tên{" "}
                {usersSort.startsWith("name") &&
                  (usersSort.endsWith("asc") ? "\u2191" : "\u2193")}
              </th>
              <th
                className="px-4 py-2.5 font-medium cursor-pointer hover:text-text"
                onClick={() => handleSort("email")}
              >
                Email{" "}
                {usersSort.startsWith("email") &&
                  (usersSort.endsWith("asc") ? "\u2191" : "\u2193")}
              </th>
              <th className="px-4 py-2.5 font-medium">Loại tài khoản</th>
              <th className="px-4 py-2.5 font-medium">Trạng thái</th>
              <th className="px-4 py-2.5 font-medium">Tổ chức</th>
              <th
                className="px-4 py-2.5 font-medium cursor-pointer hover:text-text"
                onClick={() => handleSort("created_at")}
              >
                Ngày tạo{" "}
                {usersSort.startsWith("created_at") &&
                  (usersSort.endsWith("asc") ? "\u2191" : "\u2193")}
              </th>
              <th className="px-4 py-2.5 font-medium w-[70px]">Hành động</th>
            </tr>
          </thead>
          <tbody>
            {users.length === 0 && !loading && (
              <tr>
                <td
                  colSpan={7}
                  className="px-4 py-8 text-center text-text-tertiary text-xs"
                >
                  Không tìm thấy người dùng
                </td>
              </tr>
            )}
            {users.map((user) => {
              const isSelf = user.id === currentUserId;
              const isMenuOpen = openMenuUserId === user.id;
              const platformRole = user.platform_role || "user";
              const legacyRole = user.legacy_role || user.role;

              return (
                <tr
                  key={user.id}
                  className="border-t border-border hover:bg-surface-secondary transition-colors"
                >
                  <td className="px-4 py-2.5 text-text font-medium">
                    {user.name || "\u2014"}
                  </td>
                  <td className="px-4 py-2.5 text-text-secondary">
                    {user.email || "\u2014"}
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="flex flex-col gap-1">
                      <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-[var(--accent-light)] text-[var(--accent)] w-fit">
                        {getPlatformRoleLabel(platformRole)}
                      </span>
                      <span className="text-[10px] text-text-tertiary">
                        {getLegacyRoleLabel(legacyRole)}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-2.5">
                    <span
                      className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                        user.is_active
                          ? "bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300"
                          : "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300"
                      }`}
                    >
                      {user.is_active ? "Hoạt động" : "Vô hiệu"}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-text-secondary">
                    {user.organization_count}
                  </td>
                  <td className="px-4 py-2.5 text-text-tertiary text-xs">
                    {user.created_at
                      ? new Date(user.created_at).toLocaleDateString("vi-VN")
                      : "\u2014"}
                  </td>
                  <td className="px-4 py-2.5">
                    <div
                      className="relative"
                      ref={isMenuOpen ? menuRef : undefined}
                    >
                      <button
                        onClick={() => {
                          setOpenMenuUserId(isMenuOpen ? null : user.id);
                          setShowRoleSubmenu(false);
                        }}
                        className="p-1.5 rounded-lg hover:bg-surface-tertiary transition-colors text-text-secondary"
                        aria-label={`Hành động cho ${user.name || user.email || user.id}`}
                      >
                        <MoreHorizontal size={16} />
                      </button>

                      {isMenuOpen && (
                        <div className="absolute right-0 top-full mt-1 w-48 rounded-lg border border-border bg-surface shadow-lg z-[60] py-1">
                          {user.is_active ? (
                            <>
                              {!isSelf && (
                                <button
                                  onClick={() =>
                                    handleDeactivate(
                                      user.id,
                                      user.name || user.email || user.id,
                                    )
                                  }
                                  className="w-full text-left px-3 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-surface-secondary transition-colors"
                                >
                                  Vô hiệu hóa
                                </button>
                              )}
                              <div className="relative">
                                <button
                                  onClick={() =>
                                    setShowRoleSubmenu(!showRoleSubmenu)
                                  }
                                  className="w-full text-left px-3 py-2 text-sm text-text hover:bg-surface-secondary transition-colors flex items-center justify-between"
                                >
                                  Đổi loại tài khoản
                                  <ChevronRight
                                    size={14}
                                    className="text-text-tertiary"
                                  />
                                </button>
                                {showRoleSubmenu && (
                                  <div className="absolute left-full top-0 ml-1 w-44 rounded-lg border border-border bg-surface shadow-lg z-[61] py-1">
                                    {PLATFORM_ROLE_OPTIONS.filter(
                                      (option) => option.value !== platformRole,
                                    ).map((option) => (
                                      <button
                                        key={option.value}
                                        onClick={() =>
                                          handlePlatformRoleChange(
                                            user.id,
                                            option.value,
                                          )
                                        }
                                        className="w-full text-left px-3 py-2 text-sm text-text hover:bg-surface-secondary transition-colors"
                                      >
                                        {option.label}
                                      </button>
                                    ))}
                                  </div>
                                )}
                              </div>
                            </>
                          ) : (
                            <button
                              onClick={() => handleReactivate(user.id)}
                              className="w-full text-left px-3 py-2 text-sm text-green-600 dark:text-green-400 hover:bg-surface-secondary transition-colors"
                            >
                              Kích hoạt lại
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {usersTotal > 0 && (
        <div className="flex items-center justify-between text-xs text-text-secondary">
          <span>
            {startIdx}-{endIdx} trên {usersTotal}
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => fetchUsers({ page: usersPage - 1 })}
              disabled={usersPage === 0 || loading}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded border border-border hover:bg-surface-tertiary disabled:opacity-30 transition-colors"
            >
              <ChevronLeft size={12} />
              Trang trước
            </button>
            <span>
              {usersPage + 1} / {totalPages}
            </span>
            <button
              onClick={() => fetchUsers({ page: usersPage + 1 })}
              disabled={usersPage >= totalPages - 1 || loading}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded border border-border hover:bg-surface-tertiary disabled:opacity-30 transition-colors"
            >
              Trang sau
              <ChevronRight size={12} />
            </button>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={!!confirmTarget}
        title="Vô hiệu hóa người dùng"
        message={`Bạn có chắc chắn muốn vô hiệu hóa "${confirmTarget?.name}"? Người dùng sẽ không thể đăng nhập cho đến khi được kích hoạt lại.`}
        confirmLabel="Vô hiệu hóa"
        variant="danger"
        onConfirm={handleConfirmDeactivate}
        onCancel={() => setConfirmTarget(null)}
      />
    </div>
  );
}
