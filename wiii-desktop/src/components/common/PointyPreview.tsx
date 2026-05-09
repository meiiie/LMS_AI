/**
 * Wiii Pointy preview / demo page (?preview=pointy).
 *
 * Standalone visual verification of the spring-physics multi-cursor
 * architecture. Showcases:
 *
 * - Self-driving "Wiii" cursor that hops between target buttons
 * - A second "Bro" peer cursor demonstrating multi-cursor support
 * - Awareness state buttons (idle / moving / pointing / thinking)
 *   so a reviewer can see each state's distinct feel
 * - Side-by-side spring preset sliders for tuning verification
 *
 * Open in browser at: ``http://localhost:1420/?preview=pointy``
 *
 * No auth, no chat, no SSE — pure rendering test. The chat-stream pipe
 * (SSE → registry.upsert) is exercised separately via the live API test.
 */

import { useEffect, useRef, useState } from "react";
import { CursorRegistry } from "@/pointy-host/registry";
import { WIII_IDENTITY, identityFor, type AwarenessState } from "@/pointy-host/identity";

interface DemoTarget {
  id: string;
  label: string;
  x: number;
  y: number;
}

const TARGETS: DemoTarget[] = [
  { id: "tl", label: "Top-left", x: 200, y: 180 },
  { id: "tr", label: "Top-right", x: 1100, y: 180 },
  { id: "bl", label: "Bottom-left", x: 200, y: 600 },
  { id: "br", label: "Bottom-right", x: 1100, y: 600 },
  { id: "c", label: "Center", x: 650, y: 400 },
];

const STATES: AwarenessState[] = ["idle", "moving", "pointing", "thinking"];

export function PointyPreview() {
  const registryRef = useRef<CursorRegistry | null>(null);
  const [autoplay, setAutoplay] = useState(true);
  const [wiiiState, setWiiiState] = useState<AwarenessState>("moving");
  const [showPeer, setShowPeer] = useState(true);

  useEffect(() => {
    const registry = new CursorRegistry();
    registryRef.current = registry;

    // Spawn the Wiii cursor at center.
    registry.upsert(WIII_IDENTITY, { x: 650, y: 400 });

    return () => registry.dispose();
  }, []);

  // Spawn / remove peer cursor based on toggle.
  useEffect(() => {
    const registry = registryRef.current;
    if (!registry) return;
    const peer = identityFor("subsoul-bro", "Bro", { avatar: "B", role: "ai-peer" });
    if (showPeer) {
      registry.upsert(peer, { x: 200, y: 400 });
    } else {
      registry.remove(peer.id);
    }
  }, [showPeer]);

  // Autoplay: hop the Wiii cursor between random targets every 1.6s.
  useEffect(() => {
    if (!autoplay) return;
    const registry = registryRef.current;
    if (!registry) return;
    let i = 0;
    const next = () => {
      i = (i + 1) % TARGETS.length;
      const t = TARGETS[i];
      registry.upsert(WIII_IDENTITY, { x: t.x, y: t.y });
      registry.setLabel(WIII_IDENTITY.id, `Wiii → ${t.label}`);
    };
    const timer = setInterval(next, 1600);
    return () => clearInterval(timer);
  }, [autoplay]);

  // Autoplay peer with a different rhythm so motion feels desynced.
  useEffect(() => {
    if (!showPeer || !autoplay) return;
    const registry = registryRef.current;
    if (!registry) return;
    let i = 0;
    const next = () => {
      i = (i + 1) % TARGETS.length;
      const t = TARGETS[(i + 2) % TARGETS.length];
      registry.upsert(identityFor("subsoul-bro", "Bro"), { x: t.x, y: t.y });
    };
    const timer = setInterval(next, 2400);
    return () => clearInterval(timer);
  }, [autoplay, showPeer]);

  const onSetState = (state: AwarenessState) => {
    setWiiiState(state);
    registryRef.current?.setState(WIII_IDENTITY.id, state);
  };

  const onTargetClick = (t: DemoTarget) => {
    setAutoplay(false);
    registryRef.current?.upsert(WIII_IDENTITY, { x: t.x, y: t.y });
    registryRef.current?.setLabel(WIII_IDENTITY.id, `Wiii → ${t.label}`);
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "linear-gradient(180deg, #fcfaf6 0%, #f5e9d6 100%)",
        fontFamily: "Inter, system-ui, sans-serif",
        color: "#1c1917",
        padding: "32px",
        position: "relative",
      }}
    >
      <header style={{ maxWidth: 880, marginBottom: 32 }}>
        <h1 style={{ fontSize: 32, fontWeight: 800, margin: 0, color: "#b85a33" }}>
          Wiii Pointy v2 — Spring Physics Demo
        </h1>
        <p style={{ fontSize: 15, lineHeight: 1.6, color: "#5b4a4a", marginTop: 12 }}>
          Multi-cursor architecture with Figma/Liveblocks-style spring interpolation.
          The Wiii cursor pursues each target with momentum-based motion — drag a
          new target and it redirects mid-flight without glitch. Toggle the peer
          cursor to see the multi-cursor system; switch awareness states to feel
          each preset (idle / moving / pointing / thinking).
        </p>
      </header>

      <section style={{ display: "flex", gap: 24, marginBottom: 40, flexWrap: "wrap" }}>
        <Card title="Autoplay">
          <button
            onClick={() => setAutoplay((v) => !v)}
            style={btnStyle(autoplay ? "#b85a33" : "#1c1917")}
            data-wiii-id="pointy-demo-autoplay"
          >
            {autoplay ? "▶ Đang tự chạy" : "⏸ Tạm dừng"}
          </button>
          <p style={hintStyle}>
            Cursor tự động nhảy giữa 5 góc, mỗi 1.6s. Click một mục tiêu cụ thể
            để chuyển sang chế độ thủ công.
          </p>
        </Card>

        <Card title="Awareness state">
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {STATES.map((s) => (
              <button
                key={s}
                onClick={() => onSetState(s)}
                style={btnStyle(s === wiiiState ? "#b85a33" : "#a89a8a")}
                data-wiii-id={`pointy-demo-state-${s}`}
              >
                {s}
              </button>
            ))}
          </div>
          <p style={hintStyle}>
            Mỗi state dùng spring preset khác nhau (heavy / default / snappy).
            "thinking" thêm bob animation, "idle" giảm opacity, "pointing" tăng glow.
          </p>
        </Card>

        <Card title="Multi-cursor">
          <button
            onClick={() => setShowPeer((v) => !v)}
            style={btnStyle(showPeer ? "#b85a33" : "#1c1917")}
            data-wiii-id="pointy-demo-peer"
          >
            {showPeer ? "👥 Có peer 'Bro'" : "👤 Chỉ Wiii"}
          </button>
          <p style={hintStyle}>
            Bật/tắt cursor peer. Mỗi cursor có identity riêng — màu, label, role.
            Tương lai: Soul Bridge peers sẽ hiện cùng cách này.
          </p>
        </Card>
      </section>

      <section
        style={{
          position: "relative",
          height: 580,
          background: "rgba(255,255,255,0.6)",
          borderRadius: 24,
          border: "1px solid rgba(161,145,127,0.26)",
          marginBottom: 32,
        }}
      >
        <h2 style={{ position: "absolute", top: 12, left: 24, fontSize: 13, fontWeight: 600, color: "#5b4a4a", margin: 0 }}>
          Click một mục tiêu để cursor pursue
        </h2>
        {TARGETS.map((t) => (
          <button
            key={t.id}
            onClick={() => onTargetClick(t)}
            data-wiii-id={`pointy-demo-target-${t.id}`}
            style={{
              position: "absolute",
              left: t.x - 60,
              top: t.y - 20,
              padding: "10px 18px",
              fontSize: 14,
              fontWeight: 700,
              color: "#1c1917",
              background: "white",
              border: "2px solid #b85a33",
              borderRadius: 999,
              cursor: "pointer",
              boxShadow: "0 4px 12px rgba(0,0,0,0.08)",
            }}
          >
            {t.label}
          </button>
        ))}
      </section>

      <section style={{ maxWidth: 880, fontSize: 14, color: "#5b4a4a", lineHeight: 1.7 }}>
        <h3 style={{ color: "#1c1917", fontSize: 18, fontWeight: 700, marginBottom: 12 }}>
          Kiểm tra gì khi review trang này
        </h3>
        <ol style={{ paddingLeft: 20, margin: 0 }}>
          <li>Cursor pursues smoothly — không nhảy step, không glitch.</li>
          <li>Click mục tiêu mới giữa lúc cursor đang chạy → cursor redirect mượt, không cancel + restart.</li>
          <li>Bật peer cursor → 2 cursor di chuyển độc lập, mỗi cái có rAF tick riêng.</li>
          <li>State <code>thinking</code> → cursor bob nhẹ, màu glow giảm.</li>
          <li>State <code>idle</code> → cursor giảm opacity còn 0.5.</li>
          <li><kbd>F12</kbd> → DevTools → Performance: cursor render dùng GPU compositor (translate3d). 60fps khi browser idle.</li>
          <li><kbd>prefers-reduced-motion</kbd> bật ở OS → cursor snap thẳng đến target, bỏ spring (kiểm tra qua DevTools → Rendering tab).</li>
        </ol>
      </section>
    </div>
  );
}

const btnStyle = (color: string): React.CSSProperties => ({
  padding: "10px 18px",
  fontSize: 14,
  fontWeight: 700,
  color: "white",
  background: color,
  border: "none",
  borderRadius: 12,
  cursor: "pointer",
  transition: "background 200ms",
});

const hintStyle: React.CSSProperties = {
  fontSize: 12,
  color: "#a89a8a",
  marginTop: 12,
  lineHeight: 1.5,
};

function Card(props: { title: string; children: React.ReactNode }) {
  return (
    <div
      style={{
        background: "white",
        padding: "20px 24px",
        borderRadius: 16,
        border: "1px solid rgba(161,145,127,0.2)",
        minWidth: 240,
        flex: "1 1 240px",
        maxWidth: 320,
      }}
    >
      <h3 style={{ fontSize: 13, fontWeight: 700, color: "#b85a33", marginTop: 0, marginBottom: 12, textTransform: "uppercase", letterSpacing: 0.5 }}>
        {props.title}
      </h3>
      {props.children}
    </div>
  );
}
