/**
 * SoulBridgePanel — main dashboard for Wiii's soul-to-soul connections.
 * Sprint 216: "Mang Linh Hon" (Soul Network)
 *
 * Monitors connected SubSouls (e.g., "Bro" trading risk guardian).
 * 3-tab FullPageView: overview, events, config.
 * Auto-refreshes every 30 seconds.
 */
import { useState, useEffect, useCallback, useMemo } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  Network,
  Activity,
  Settings2,
  RefreshCw,
  Wifi,
  WifiOff,
  Radio,
} from "lucide-react";
import { FullPageView } from "@/components/layout/FullPageView";
import type { FullPageTab } from "@/components/layout/FullPageView";
import { useSoulBridgeStore } from "@/stores/soul-bridge-store";
import { useUIStore } from "@/stores/ui-store";
import type {
  SoulBridgeStatus,
  PeerDetail,
  PeerEvent,
} from "@/api/soul-bridge";
import { PeerCard } from "./PeerCard";
import { EventTimeline } from "./EventTimeline";

// ── Types ──

type SoulBridgeTab = "overview" | "events" | "config";

// ── Constants ──

const TABS: (FullPageTab & { id: SoulBridgeTab })[] = [
  { id: "overview", label: "Tổng quan", icon: <Network size={16} /> },
  { id: "events", label: "Sự kiện", icon: <Activity size={16} /> },
  { id: "config", label: "Cấu hình", icon: <Settings2 size={16} /> },
];

const REFRESH_INTERVAL_MS = 30_000;

// ── Component ──

export function SoulBridgePanel() {
  const [activeTab, setActiveTab] = useState<SoulBridgeTab>("overview");
  const { navigateToChat } = useUIStore();
  const {
    bridgeStatus,
    peerDetails,
    loading,
    error,
    selectedPeerId,
    refreshAll,
    selectPeer,
  } = useSoulBridgeStore();

  // Fetch on mount
  useEffect(() => {
    refreshAll();
  }, [refreshAll]);

  // Auto-refresh every 30s
  useEffect(() => {
    const interval = setInterval(() => {
      refreshAll();
    }, REFRESH_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [refreshAll]);

  // Peer selection + tab switch handler
  const handlePeerClick = useCallback(
    (peerId: string) => {
      selectPeer(peerId);
      setActiveTab("events");
    },
    [selectPeer],
  );

  // Peer IDs from bridge status
  const peerIds = useMemo(
    () => Object.keys(bridgeStatus?.peers ?? {}),
    [bridgeStatus],
  );

  // Selected peer (fallback to first)
  const effectivePeerId = selectedPeerId ?? peerIds[0] ?? null;

  // Events for selected peer
  const selectedEvents = effectivePeerId
    ? (peerDetails[effectivePeerId]?.recent_events ?? [])
    : [];

  // Refresh footer button for sidebar
  const footerRefresh = (
    <button
      onClick={() => refreshAll()}
      disabled={loading}
      className="flex items-center gap-2 w-full px-3 py-2 mb-1 rounded-lg text-sm text-text-secondary
        hover:bg-surface-tertiary hover:text-text transition-colors disabled:opacity-50"
    >
      <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
      Làm mới
    </button>
  );

  return (
    <FullPageView
      title="Mạng Linh Hồn"
      subtitle={
        bridgeStatus
          ? `${bridgeStatus.peer_count} peer${bridgeStatus.peer_count !== 1 ? "s" : ""}`
          : undefined
      }
      icon={<Network size={20} />}
      tabs={TABS}
      activeTab={activeTab}
      onTabChange={(id) => setActiveTab(id as SoulBridgeTab)}
      onClose={navigateToChat}
      footer={footerRefresh}
    >
      {/* Error banner */}
      {error && (
        <div className="mb-4 px-3 py-2 rounded-lg bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 text-xs text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      {activeTab === "overview" && (
        <OverviewTab
          bridgeStatus={bridgeStatus}
          peerDetails={peerDetails}
          peerIds={peerIds}
          onPeerClick={handlePeerClick}
          loading={loading}
        />
      )}

      {activeTab === "events" && (
        <EventsTab
          peerIds={peerIds}
          effectivePeerId={effectivePeerId}
          peerDetails={peerDetails}
          events={selectedEvents}
          onSelectPeer={selectPeer}
        />
      )}

      {activeTab === "config" && <ConfigTab bridgeStatus={bridgeStatus} />}
    </FullPageView>
  );
}

// ── Overview Tab ──

function OverviewTab({
  bridgeStatus,
  peerDetails,
  peerIds,
  onPeerClick,
  loading,
}: {
  bridgeStatus: SoulBridgeStatus | null;
  peerDetails: Record<string, PeerDetail>;
  peerIds: string[];
  onPeerClick: (id: string) => void;
  loading: boolean;
}) {
  return (
    <div className="space-y-6">
      {/* Bridge status banner */}
      <div className="p-4 rounded-xl bg-surface-secondary border border-border">
        <div className="flex items-center gap-3 mb-3">
          <motion.div
            animate={
              bridgeStatus?.initialized ? { scale: [1, 1.1, 1] } : { scale: 1 }
            }
            transition={
              bridgeStatus?.initialized ? { duration: 2, repeat: Infinity } : {}
            }
          >
            <Radio
              size={18}
              className={
                bridgeStatus?.initialized
                  ? "text-[var(--accent)]"
                  : "text-text-tertiary"
              }
            />
          </motion.div>
          <div>
            <h3 className="text-sm font-semibold text-text">
              Trạng thái cầu nối
            </h3>
            <p className="text-xs text-text-tertiary">
              {bridgeStatus?.initialized
                ? "Đang hoạt động"
                : "Chưa khởi tạo hoặc đang tắt bằng feature flag"}
            </p>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 text-xs">
          <div>
            <span className="text-text-tertiary">Soul ID</span>
            <p className="text-text font-mono font-medium mt-0.5 truncate">
              {bridgeStatus?.soul_id ?? "—"}
            </p>
          </div>
          <div>
            <span className="text-text-tertiary">Số peer</span>
            <p className="text-text font-medium mt-0.5">
              {bridgeStatus?.peer_count ?? 0}
            </p>
          </div>
        </div>
      </div>

      {/* Peer cards grid */}
      <div>
        <h3 className="text-xs font-medium text-text-secondary mb-3 uppercase tracking-wider">
          Các peer kết nối
        </h3>

        {peerIds.length === 0 && !loading && (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <WifiOff className="w-10 h-10 text-text-tertiary mb-3" />
            <p className="text-sm text-text-secondary">
              Chưa có peer nào kết nối
            </p>
            <p className="text-xs text-text-tertiary mt-1">
              Cấu hình enable_soul_bridge và soul_bridge_peers để kết nối với
              các SubSoul khác. Khi chưa bật, Wiii giữ panel ở chế độ quan sát
              an toàn thay vì gọi route lỗi.
            </p>
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <AnimatePresence>
            {peerIds.map((peerId, idx) => (
              <motion.div
                key={peerId}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ delay: idx * 0.05 }}
              >
                <PeerCard
                  peerId={peerId}
                  peer={bridgeStatus!.peers[peerId]}
                  detail={peerDetails[peerId] ?? null}
                  onClick={() => onPeerClick(peerId)}
                />
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}

// ── Events Tab ──

function EventsTab({
  peerIds,
  effectivePeerId,
  peerDetails,
  events,
  onSelectPeer,
}: {
  peerIds: string[];
  effectivePeerId: string | null;
  peerDetails: Record<string, PeerDetail>;
  events: PeerEvent[];
  onSelectPeer: (id: string | null) => void;
}) {
  return (
    <div className="space-y-4">
      {/* Peer selector (if multiple peers) */}
      {peerIds.length > 1 && (
        <div className="flex items-center gap-2">
          <label className="text-xs text-text-secondary" htmlFor="peer-select">
            Peer:
          </label>
          <select
            id="peer-select"
            value={effectivePeerId ?? ""}
            onChange={(e) => onSelectPeer(e.target.value || null)}
            className="text-sm px-2 py-1 rounded-lg bg-surface-secondary border border-border
              text-text focus:outline-none focus:ring-1 focus:ring-[var(--accent)]"
          >
            {peerIds.map((id) => {
              const card = peerDetails[id]?.card;
              return (
                <option key={id} value={id}>
                  {card?.name ?? id}
                </option>
              );
            })}
          </select>
        </div>
      )}

      {/* Peer header */}
      {effectivePeerId && peerDetails[effectivePeerId]?.card && (
        <div className="flex items-center gap-2 pb-2 border-b border-border">
          <Wifi size={14} className="text-[var(--accent)]" />
          <span className="text-sm font-medium text-text">
            {peerDetails[effectivePeerId].card!.name}
          </span>
          <span className="text-xs text-text-tertiary">
            ({peerDetails[effectivePeerId].event_count} sự kiện)
          </span>
        </div>
      )}

      {/* Timeline */}
      {events.length > 0 ? (
        <EventTimeline events={events} />
      ) : (
        <div className="rounded-xl border border-dashed border-border bg-surface-secondary/60 px-4 py-8 text-center">
          <Activity
            size={24}
            className="mx-auto mb-3 text-text-tertiary opacity-60"
          />
          <p className="text-sm font-medium text-text">
            Chưa có sự kiện Soul Bridge.
          </p>
          <p className="mx-auto mt-2 max-w-xl text-xs leading-5 text-text-secondary">
            Khi bridge được bật và có peer gửi trạng thái, mood, discovery hoặc
            consultation, timeline này sẽ hiển thị từng event để mình kiểm tra
            luồng liên kết giữa các “linh hồn” số.
          </p>
        </div>
      )}
    </div>
  );
}

// ── Config Tab ──

function ConfigTab({
  bridgeStatus,
}: {
  bridgeStatus: SoulBridgeStatus | null;
}) {
  return (
    <div className="space-y-6">
      {/* Soul ID */}
      <div>
        <h3 className="text-xs font-medium text-text-secondary mb-2 uppercase tracking-wider">
          Danh tính linh hồn
        </h3>
        <div className="p-3 rounded-lg bg-surface-secondary border border-border">
          <div className="text-xs text-text-tertiary mb-1">Soul ID</div>
          <div className="text-sm text-text font-mono">
            {bridgeStatus?.soul_id ?? "Chưa cấu hình"}
          </div>
        </div>
      </div>

      {/* Bridge events */}
      <div>
        <h3 className="text-xs font-medium text-text-secondary mb-2 uppercase tracking-wider">
          Sự kiện được cấu hình
        </h3>
        {(bridgeStatus?.bridge_events ?? []).length === 0 ? (
          <p className="text-xs text-text-tertiary">
            Không có sự kiện nào được cấu hình
          </p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {bridgeStatus!.bridge_events.map((evt) => (
              <span
                key={evt}
                className="text-xs px-2.5 py-1 rounded-lg bg-surface-secondary border border-border text-text"
              >
                {evt}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Info note */}
      <div className="p-3 rounded-lg border border-border bg-[var(--accent)]/5 text-xs text-text-secondary">
        <p>
          Cấu hình cầu nối linh hồn được quản lý qua{" "}
          <code className="text-[var(--accent)] font-mono">soul_bridge_*</code>{" "}
          trong file .env. Thay đổi cần khởi động lại server.
        </p>
      </div>
    </div>
  );
}
