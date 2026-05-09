/**
 * Conversation grouping — time-based groups + search filtering.
 * Sprint 80: Multi-session sidebar enhancement.
 */
import type { Conversation } from "@/api/types";
export { DOMAIN_BADGES } from "@/lib/domain-config";

export interface ConversationGroup {
  label: string;
  conversations: Conversation[];
}

/** Check if a date is today. */
function isToday(date: Date): boolean {
  const now = new Date();
  return (
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  );
}

/** Check if a date is yesterday. */
function isYesterday(date: Date): boolean {
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  return (
    date.getFullYear() === yesterday.getFullYear() &&
    date.getMonth() === yesterday.getMonth() &&
    date.getDate() === yesterday.getDate()
  );
}

/** Check if a date is within the last 7 days (excluding today and yesterday). */
function isThisWeek(date: Date): boolean {
  const now = new Date();
  const weekAgo = new Date();
  weekAgo.setDate(weekAgo.getDate() - 7);
  return date >= weekAgo && date < now && !isToday(date) && !isYesterday(date);
}

/**
 * Group conversations by time + pinned status, optionally filtered by search and org.
 *
 * Groups: Ghim (pinned) -> Hom nay -> Hom qua -> Tuan nay -> Cu hon
 * Search: case-insensitive match against title.
 * Sprint 156: Optional org filter — "personal" shows only convs without org_id.
 */
export function groupConversations(
  conversations: Conversation[],
  searchQuery?: string,
  orgFilter?: string | null,
): ConversationGroup[] {
  // Sprint 156: Filter by organization
  let filtered = conversations;
  if (orgFilter !== undefined && orgFilter !== null) {
    if (orgFilter === "personal") {
      filtered = filtered.filter((c) => !c.organization_id);
    } else {
      filtered = filtered.filter((c) => c.organization_id === orgFilter);
    }
  }

  // Filter by search query
  if (searchQuery && searchQuery.trim()) {
    const query = searchQuery.trim().toLowerCase();
    filtered = filtered.filter((c) =>
      c.title.toLowerCase().includes(query)
    );
  }

  // Phase 35 — dedup by session_id (server sync occasionally creates stub
  // conversations alongside the local conv when thread_id linkage races).
  // Keep the entry with more messages (or the locally-created one if tied).
  const bySessionId = new Map<string, Conversation>();
  const dedupedFiltered: Conversation[] = [];
  for (const c of filtered) {
    const sid = c.session_id || c.thread_id;
    if (!sid) {
      dedupedFiltered.push(c);
      continue;
    }
    const existing = bySessionId.get(sid);
    if (!existing) {
      bySessionId.set(sid, c);
      dedupedFiltered.push(c);
      continue;
    }
    // Prefer the entry with more messages (real local conv) over server stub.
    const existingCount = existing.messages?.length ?? existing.message_count ?? 0;
    const newCount = c.messages?.length ?? c.message_count ?? 0;
    if (newCount > existingCount) {
      const idx = dedupedFiltered.indexOf(existing);
      if (idx >= 0) dedupedFiltered[idx] = c;
      bySessionId.set(sid, c);
    }
  }

  // Sort by updated_at descending (most recent first)
  const sorted = [...dedupedFiltered].sort(
    (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
  );

  // Separate pinned
  const pinned = sorted.filter((c) => c.pinned);
  const unpinned = sorted.filter((c) => !c.pinned);

  // Group unpinned by time
  const today: Conversation[] = [];
  const yesterday: Conversation[] = [];
  const thisWeek: Conversation[] = [];
  const older: Conversation[] = [];

  for (const conv of unpinned) {
    const date = new Date(conv.updated_at);
    if (isToday(date)) {
      today.push(conv);
    } else if (isYesterday(date)) {
      yesterday.push(conv);
    } else if (isThisWeek(date)) {
      thisWeek.push(conv);
    } else {
      older.push(conv);
    }
  }

  // Build groups (only include non-empty groups)
  const groups: ConversationGroup[] = [];

  if (pinned.length > 0) {
    groups.push({ label: "Ghim", conversations: pinned });
  }
  if (today.length > 0) {
    groups.push({ label: "Hôm nay", conversations: today });
  }
  if (yesterday.length > 0) {
    groups.push({ label: "Hôm qua", conversations: yesterday });
  }
  if (thisWeek.length > 0) {
    groups.push({ label: "Tuần này", conversations: thisWeek });
  }
  if (older.length > 0) {
    groups.push({ label: "Cũ hơn", conversations: older });
  }

  return groups;
}

