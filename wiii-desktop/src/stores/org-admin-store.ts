/**
 * Org Admin store — Sprint 181: "Hai Tầng Quyền Lực"
 * Sprint 190: Added document management state + actions for Knowledge tab.
 *
 * Lightweight store for org manager panel (5 tabs).
 * Separated from admin-store (system admin) for cleaner UX.
 */
import { create } from "zustand";
import type {
  AdminAuthEvent,
  AdminOrgMember,
  AdminOrgDetail,
  OrgDocument,
} from "@/api/types";
import {
  getAdminOrgDetail,
  getAdminOrgMembers,
  addOrgMember as apiAddOrgMember,
  removeOrgMember as apiRemoveOrgMember,
  listOrgDocuments,
  uploadOrgDocument as apiUploadOrgDocument,
  deleteOrgDocument as apiDeleteOrgDocument,
} from "@/api/admin";
import {
  getOrgHostActionEvents,
  getOrgSettings,
  updateOrgSettings,
} from "@/api/organizations";
import type { OrgSettings } from "@/api/types";

export type OrgManagerTab =
  | "dashboard"
  | "members"
  | "analytics"
  | "audit"
  | "settings"
  | "knowledge";
export type OrgHostActionView = "all" | "previews" | "applies" | "publishes";

interface OrgAdminToast {
  type: "success" | "error";
  message: string;
}

interface OrgAdminState {
  activeTab: OrgManagerTab;
  orgId: string | null;
  orgDetail: AdminOrgDetail | null;
  members: AdminOrgMember[];
  orgSettings: OrgSettings | null;
  detailLoading: boolean;
  membersLoading: boolean;
  loading: boolean;
  toast: OrgAdminToast | null;
  _toastTimer: ReturnType<typeof setTimeout> | undefined;

  // Sprint 190: Knowledge documents
  documents: OrgDocument[];
  documentsTotal: number;
  documentsLoading: boolean;
  _documentsFetchOrgId: string | null;
  _documentsFetchPromise: Promise<void> | null;
  hostActionEvents: AdminAuthEvent[];
  hostActionEventsTotal: number;
  hostActionEventsPage: number;
  hostActionView: OrgHostActionView;
  hostActionLoading: boolean;

  // Actions
  setActiveTab: (tab: OrgManagerTab) => void;
  setOrgId: (orgId: string) => void;
  reset: () => void;
  fetchOrgDetail: (orgId: string) => Promise<void>;
  fetchMembers: (orgId: string) => Promise<void>;
  fetchSettings: (orgId: string) => Promise<void>;
  addMember: (orgId: string, userId: string, role?: string) => Promise<void>;
  removeMember: (orgId: string, userId: string) => Promise<void>;
  updateSettings: (
    orgId: string,
    patch: Record<string, unknown>,
  ) => Promise<void>;
  showToast: (type: "success" | "error", message: string) => void;

  // Sprint 190: Knowledge actions
  fetchDocuments: (orgId: string) => Promise<void>;
  uploadDocument: (orgId: string, file: File) => Promise<void>;
  deleteDocument: (orgId: string, docId: string) => Promise<void>;
  fetchHostActionEvents: (orgId: string, page?: number) => Promise<void>;
  setHostActionView: (view: OrgHostActionView) => void;
}

export const useOrgAdminStore = create<OrgAdminState>((set, get) => ({
  activeTab: "dashboard",
  orgId: null,
  orgDetail: null,
  members: [],
  orgSettings: null,
  detailLoading: false,
  membersLoading: false,
  loading: false,
  toast: null,
  _toastTimer: undefined,

  // Sprint 190: Knowledge state
  documents: [],
  documentsTotal: 0,
  documentsLoading: false,
  _documentsFetchOrgId: null,
  _documentsFetchPromise: null,
  hostActionEvents: [],
  hostActionEventsTotal: 0,
  hostActionEventsPage: 0,
  hostActionView: "all",
  hostActionLoading: false,

  setActiveTab: (tab) => set({ activeTab: tab }),
  setOrgId: (orgId) => set({ orgId }),
  reset: () => {
    const timer = get()._toastTimer;
    if (timer) clearTimeout(timer);
    set({
      activeTab: "dashboard",
      orgId: null,
      orgDetail: null,
      members: [],
      orgSettings: null,
      detailLoading: false,
      membersLoading: false,
      loading: false,
      toast: null,
      _toastTimer: undefined,
      documents: [],
      documentsTotal: 0,
      documentsLoading: false,
      _documentsFetchOrgId: null,
      _documentsFetchPromise: null,
      hostActionEvents: [],
      hostActionEventsTotal: 0,
      hostActionEventsPage: 0,
      hostActionView: "all",
      hostActionLoading: false,
    });
  },

  fetchOrgDetail: async (orgId) => {
    set({ detailLoading: true, loading: true });
    try {
      const detail = await getAdminOrgDetail(orgId);
      set({ orgDetail: detail });
    } catch {
      get().showToast("error", "Không thể tải thông tin tổ chức");
    } finally {
      set((s) => ({ detailLoading: false, loading: s.membersLoading }));
    }
  },

  fetchMembers: async (orgId) => {
    set({ membersLoading: true, loading: true });
    try {
      const members = await getAdminOrgMembers(orgId);
      set({ members });
    } catch {
      get().showToast("error", "Không thể tải danh sách thành viên");
    } finally {
      set((s) => ({ membersLoading: false, loading: s.detailLoading }));
    }
  },

  fetchSettings: async (orgId) => {
    try {
      const settings = await getOrgSettings(orgId);
      set({ orgSettings: settings });
    } catch {
      get().showToast("error", "Không thể tải cài đặt");
    }
  },

  addMember: async (orgId, userId, role) => {
    try {
      await apiAddOrgMember(orgId, userId, role);
      get().showToast("success", "Đã thêm thành viên");
      await get().fetchMembers(orgId);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Lỗi thêm thành viên";
      get().showToast("error", msg);
    }
  },

  removeMember: async (orgId, userId) => {
    try {
      await apiRemoveOrgMember(orgId, userId);
      get().showToast("success", "Đã xoá thành viên");
      await get().fetchMembers(orgId);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Lỗi xoá thành viên";
      get().showToast("error", msg);
    }
  },

  updateSettings: async (orgId, patch) => {
    try {
      const updated = await updateOrgSettings(orgId, patch);
      set({ orgSettings: updated });
      get().showToast("success", "Đã cập nhật cài đặt");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Lỗi cập nhật cài đặt";
      get().showToast("error", msg);
    }
  },

  // Sprint 190: Knowledge document actions
  fetchDocuments: async (orgId) => {
    const inFlight = get()._documentsFetchPromise;
    if (inFlight && get()._documentsFetchOrgId === orgId) {
      return inFlight;
    }

    set({ documentsLoading: true });
    const promise = (async () => {
      try {
        const resp = await listOrgDocuments(orgId);
        set({ documents: resp.documents, documentsTotal: resp.total });
      } catch {
        get().showToast("error", "Không thể tải danh sách tài liệu");
      } finally {
        set({
          documentsLoading: false,
          _documentsFetchOrgId: null,
          _documentsFetchPromise: null,
        });
      }
    })();
    set({ _documentsFetchOrgId: orgId, _documentsFetchPromise: promise });
    return promise;
  },

  uploadDocument: async (orgId, file) => {
    try {
      const result = await apiUploadOrgDocument(orgId, file);
      const parts: string[] = [`Đã tải lên: ${file.name}`];
      if (result.page_count != null && result.page_count > 0)
        parts.push(`${result.page_count} trang`);
      if (result.chunk_count != null && result.chunk_count > 0)
        parts.push(`${result.chunk_count} phân đoạn`);
      get().showToast("success", parts.join(" — "));
      await get().fetchDocuments(orgId);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Lỗi tải lên file";
      get().showToast("error", msg);
    }
  },

  deleteDocument: async (orgId, docId) => {
    try {
      await apiDeleteOrgDocument(orgId, docId);
      get().showToast("success", "Đã xoá tài liệu");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Lỗi xoá tài liệu";
      get().showToast("error", msg);
    } finally {
      await get().fetchDocuments(orgId);
    }
  },

  fetchHostActionEvents: async (orgId, page) => {
    const nextPage = page ?? get().hostActionEventsPage;
    const view = get().hostActionView;
    const eventType =
      view === "previews"
        ? "host_action.preview_created"
        : view === "applies"
          ? "host_action.apply_confirmed"
          : view === "publishes"
            ? "host_action.publish_confirmed"
            : undefined;

    set({ hostActionLoading: true, hostActionEventsPage: nextPage });
    try {
      const response = await getOrgHostActionEvents(orgId, {
        event_type: eventType,
        limit: 20,
        offset: nextPage * 20,
      });
      set({
        hostActionEvents: response.entries,
        hostActionEventsTotal: response.total,
      });
    } catch (err) {
      const msg =
        err instanceof Error
          ? err.message
          : "Không thể tải host action timeline";
      get().showToast("error", msg);
    } finally {
      set({ hostActionLoading: false });
    }
  },

  setHostActionView: (view) =>
    set({ hostActionView: view, hostActionEventsPage: 0 }),

  showToast: (type, message) => {
    const prev = get()._toastTimer;
    if (prev) clearTimeout(prev);
    const duration = type === "error" ? 6000 : 3000;
    const timer = setTimeout(
      () => set({ toast: null, _toastTimer: undefined }),
      duration,
    );
    set({ toast: { type, message }, _toastTimer: timer });
  },
}));
