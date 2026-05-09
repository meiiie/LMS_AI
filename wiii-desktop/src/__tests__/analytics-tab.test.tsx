import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AnalyticsTab } from "@/components/admin/AnalyticsTab";
import { useAdminStore } from "@/stores/admin-store";

vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  LineChart: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Line: () => null,
  BarChart: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Bar: () => null,
  XAxis: () => null,
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
}));

describe("AnalyticsTab identity semantics", () => {
  beforeEach(() => {
    useAdminStore.setState({
      analyticsOverview: null,
      llmUsage: null,
      userAnalytics: {
        total_users: 12,
        new_users_period: 3,
        active_users_period: 8,
        user_growth: [],
        role_distribution: { student: 7, teacher: 4, admin: 1 },
        legacy_role_distribution: { student: 7, teacher: 4, admin: 1 },
        platform_role_distribution: { user: 11, platform_admin: 1 },
        organization_role_distribution: { member: 10, org_admin: 1, owner: 1 },
        top_active_users: [],
      },
      analyticsDateRange: "30d",
      loading: false,
      fetchAnalyticsOverview: vi.fn(),
      fetchLlmUsage: vi.fn(),
      fetchUserAnalytics: vi.fn(),
      setAnalyticsDateRange: vi.fn(),
    } as never);
  });

  it("shows canonical Wiii account types before compatibility roles", () => {
    render(<AnalyticsTab />);

    expect(screen.getByText("Loại tài khoản Wiii")).toBeTruthy();
    expect(screen.getByText("Wiii User")).toBeTruthy();
    expect(screen.getByText("Platform Admin")).toBeTruthy();
    expect(screen.getByText("Vai trò tương thích (legacy)")).toBeTruthy();
    expect(screen.getByText("Vai trò trong tổ chức đang lọc")).toBeTruthy();
  });
});
