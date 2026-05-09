/**
 * Sprint 141: Avatar Preview Lab — dev tool for inspecting ALL avatar capabilities.
 * Access via: http://localhost:1420?preview=avatar
 *
 * Features:
 * - Toggle between SVG (legacy) and Rive (new) rendering
 * - 6 lifecycle states (idle, listening, thinking, speaking, complete, error)
 * - 5 mood overlays (excited, warm, concerned, gentle, neutral)
 * - Soul emotion face sliders (eyeOpenness, pupilSize, mouthCurve, blush, etc.)
 * - Size comparison (3-tier: tiny/medium/large)
 * - Auto-demo cycling mode
 * - Rive state machine input monitor
 */
import { useState, useEffect, useCallback, useRef } from "react";
import { WiiiAvatar } from "@/lib/avatar/WiiiAvatar";
import { RiveWiiiAvatar } from "@/lib/avatar/rive/RiveWiiiAvatar";
import { resolveAvatarState } from "@/lib/avatar/rive/rive-adapter";
import type { AvatarState, SoulEmotionData } from "@/lib/avatar/types";
import type { MoodType } from "@/lib/avatar/mood-theme";

type RenderMode = "svg" | "rive" | "rive-demo";

/**
 * Demo .riv uses "State Machine 1" — the downloaded community file.
 * The real Wiii .riv will use "main" (our spec).
 */
const DEMO_STATE_MACHINE = "State Machine 1";

const ALL_STATES: AvatarState[] = [
  "idle",
  "listening",
  "thinking",
  "speaking",
  "complete",
  "error",
];

const ALL_MOODS: MoodType[] = [
  "neutral",
  "excited",
  "warm",
  "concerned",
  "gentle",
];

const STATE_LABELS: Record<AvatarState, string> = {
  idle: "Chờ — mỉm cười nhẹ",
  listening: "Lắng nghe — mắt mở to",
  thinking: "Suy nghĩ — nhíu mày",
  speaking: "Nói — miệng chuyển động",
  complete: "Hoàn thành — cười rạng rỡ",
  error: "Lỗi — cau mày",
};

const MOOD_LABELS: Record<MoodType, { emoji: string; desc: string }> = {
  neutral: { emoji: ":|", desc: "Bình thường" },
  excited: { emoji: ":D", desc: "Hưng khởi, nhanh, lấp lánh" },
  warm: { emoji: ":)", desc: "Ấm áp, dịu dàng, ửng hồng" },
  concerned: { emoji: ":(", desc: "Lo lắng, chân mày nhíu" },
  gentle: { emoji: "-_-", desc: "Nhẹ nhàng, chậm rãi" },
};

/** Preset soul emotion expressions for quick testing */
const SOUL_PRESETS: Record<
  string,
  { label: string; mood: MoodType; face: Record<string, number>; intensity: number }
> = {
  happy: {
    label: "Vui vẻ",
    mood: "warm",
    face: { mouthCurve: 0.8, eyeOpenness: 1.1, blush: 0.4, pupilSize: 1.1 },
    intensity: 0.9,
  },
  surprised: {
    label: "Ngạc nhiên",
    mood: "excited",
    face: { eyeOpenness: 1.4, mouthOpenness: 0.6, pupilSize: 1.3, browRaise: 0.5 },
    intensity: 1.0,
  },
  thinking_deep: {
    label: "Suy tư",
    mood: "gentle",
    face: { eyeOpenness: 0.8, browTilt: 0.3, pupilOffsetY: -0.2, mouthCurve: 0.1 },
    intensity: 0.7,
  },
  shy: {
    label: "Ngại ngùng",
    mood: "warm",
    face: { blush: 0.8, eyeOpenness: 0.7, mouthCurve: 0.3, mouthWidth: 0.7 },
    intensity: 0.85,
  },
  worried: {
    label: "Lo lắng",
    mood: "concerned",
    face: { browTilt: -0.3, eyeOpenness: 1.1, mouthCurve: -0.2, pupilSize: 0.9 },
    intensity: 0.8,
  },
  sleepy: {
    label: "Buồn ngủ",
    mood: "gentle",
    face: { eyeOpenness: 0.5, mouthOpenness: 0.3, browRaise: -0.2, blinkRate: 0.3 },
    intensity: 0.6,
  },
  confident: {
    label: "Tự tin",
    mood: "excited",
    face: { mouthCurve: 0.5, eyeOpenness: 0.9, browRaise: 0.3, pupilSize: 1.05 },
    intensity: 0.75,
  },
  sad: {
    label: "Buồn",
    mood: "concerned",
    face: { mouthCurve: -0.4, eyeOpenness: 0.75, browTilt: -0.4, blush: 0.1 },
    intensity: 0.85,
  },
  pouty: {
    label: "Phụng phịu",
    mood: "gentle",
    face: { mouthShape: 4, mouthCurve: 0.1, blush: 0.5, eyeOpenness: 0.85, browRaise: -0.1 },
    intensity: 0.9,
  },
  dizzy: {
    label: "Choáng váng",
    mood: "concerned",
    face: { mouthOpenness: 0.4, browTilt: -0.3, eyeOpenness: 1.2, mouthShape: 3, pupilSize: 0.7 },
    intensity: 1.0,
  },
  cat_smile: {
    label: "Mèo cười",
    mood: "excited",
    face: { mouthShape: 1, eyeShape: 0.6, mouthCurve: 0.5, blush: 0.3, pupilSize: 1.15 },
    intensity: 0.85,
  },
  crying: {
    label: "Khóc",
    mood: "concerned",
    face: { browRaise: 0.35, mouthCurve: -0.3, eyeOpenness: 0.9, blush: 0.15, browTilt: -0.3 },
    intensity: 0.9,
  },
};

const FACE_SLIDERS = [
  { key: "eyeOpenness", label: "Mắt mở", min: 0.3, max: 1.5, step: 0.05, default: 1.0 },
  { key: "pupilSize", label: "Đồng tử", min: 0.5, max: 1.5, step: 0.05, default: 1.0 },
  { key: "eyeShape", label: "Mắt cười ^_^", min: 0, max: 1.0, step: 0.05, default: 0 },
  { key: "mouthCurve", label: "Cười", min: -0.5, max: 1.0, step: 0.05, default: 0.3 },
  { key: "mouthOpenness", label: "Miệng mở", min: 0, max: 1.0, step: 0.05, default: 0 },
  { key: "mouthWidth", label: "Miệng rộng", min: 0.5, max: 1.5, step: 0.05, default: 1.0 },
  { key: "browRaise", label: "Chân mày", min: -0.5, max: 0.5, step: 0.05, default: 0 },
  { key: "browTilt", label: "Mày nghiêng", min: -0.5, max: 0.5, step: 0.05, default: 0 },
  { key: "blush", label: "Đỏ mặt", min: 0, max: 1.0, step: 0.05, default: 0 },
  { key: "pupilOffsetX", label: "Nhìn LR", min: -0.3, max: 0.3, step: 0.02, default: 0 },
  { key: "pupilOffsetY", label: "Nhìn UD", min: -0.3, max: 0.3, step: 0.02, default: 0 },
];

/** Mouth shape options */
const MOUTH_SHAPES = [
  { value: 0, label: "Normal", kaomoji: ":)" },
  { value: 1, label: "Cat", kaomoji: "ω" },
  { value: 2, label: "Dot", kaomoji: "·" },
  { value: 3, label: "Wavy", kaomoji: "～" },
  { value: 4, label: "Pout", kaomoji: "ε" },
];

// Styles
const S = {
  page: {
    background: "#0f0f1a",
    color: "#e0e0e0",
    fontFamily: "var(--font-body)",
    minHeight: "100vh",
    padding: "24px 32px",
  } as const,
  h1: { fontSize: 22, fontWeight: 700, color: "#fff", margin: 0 } as const,
  h2: {
    fontSize: 15,
    fontWeight: 600,
    color: "#f97316",
    borderBottom: "1px solid #2a2a3e",
    paddingBottom: 6,
    marginBottom: 16,
    marginTop: 0,
  } as const,
  card: {
    background: "#1a1a2e",
    borderRadius: 12,
    border: "1px solid #2a2a3e",
    padding: 16,
  } as const,
  btn: (active: boolean) =>
    ({
      padding: "5px 12px",
      borderRadius: 6,
      border: "none",
      cursor: "pointer",
      fontSize: 12,
      fontWeight: 500,
      background: active ? "#f97316" : "#2a2a3e",
      color: active ? "#fff" : "#999",
      transition: "all 0.15s",
    }) as const,
  tag: {
    fontSize: 10,
    padding: "2px 6px",
    borderRadius: 4,
    background: "#2a2a3e",
    color: "#888",
  } as const,
  modeBtn: (active: boolean) =>
    ({
      padding: "6px 16px",
      borderRadius: 8,
      border: active ? "2px solid #f97316" : "2px solid #333",
      cursor: "pointer",
      fontSize: 13,
      fontWeight: 600,
      background: active ? "#2d1a0a" : "#1a1a2e",
      color: active ? "#f97316" : "#666",
      transition: "all 0.2s",
    }) as const,
};

/** The Avatar component to render based on mode */
function AvatarRenderer({
  mode,
  state,
  size,
  mood,
  soulEmotion,
}: {
  mode: RenderMode;
  state: AvatarState;
  size: number;
  mood: MoodType;
  soulEmotion: SoulEmotionData | null;
}) {
  if (mode === "rive") {
    return (
      <RiveWiiiAvatar
        key="rive-wiii"
        state={state}
        size={size}
        mood={mood}
        soulEmotion={soulEmotion}
      />
    );
  }
  if (mode === "rive-demo") {
    return (
      <RiveWiiiAvatar
        key="rive-demo"
        state={state}
        size={size}
        mood={mood}
        soulEmotion={soulEmotion}
        riveSrc="/animations/wiii-demo.riv"
        stateMachine={DEMO_STATE_MACHINE}
      />
    );
  }
  return (
    <WiiiAvatar
      state={state}
      size={size}
      mood={mood}
      soulEmotion={soulEmotion}
    />
  );
}

export function AvatarPreview() {
  // Override body overflow:hidden so preview page can scroll
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "auto";
    document.body.style.userSelect = "auto";
    return () => {
      document.body.style.overflow = prev;
      document.body.style.userSelect = "";
    };
  }, []);

  // State
  const [renderMode, setRenderMode] = useState<RenderMode>("svg");
  const [activeState, setActiveState] = useState<AvatarState>("idle");
  const [activeMood, setActiveMood] = useState<MoodType>("neutral");
  const [soulEnabled, setSoulEnabled] = useState(false);
  const [soulIntensity, setSoulIntensity] = useState(0.8);
  const [soulMood, setSoulMood] = useState<MoodType>("warm");
  const [faceValues, setFaceValues] = useState<Record<string, number>>(() => {
    const init: Record<string, number> = {};
    FACE_SLIDERS.forEach((s) => (init[s.key] = s.default));
    return init;
  });
  const [autoCycle, setAutoCycle] = useState(false);
  const cycleRef = useRef(0);

  // Derived soul emotion
  const soulEmotion: SoulEmotionData | null = soulEnabled
    ? { mood: soulMood, face: { ...faceValues }, intensity: soulIntensity }
    : null;

  // Resolved Rive inputs (for debug display)
  const riveInputs = resolveAvatarState(activeState, activeMood, soulEmotion);

  // Apply preset
  const applyPreset = useCallback(
    (key: string) => {
      const p = SOUL_PRESETS[key];
      if (!p) return;
      setSoulEnabled(true);
      setSoulMood(p.mood);
      setSoulIntensity(p.intensity);
      const newFace: Record<string, number> = {};
      FACE_SLIDERS.forEach((s) => (newFace[s.key] = s.default));
      Object.entries(p.face).forEach(([k, v]) => (newFace[k] = v));
      setFaceValues(newFace);
    },
    [],
  );

  // Reset sliders
  const resetFace = useCallback(() => {
    const init: Record<string, number> = {};
    FACE_SLIDERS.forEach((s) => (init[s.key] = s.default));
    setFaceValues(init);
    setSoulIntensity(0.8);
  }, []);

  // Auto-cycle demo
  useEffect(() => {
    if (!autoCycle) return;
    const presetKeys = Object.keys(SOUL_PRESETS);
    const interval = setInterval(() => {
      const idx = cycleRef.current % (ALL_STATES.length + presetKeys.length);
      if (idx < ALL_STATES.length) {
        setActiveState(ALL_STATES[idx]);
        setSoulEnabled(false);
        setActiveMood(ALL_MOODS[idx % ALL_MOODS.length]);
      } else {
        const pk = presetKeys[idx - ALL_STATES.length];
        setActiveState("speaking");
        applyPreset(pk);
      }
      cycleRef.current++;
    }, 2500);
    return () => clearInterval(interval);
  }, [autoCycle, applyPreset]);

  return (
    <div style={S.page}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 24 }}>
        <AvatarRenderer
          mode={renderMode}
          state={activeState}
          size={48}
          mood={activeMood}
          soulEmotion={soulEmotion}
        />
        <div>
          <h1 style={S.h1}>Wiii Avatar Lab</h1>
          <p style={{ fontSize: 12, opacity: 0.5, margin: "2px 0 0" }}>
            Sprint 144 — "Linh Hồn Chuyên Nghiệp" Pro Animation
          </p>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          {/* Render mode toggle */}
          <button
            onClick={() => setRenderMode("svg")}
            style={S.modeBtn(renderMode === "svg")}
          >
            SVG
          </button>
          <button
            onClick={() => setRenderMode("rive-demo")}
            style={S.modeBtn(renderMode === "rive-demo")}
          >
            Rive Demo
          </button>
          <button
            onClick={() => setRenderMode("rive")}
            style={S.modeBtn(renderMode === "rive")}
          >
            Rive Wiii
          </button>
          <button
            onClick={() => setAutoCycle(!autoCycle)}
            style={{
              ...S.btn(autoCycle),
              padding: "8px 16px",
              fontSize: 13,
              background: autoCycle ? "#22c55e" : "#2a2a3e",
            }}
          >
            {autoCycle ? "|| Pause" : "> Demo"}
          </button>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 24 }}>
        {/* Left: Main Preview */}
        <div>
          {/* Hero Avatar */}
          <div
            style={{
              ...S.card,
              display: "flex",
              justifyContent: "center",
              alignItems: "center",
              height: 300,
              marginBottom: 20,
              position: "relative",
            }}
          >
            <AvatarRenderer
              mode={renderMode}
              state={activeState}
              size={200}
              mood={activeMood}
              soulEmotion={soulEmotion}
            />
            <div
              style={{
                position: "absolute",
                bottom: 10,
                left: 16,
                display: "flex",
                gap: 6,
              }}
            >
              <span style={{ ...S.tag, background: renderMode === "rive" ? "#1a2e1a" : "#2a2a3e", color: renderMode === "rive" ? "#4ade80" : "#888" }}>
                {renderMode.toUpperCase()}
              </span>
              <span style={S.tag}>state: {activeState}</span>
              <span style={S.tag}>mood: {activeMood}</span>
              {soulEnabled && (
                <span style={{ ...S.tag, background: "#3b2a10", color: "#f97316" }}>
                  soul: {soulMood} ({(soulIntensity * 100).toFixed(0)}%)
                </span>
              )}
            </div>
          </div>

          {/* State buttons */}
          <section style={{ marginBottom: 20 }}>
            <h2 style={S.h2}>Lifecycle State</h2>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {ALL_STATES.map((s) => (
                <button key={s} onClick={() => setActiveState(s)} style={S.btn(activeState === s)}>
                  {s}
                </button>
              ))}
            </div>
            <p style={{ fontSize: 11, opacity: 0.5, margin: "6px 0 0" }}>
              {STATE_LABELS[activeState]}
            </p>
          </section>

          {/* Mood buttons */}
          <section style={{ marginBottom: 20 }}>
            <h2 style={S.h2}>Mood Overlay</h2>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {ALL_MOODS.map((m) => (
                <button key={m} onClick={() => setActiveMood(m)} style={S.btn(activeMood === m)}>
                  {MOOD_LABELS[m].emoji} {m}
                </button>
              ))}
            </div>
            <p style={{ fontSize: 11, opacity: 0.5, margin: "6px 0 0" }}>
              {MOOD_LABELS[activeMood].desc}
            </p>
          </section>

          {/* Soul Presets */}
          <section style={{ marginBottom: 20 }}>
            <h2 style={S.h2}>Soul Emotion Presets</h2>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {Object.entries(SOUL_PRESETS).map(([key, p]) => (
                <button
                  key={key}
                  onClick={() => applyPreset(key)}
                  style={{
                    ...S.btn(soulEnabled && soulMood === p.mood),
                    fontSize: 13,
                    padding: "6px 14px",
                  }}
                >
                  {p.label}
                </button>
              ))}
              {soulEnabled && (
                <button
                  onClick={() => {
                    setSoulEnabled(false);
                    resetFace();
                  }}
                  style={{
                    ...S.btn(false),
                    color: "#ef4444",
                    borderColor: "#ef4444",
                  }}
                >
                  x Clear
                </button>
              )}
            </div>
          </section>

          {/* Reaction Chains */}
          <section style={{ marginBottom: 20 }}>
            <h2 style={S.h2}>Reaction Chains (cinematic arcs)</h2>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {[
                { id: "surprise_to_smile", label: "Ngạc nhiên → Cười", desc: "surprise→sparkle→nod" },
                { id: "panic_to_relief", label: "Hoảng hốt → Thở phào", desc: "panic→flinch(×)→sigh" },
                { id: "love_struck", label: "Tình yêu sét đánh", desc: "doki→blush→shy" },
                { id: "false_alarm", label: "Hụt hồn", desc: "startle(×)→perk→giggle" },
                { id: "frustration", label: "Bực bội", desc: "hmph→twitch→sigh" },
              ].map((chain) => (
                <button
                  key={chain.id}
                  onClick={() => {
                    // Trigger chain by switching to error then back (for panic_to_relief)
                    // or by toggling state to trigger reactions
                    if (chain.id === "panic_to_relief") {
                      setActiveState("idle");
                      setTimeout(() => setActiveState("error"), 50);
                    } else {
                      // Quick state toggle to trigger chain reactions
                      setActiveState("idle");
                      setTimeout(() => {
                        if (chain.id === "love_struck") { setActiveMood("warm"); applyPreset("shy"); }
                        else if (chain.id === "surprise_to_smile") { setActiveState("complete"); setActiveMood("excited"); }
                        else if (chain.id === "false_alarm") { setActiveMood("excited"); setActiveState("listening"); }
                        else if (chain.id === "frustration") { setActiveMood("concerned"); setActiveState("thinking"); }
                      }, 50);
                    }
                  }}
                  style={{ ...S.btn(false), fontSize: 12, padding: "5px 12px" }}
                  title={chain.desc}
                >
                  {chain.label}
                </button>
              ))}
            </div>
          </section>

          {/* Indicator Matrix — which indicator shows for each state×mood combo */}
          <section style={{ marginBottom: 20 }}>
            <h2 style={S.h2}>Indicator Matrix (state x mood)</h2>
            <div style={{ overflowX: "auto" }}>
              <table style={{ fontSize: 10, borderCollapse: "collapse", width: "100%" }}>
                <thead>
                  <tr>
                    <th style={{ padding: "4px 6px", borderBottom: "1px solid #333", color: "#888", textAlign: "left" }}>State</th>
                    {ALL_MOODS.map((m) => (
                      <th key={m} style={{ padding: "4px 6px", borderBottom: "1px solid #333", color: "#888" }}>{m}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {ALL_STATES.map((st) => (
                    <tr key={st}>
                      <td style={{ padding: "3px 6px", borderBottom: "1px solid #222", color: "#ccc", fontWeight: 600 }}>{st}</td>
                      {ALL_MOODS.map((m) => {
                        // Inline computation of indicator (mirrors manga-indicators.ts logic)
                        let ind = "none";
                        if (m === "concerned" && st === "error") ind = "anger_vein";
                        else if (m === "concerned" && st === "listening") ind = "gloom_lines";
                        else if (m === "concerned" && st === "thinking") ind = "spiral_eyes";
                        else if (m === "concerned" && st === "speaking") ind = "sweat";
                        else if (m === "excited" && st === "complete") ind = "flower_bloom";
                        else if (m === "gentle" && st === "idle") ind = "zzz";
                        else if (m === "excited" && st === "thinking") ind = "fire_spirit";
                        else if (m === "excited" && (st === "idle" || st === "speaking")) ind = "heart";
                        else if (m === "warm" && st === "idle") ind = "heart";
                        else if (m === "concerned" && st === "idle") ind = "sweat";
                        else if (st === "complete") ind = "sparkle";
                        else if (st === "thinking") ind = "thought";
                        else if (st === "error") ind = "sweat";
                        else if (st === "idle") ind = "music";
                        else if (st === "listening") ind = "exclaim";
                        const isActive = activeState === st && activeMood === m;
                        return (
                          <td
                            key={m}
                            onClick={() => { setActiveState(st); setActiveMood(m); }}
                            style={{
                              padding: "3px 6px",
                              borderBottom: "1px solid #222",
                              textAlign: "center",
                              cursor: "pointer",
                              background: isActive ? "#2d1a0a" : "transparent",
                              color: ind === "none" ? "#444" : "#e0e0e0",
                              fontFamily: "monospace",
                            }}
                          >
                            {ind === "none" ? "-" : ind.replace("_", " ")}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {/* All States Grid */}
          <section>
            <h2 style={S.h2}>All States @ 100px (mood: {activeMood})</h2>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 12 }}>
              {ALL_STATES.map((st) => (
                <div
                  key={st}
                  style={{ textAlign: "center", cursor: "pointer" }}
                  onClick={() => setActiveState(st)}
                >
                  <div
                    style={{
                      ...S.card,
                      display: "flex",
                      justifyContent: "center",
                      alignItems: "center",
                      height: 130,
                      padding: 8,
                      border:
                        activeState === st
                          ? "2px solid #f97316"
                          : "1px solid #2a2a3e",
                    }}
                  >
                    <AvatarRenderer
                      mode={renderMode}
                      state={st}
                      size={100}
                      mood={activeMood}
                      soulEmotion={null}
                    />
                  </div>
                  <div
                    style={{
                      marginTop: 6,
                      fontSize: 11,
                      fontWeight: 600,
                      color: activeState === st ? "#f97316" : "#888",
                    }}
                  >
                    {st}
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>

        {/* Right: Control Panel */}
        <div>
          <div style={{ ...S.card, position: "sticky", top: 24 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
              <h2 style={{ ...S.h2, borderBottom: "none", marginBottom: 0, flex: 1 }}>
                Soul Emotion Control
              </h2>
              <label style={{ fontSize: 11, display: "flex", alignItems: "center", gap: 4 }}>
                <input
                  type="checkbox"
                  checked={soulEnabled}
                  onChange={(e) => setSoulEnabled(e.target.checked)}
                  style={{ accentColor: "#f97316" }}
                />
                ON
              </label>
            </div>

            {/* Soul Mood */}
            <div style={{ marginBottom: 12 }}>
              <label style={{ fontSize: 11, color: "#888", display: "block", marginBottom: 4 }}>
                Soul Mood
              </label>
              <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                {ALL_MOODS.map((m) => (
                  <button
                    key={m}
                    onClick={() => {
                      setSoulMood(m);
                      setSoulEnabled(true);
                    }}
                    style={{
                      ...S.btn(soulMood === m && soulEnabled),
                      fontSize: 11,
                      padding: "3px 8px",
                    }}
                  >
                    {MOOD_LABELS[m].emoji}
                  </button>
                ))}
              </div>
            </div>

            {/* Intensity */}
            <div style={{ marginBottom: 16 }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 2 }}>
                <label style={{ fontSize: 11, color: "#888" }}>Intensity</label>
                <span style={{ fontSize: 11, color: "#f97316" }}>
                  {(soulIntensity * 100).toFixed(0)}%
                </span>
              </div>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={soulIntensity}
                onChange={(e) => {
                  setSoulIntensity(parseFloat(e.target.value));
                  setSoulEnabled(true);
                }}
                style={{ width: "100%", accentColor: "#f97316" }}
              />
            </div>

            {/* Face Sliders */}
            <div
              style={{
                borderTop: "1px solid #2a2a3e",
                paddingTop: 12,
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: "#ccc" }}>
                  Face Parameters
                </span>
                <button
                  onClick={resetFace}
                  style={{
                    fontSize: 10,
                    background: "none",
                    border: "1px solid #444",
                    color: "#888",
                    padding: "2px 8px",
                    borderRadius: 4,
                    cursor: "pointer",
                  }}
                >
                  Reset
                </button>
              </div>
              {FACE_SLIDERS.map((slider) => (
                <div key={slider.key} style={{ marginBottom: 8 }}>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      marginBottom: 1,
                    }}
                  >
                    <label style={{ fontSize: 11, color: "#888" }}>{slider.label}</label>
                    <span style={{ fontSize: 10, color: "#666", fontFamily: "monospace" }}>
                      {faceValues[slider.key]?.toFixed(2)}
                    </span>
                  </div>
                  <input
                    type="range"
                    min={slider.min}
                    max={slider.max}
                    step={slider.step}
                    value={faceValues[slider.key] ?? slider.default}
                    onChange={(e) => {
                      setFaceValues((prev) => ({
                        ...prev,
                        [slider.key]: parseFloat(e.target.value),
                      }));
                      setSoulEnabled(true);
                    }}
                    style={{ width: "100%", accentColor: "#f97316", height: 4 }}
                  />
                </div>
              ))}

              {/* Mouth Shape selector */}
              <div style={{ marginTop: 12, paddingTop: 10, borderTop: "1px solid #2a2a3e" }}>
                <span style={{ fontSize: 11, color: "#888", display: "block", marginBottom: 6 }}>
                  Mieng (mouthShape)
                </span>
                <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                  {MOUTH_SHAPES.map((ms) => (
                    <button
                      key={ms.value}
                      onClick={() => {
                        setFaceValues((prev) => ({ ...prev, mouthShape: ms.value }));
                        setSoulEnabled(true);
                      }}
                      style={{
                        ...S.btn((faceValues.mouthShape ?? 0) === ms.value),
                        fontSize: 11,
                        padding: "3px 8px",
                      }}
                    >
                      {ms.kaomoji} {ms.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Rive Debug: Resolved inputs */}
            {(renderMode === "rive" || renderMode === "rive-demo") && (
              <div
                style={{
                  marginTop: 12,
                  borderTop: "1px solid #2a2a3e",
                  paddingTop: 10,
                }}
              >
                <label style={{ fontSize: 10, color: "#666", display: "block", marginBottom: 4 }}>
                  Rive State Machine Inputs
                </label>
                <pre
                  style={{
                    fontSize: 9,
                    background: "#12121e",
                    padding: 8,
                    borderRadius: 6,
                    color: "#6b8",
                    overflow: "auto",
                    maxHeight: 160,
                    margin: 0,
                    lineHeight: 1.4,
                  }}
                >
                  {JSON.stringify(riveInputs.inputs, null, 2)}
                </pre>
              </div>
            )}

            {/* Soul JSON */}
            {soulEnabled && (
              <div
                style={{
                  marginTop: 12,
                  borderTop: "1px solid #2a2a3e",
                  paddingTop: 10,
                }}
              >
                <label style={{ fontSize: 10, color: "#666", display: "block", marginBottom: 4 }}>
                  SoulEmotionData (JSON)
                </label>
                <pre
                  style={{
                    fontSize: 10,
                    background: "#12121e",
                    padding: 8,
                    borderRadius: 6,
                    color: "#8b8",
                    overflow: "auto",
                    maxHeight: 120,
                    margin: 0,
                  }}
                >
                  {JSON.stringify(soulEmotion, null, 2)}
                </pre>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
