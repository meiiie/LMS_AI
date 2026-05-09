/**
 * Analytics tab - charts and admin metrics via recharts.
 * The canonical Wiii view is account-type first; legacy roles remain visible
 * only as compatibility data.
 */
import { useCallback, useEffect, useState } from "react";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { AlertCircle, Loader2 } from "lucide-react";
import { useAdminStore } from "@/stores/admin-store";
import type { DateRange } from "@/stores/admin-store";

const DATE_RANGES: { value: DateRange; label: string }[] = [
  { value: "7d", label: "7 ngày" },
  { value: "30d", label: "30 ngày" },
  { value: "90d", label: "90 ngày" },
  { value: "all", label: "Tất cả" },
];

const PLATFORM_ROLE_LABELS: Record<string, string> = {
  user: "Wiii User",
  platform_admin: "Platform Admin",
};

const LEGACY_ROLE_LABELS: Record<string, string> = {
  student: "student",
  teacher: "teacher",
  admin: "admin",
};

const ORG_ROLE_LABELS: Record<string, string> = {
  member: "Thành viên tổ chức",
  org_admin: "Quản trị tổ chức",
  owner: "Chủ sở hữu tổ chức",
  admin: "Quản trị tổ chức",
};

function useThemeColors() {
  if (typeof window === "undefined") {
    return { accent: "#6366f1", text: "#374151", grid: "#e5e7eb" };
  }
  const style = getComputedStyle(document.documentElement);
  return {
    accent: style.getPropertyValue("--accent").trim() || "#6366f1",
    text: style.getPropertyValue("--text-secondary").trim() || "#374151",
    grid: style.getPropertyValue("--border").trim() || "#e5e7eb",
  };
}

function DistributionRow({
  title,
  values,
  labels,
}: {
  title: string;
  values?: Record<string, number>;
  labels?: Record<string, string>;
}) {
  if (!values || Object.keys(values).length === 0) return null;
  return (
    <div>
      <div className="text-[11px] font-medium text-text-secondary mb-2">
        {title}
      </div>
      <div className="flex flex-wrap gap-3">
        {Object.entries(values).map(([key, count]) => (
          <div key={key} className="flex items-center gap-1.5 text-xs">
            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-surface-tertiary text-text-secondary">
              {labels?.[key] || key}
            </span>
            <span className="text-text">{count}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function derivePlatformRoleDistribution(
  values?: Record<string, number>,
): Record<string, number> | undefined {
  if (!values || Object.keys(values).length === 0) return undefined;
  return {
    platform_admin: values.admin || 0,
    user: Object.entries(values).reduce(
      (total, [role, count]) => total + (role === "admin" ? 0 : count),
      0,
    ),
  };
}

export function AnalyticsTab() {
  const {
    analyticsOverview,
    llmUsage,
    userAnalytics,
    analyticsDateRange,
    error,
    fetchAnalyticsOverview,
    fetchLlmUsage,
    fetchUserAnalytics,
    setAnalyticsDateRange,
  } = useAdminStore();
  const [localLoading, setLocalLoading] = useState(false);
  const colors = useThemeColors();

  const loadAnalytics = useCallback(
    async (range?: DateRange) => {
      setLocalLoading(true);
      try {
        await Promise.allSettled([
          fetchAnalyticsOverview(range),
          fetchLlmUsage(range),
          fetchUserAnalytics(range),
        ]);
      } finally {
        setLocalLoading(false);
      }
    },
    [fetchAnalyticsOverview, fetchLlmUsage, fetchUserAnalytics],
  );

  useEffect(() => {
    void loadAnalytics();
  }, [loadAnalytics]);

  const handleRangeChange = (range: DateRange) => {
    setAnalyticsDateRange(range);
    void loadAnalytics(range);
  };

  const platformRoleDistribution =
    userAnalytics?.platform_role_distribution ||
    derivePlatformRoleDistribution(userAnalytics?.role_distribution);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="text-sm font-medium text-text">Phân tích hệ thống</div>
        <div className="flex gap-1.5">
          {DATE_RANGES.map((range) => (
            <button
              key={range.value}
              disabled={localLoading}
              onClick={() => handleRangeChange(range.value)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                analyticsDateRange === range.value
                  ? "bg-[var(--accent)] text-white"
                  : "bg-surface-secondary text-text-secondary hover:text-text border border-border"
              }`}
            >
              {range.label}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-900/60 dark:bg-red-950/20 dark:text-red-300">
          <AlertCircle size={14} className="mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {localLoading && !analyticsOverview && !llmUsage && !userAnalytics && (
        <div
          aria-busy="true"
          className="flex items-start gap-3 rounded-xl border border-border bg-surface-secondary px-4 py-5 text-sm text-text-secondary"
        >
          <Loader2
            size={18}
            className="mt-0.5 shrink-0 animate-spin text-[var(--accent)]"
          />
          <div>
            <p className="font-medium text-text">
              Đang tải phân tích hệ thống...
            </p>
            <p className="mt-1 text-xs leading-5">
              Wiii đang lấy song song dữ liệu người dùng, lưu lượng chat và
              usage LLM. Nếu dữ liệu trống, tab sẽ hiển thị empty-state thay vì
              treo ở một dòng loading ngắn.
            </p>
          </div>
        </div>
      )}

      {analyticsOverview && analyticsOverview.daily_active_users.length > 0 && (
        <div className="p-4 rounded-xl border border-border bg-surface-secondary">
          <div className="text-xs font-medium text-text-secondary mb-3">
            Người dùng hoạt động hằng ngày
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={analyticsOverview.daily_active_users}>
              <CartesianGrid strokeDasharray="3 3" stroke={colors.grid} />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 10, fill: colors.text }}
              />
              <YAxis tick={{ fontSize: 10, fill: colors.text }} />
              <Tooltip
                contentStyle={{
                  fontSize: 12,
                  borderRadius: 8,
                  border: `1px solid ${colors.grid}`,
                }}
              />
              <Line
                type="monotone"
                dataKey="count"
                stroke={colors.accent}
                strokeWidth={2}
                dot={false}
                name="DAU"
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {analyticsOverview && analyticsOverview.chat_volume.length > 0 && (
        <div className="p-4 rounded-xl border border-border bg-surface-secondary">
          <div className="text-xs font-medium text-text-secondary mb-3">
            Lượng chat hằng ngày
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={analyticsOverview.chat_volume}>
              <CartesianGrid strokeDasharray="3 3" stroke={colors.grid} />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 10, fill: colors.text }}
              />
              <YAxis tick={{ fontSize: 10, fill: colors.text }} />
              <Tooltip
                contentStyle={{
                  fontSize: 12,
                  borderRadius: 8,
                  border: `1px solid ${colors.grid}`,
                }}
              />
              <Bar
                dataKey="messages"
                fill={colors.accent}
                name="Tin nhắn"
                radius={[4, 4, 0, 0]}
              />
              <Bar
                dataKey="sessions"
                fill={`${colors.accent}80`}
                name="Phiên"
                radius={[4, 4, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {llmUsage && (
        <div className="p-4 rounded-xl border border-border bg-surface-secondary">
          <div className="text-xs font-medium text-text-secondary mb-3">
            Sử dụng LLM
          </div>
          <div className="grid grid-cols-3 gap-4 mb-4">
            <div className="text-center">
              <div className="text-xl font-semibold text-text">
                {llmUsage.total_tokens >= 1000000
                  ? `${(llmUsage.total_tokens / 1000000).toFixed(1)}M`
                  : llmUsage.total_tokens >= 1000
                    ? `${(llmUsage.total_tokens / 1000).toFixed(1)}k`
                    : String(llmUsage.total_tokens)}
              </div>
              <div className="text-[10px] text-text-tertiary">Tokens</div>
            </div>
            <div className="text-center">
              <div className="text-xl font-semibold text-text">
                ${llmUsage.total_cost_usd.toFixed(2)}
              </div>
              <div className="text-[10px] text-text-tertiary">Chi phí</div>
            </div>
            <div className="text-center">
              <div className="text-xl font-semibold text-text">
                {llmUsage.total_requests}
              </div>
              <div className="text-[10px] text-text-tertiary">Requests</div>
            </div>
          </div>

          {llmUsage.breakdown.length > 0 && (
            <ResponsiveContainer width="100%" height={160}>
              <BarChart data={llmUsage.breakdown}>
                <CartesianGrid strokeDasharray="3 3" stroke={colors.grid} />
                <XAxis
                  dataKey="group"
                  tick={{ fontSize: 10, fill: colors.text }}
                />
                <YAxis tick={{ fontSize: 10, fill: colors.text }} />
                <Tooltip
                  contentStyle={{
                    fontSize: 12,
                    borderRadius: 8,
                    border: `1px solid ${colors.grid}`,
                  }}
                />
                <Bar
                  dataKey="tokens"
                  fill={colors.accent}
                  name="Tokens"
                  radius={[4, 4, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          )}

          {llmUsage.top_models.length > 0 && (
            <div className="mt-4">
              <div className="text-[11px] font-medium text-text-secondary mb-2">
                Model dùng nhiều
              </div>
              <div className="space-y-1">
                {llmUsage.top_models.slice(0, 5).map((model, index) => (
                  <div
                    key={index}
                    className="flex items-center justify-between text-xs"
                  >
                    <span className="text-text font-mono truncate">
                      {model.model}
                    </span>
                    <span className="text-text-tertiary shrink-0 ml-2">
                      {model.tokens >= 1000
                        ? `${(model.tokens / 1000).toFixed(1)}k`
                        : model.tokens}{" "}
                      tokens
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {llmUsage.top_users.length > 0 && (
            <div className="mt-4">
              <div className="text-[11px] font-medium text-text-secondary mb-2">
                Người dùng nhiều nhất
              </div>
              <div className="space-y-1">
                {llmUsage.top_users.slice(0, 5).map((user, index) => (
                  <div
                    key={index}
                    className="flex items-center justify-between text-xs"
                  >
                    <span className="text-text truncate">{user.user_id}</span>
                    <span className="text-text-tertiary shrink-0 ml-2">
                      {user.tokens >= 1000
                        ? `${(user.tokens / 1000).toFixed(1)}k`
                        : user.tokens}{" "}
                      tokens
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {userAnalytics && (
        <div className="p-4 rounded-xl border border-border bg-surface-secondary">
          <div className="text-xs font-medium text-text-secondary mb-3">
            Người dùng
          </div>
          <div className="grid grid-cols-3 gap-4 mb-4">
            <div className="text-center">
              <div className="text-xl font-semibold text-text">
                {userAnalytics.total_users}
              </div>
              <div className="text-[10px] text-text-tertiary">Tổng</div>
            </div>
            <div className="text-center">
              <div className="text-xl font-semibold text-text">
                {userAnalytics.new_users_period}
              </div>
              <div className="text-[10px] text-text-tertiary">Mới</div>
            </div>
            <div className="text-center">
              <div className="text-xl font-semibold text-text">
                {userAnalytics.active_users_period}
              </div>
              <div className="text-[10px] text-text-tertiary">Hoạt động</div>
            </div>
          </div>

          <div className="space-y-3">
            <DistributionRow
              title="Loại tài khoản Wiii"
              values={platformRoleDistribution}
              labels={PLATFORM_ROLE_LABELS}
            />
            <DistributionRow
              title="Vai trò tương thích (legacy)"
              values={
                userAnalytics.legacy_role_distribution ||
                userAnalytics.role_distribution
              }
              labels={LEGACY_ROLE_LABELS}
            />
            <DistributionRow
              title="Vai trò trong tổ chức đang lọc"
              values={userAnalytics.organization_role_distribution}
              labels={ORG_ROLE_LABELS}
            />
          </div>
        </div>
      )}

      {localLoading && analyticsOverview && (
        <div className="text-center text-text-tertiary text-xs py-8">
          Đang tải...
        </div>
      )}
    </div>
  );
}
