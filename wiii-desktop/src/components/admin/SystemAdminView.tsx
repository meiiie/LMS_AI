/**
 * SystemAdminView - shared full-page system admin shell.
 */
import { useEffect } from "react";
import {
  BarChart3,
  Building2,
  Flag,
  LayoutDashboard,
  ScrollText,
  Server,
  Shield,
  Users,
} from "lucide-react";
import { useUIStore } from "@/stores/ui-store";
import { useAdminStore } from "@/stores/admin-store";
import type { AdminTab } from "@/stores/admin-store";
import { FullPageView } from "@/components/layout/FullPageView";
import type { FullPageTab } from "@/components/layout/FullPageView";
import { AdminToast } from "./AdminToast";
import { AnalyticsTab } from "./AnalyticsTab";
import { AuditLogsTab } from "./AuditLogsTab";
import { DashboardTab } from "./DashboardTab";
import { FeatureFlagsTab } from "./FeatureFlagsTab";
import { GdprTab } from "./GdprTab";
import { LlmRuntimeTab } from "./LlmRuntimeTab";
import { OrganizationsTab } from "./OrganizationsTab";
import { UsersTab } from "./UsersTab";

const TABS: (FullPageTab & { id: AdminTab })[] = [
  { id: "dashboard", label: "Tổng quan", icon: <LayoutDashboard size={16} /> },
  { id: "runtime", label: "Runtime", icon: <Server size={16} /> },
  { id: "users", label: "Người dùng", icon: <Users size={16} /> },
  { id: "organizations", label: "Tổ chức", icon: <Building2 size={16} /> },
  { id: "flags", label: "Feature Flags", icon: <Flag size={16} /> },
  { id: "analytics", label: "Phân tích", icon: <BarChart3 size={16} /> },
  { id: "audit", label: "Nhật ký", icon: <ScrollText size={16} /> },
  { id: "gdpr", label: "GDPR", icon: <Shield size={16} /> },
];

export function SystemAdminView() {
  const { navigateToChat } = useUIStore();
  const { activeTab, setActiveTab, fetchDashboard, reset } = useAdminStore();

  useEffect(() => {
    void fetchDashboard();
  }, [fetchDashboard]);

  useEffect(() => {
    return () => reset();
  }, [reset]);

  return (
    <>
      <FullPageView
        title="Quản trị hệ thống"
        icon={<Shield size={20} />}
        tabs={TABS}
        activeTab={activeTab}
        onTabChange={(id) => setActiveTab(id as AdminTab)}
        onClose={navigateToChat}
      >
        {activeTab === "dashboard" && <DashboardTab />}
        {activeTab === "runtime" && <LlmRuntimeTab />}
        {activeTab === "users" && <UsersTab />}
        {activeTab === "organizations" && <OrganizationsTab />}
        {activeTab === "flags" && <FeatureFlagsTab />}
        {activeTab === "analytics" && <AnalyticsTab />}
        {activeTab === "audit" && <AuditLogsTab />}
        {activeTab === "gdpr" && <GdprTab />}
      </FullPageView>
      <AdminToast />
    </>
  );
}
