/**
 * OrgAdminView - full-page org admin shell.
 */
import { useEffect } from "react";
import {
  BarChart3,
  BookOpen,
  Building2,
  LayoutDashboard,
  ScrollText,
  Settings,
  Users,
} from "lucide-react";
import { useUIStore } from "@/stores/ui-store";
import { useOrgAdminStore } from "@/stores/org-admin-store";
import type { OrgManagerTab } from "@/stores/org-admin-store";
import { FullPageView } from "@/components/layout/FullPageView";
import type { FullPageTab } from "@/components/layout/FullPageView";
import { OrgManagerDashboard } from "./OrgManagerDashboard";
import { OrgManagerMembers } from "./OrgManagerMembers";
import { OrgManagerSettings } from "./OrgManagerSettings";
import { OrgManagerKnowledge } from "./OrgManagerKnowledge";
import { OrgManagerAudit } from "./OrgManagerAudit";
import { OrgManagerActivity } from "./OrgManagerActivity";
import { PanelToast } from "@/components/admin/AdminToast";

const TABS: (FullPageTab & { id: OrgManagerTab })[] = [
  { id: "dashboard", label: "Tổng quan", icon: <LayoutDashboard size={16} /> },
  { id: "members", label: "Thành viên", icon: <Users size={16} /> },
  { id: "analytics", label: "Hoạt động", icon: <BarChart3 size={16} /> },
  { id: "audit", label: "Host actions", icon: <ScrollText size={16} /> },
  { id: "settings", label: "Cài đặt", icon: <Settings size={16} /> },
  { id: "knowledge", label: "Tri thức", icon: <BookOpen size={16} /> },
];

export function OrgAdminView() {
  const { navigateToChat, orgManagerTargetOrgId } = useUIStore();
  const {
    activeTab,
    setActiveTab,
    fetchOrgDetail,
    fetchMembers,
    orgDetail,
    reset,
  } = useOrgAdminStore();
  const toast = useOrgAdminStore((s) => s.toast);

  useEffect(() => {
    if (orgManagerTargetOrgId) {
      void fetchOrgDetail(orgManagerTargetOrgId);
      void fetchMembers(orgManagerTargetOrgId);
    }
  }, [orgManagerTargetOrgId, fetchOrgDetail, fetchMembers]);

  useEffect(() => {
    return () => reset();
  }, [reset]);

  const orgName =
    orgDetail?.display_name || orgDetail?.name || orgManagerTargetOrgId || "";

  return (
    <>
      <FullPageView
        title="Quản lý tổ chức"
        subtitle={orgName}
        icon={<Building2 size={20} />}
        tabs={TABS}
        activeTab={activeTab}
        onTabChange={(id) => setActiveTab(id as OrgManagerTab)}
        onClose={navigateToChat}
      >
        {activeTab === "dashboard" && <OrgManagerDashboard />}
        {activeTab === "members" && orgManagerTargetOrgId && (
          <OrgManagerMembers orgId={orgManagerTargetOrgId} />
        )}
        {activeTab === "analytics" && orgManagerTargetOrgId && (
          <OrgManagerActivity orgId={orgManagerTargetOrgId} />
        )}
        {activeTab === "audit" && orgManagerTargetOrgId && (
          <OrgManagerAudit orgId={orgManagerTargetOrgId} />
        )}
        {activeTab === "settings" && orgManagerTargetOrgId && (
          <OrgManagerSettings orgId={orgManagerTargetOrgId} />
        )}
        {activeTab === "knowledge" && orgManagerTargetOrgId && (
          <OrgManagerKnowledge orgId={orgManagerTargetOrgId} />
        )}
      </FullPageView>
      <PanelToast toast={toast} />
    </>
  );
}
