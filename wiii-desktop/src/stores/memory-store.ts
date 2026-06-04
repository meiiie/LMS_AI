/**
 * Memory store — user memory facts state.
 * Sprint 80: ChatGPT-style memory management (view/delete facts).
 */
import { create } from "zustand";
import { fetchMemories, deleteMemory, clearMemories } from "@/api/memories";
import type { MemoryHealthSummary, MemoryItem } from "@/api/types";

/** Vietnamese labels for fact types (Sprint 73: 15 FactTypes). */
export const FACT_TYPE_LABELS: Record<string, string> = {
  name: "Tên",
  age: "Tuổi",
  location: "Nơi ở",
  organization: "Tổ chức",
  role: "Vai trò",
  level: "Cấp bậc",
  goal: "Mục tiêu",
  preference: "Sở thích học",
  weakness: "Điểm yếu",
  strength: "Điểm mạnh",
  learning_style: "Phong cách học",
  hobby: "Sở thích",
  interest: "Quan tâm",
  emotion: "Tâm trạng",
  recent_topic: "Chủ đề gần đây",
  pronoun_style: "Xưng hô",
  hometown: "Quê quán",
};

interface MemoryState {
  memories: MemoryItem[];
  memorySummary: MemoryHealthSummary | null;
  isLoading: boolean;
  error: string | null;

  fetchMemories: (userId: string) => Promise<void>;
  deleteOne: (userId: string, memoryId: string) => Promise<void>;
  clearAll: (userId: string) => Promise<void>;
  reset: () => void;
}

export const useMemoryStore = create<MemoryState>((set, get) => ({
  memories: [],
  memorySummary: null,
  isLoading: false,
  error: null,

  fetchMemories: async (userId: string) => {
    if (!userId) return;
    set({ isLoading: true, error: null });
    try {
      const res = await fetchMemories(userId);
      set({
        memories: res.data ?? [],
        memorySummary: res.summary ?? null,
        isLoading: false,
      });
    } catch (err) {
      set({
        isLoading: false,
        error: err instanceof Error ? err.message : "Không thể tải bộ nhớ",
      });
    }
  },

  deleteOne: async (userId: string, memoryId: string) => {
    try {
      await deleteMemory(userId, memoryId);
      // Optimistic removal
      set((state) => {
        const nextMemories = state.memories.filter((m) => m.id !== memoryId);
        const nextTypeCounts = nextMemories.reduce<Record<string, number>>(
          (acc, memory) => {
            acc[memory.type] = (acc[memory.type] || 0) + 1;
            return acc;
          },
          {},
        );
        const sortedDates = nextMemories
          .map((memory) => memory.created_at)
          .sort();
        const latestCreatedAt = sortedDates[sortedDates.length - 1] ?? null;
        const nextSourceKinds: Record<string, number> = nextMemories.length
          ? { semantic_fact: nextMemories.length }
          : {};

        return {
          memories: nextMemories,
          memorySummary: state.memorySummary
            ? {
                ...state.memorySummary,
                total: nextMemories.length,
                type_counts: nextTypeCounts,
                latest_created_at: latestCreatedAt,
                provenance: {
                  ...state.memorySummary.provenance,
                  source_kinds: nextSourceKinds,
                },
              }
            : null,
        };
      });
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : "Không thể xóa bộ nhớ",
      });
    }
  },

  clearAll: async (userId: string) => {
    set({ isLoading: true, error: null });
    try {
      await clearMemories(userId);
      set((state) => ({
        memories: [],
        memorySummary: state.memorySummary
          ? {
              ...state.memorySummary,
              total: 0,
              type_counts: {},
              latest_created_at: null,
              provenance: {
                ...state.memorySummary.provenance,
                source_kinds: {},
              },
            }
          : null,
        isLoading: false,
      }));
    } catch (err) {
      set({
        isLoading: false,
        error: err instanceof Error ? err.message : "Không thể xóa tất cả bộ nhớ",
      });
      // Refresh to get actual state
      await get().fetchMemories(userId);
    }
  },

  reset: () =>
    set({ memories: [], memorySummary: null, isLoading: false, error: null }),
}));
