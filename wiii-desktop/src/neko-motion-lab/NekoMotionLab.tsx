import {
  Activity,
  CirclePause,
  Eye,
  Gauge,
  MousePointer2,
  Play,
  RefreshCcw,
  RotateCcw,
  Sparkles,
  Square,
} from "lucide-react";
import { useReducedMotion } from "motion/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { NekoRig } from "./NekoRig";
import {
  NEKO_MOTION_PRESETS,
  NEKO_MOTION_STATES,
  nextNekoMotionState,
  resolveNekoPose,
  type NekoMotionState,
} from "./neko-motion-model";
import "./neko-motion-lab.css";

interface MotionEvent {
  id: number;
  time: string;
  kind: "state" | "gesture" | "system";
  message: string;
}

const DEFAULTS = {
  energy: 0.82,
  gazeX: 0,
  gazeY: 0,
  tail: 0,
  stiffness: 270,
  damping: 28,
};

function formatTime(): string {
  return new Intl.DateTimeFormat("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date());
}

function RangeControl({
  label,
  value,
  min,
  max,
  step,
  display,
  disabled,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  display: string;
  disabled?: boolean;
  onChange: (value: number) => void;
}) {
  return (
    <label className="neko-lab-range">
      <span>
        <span>{label}</span>
        <output>{display}</output>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(Number(event.currentTarget.value))}
      />
    </label>
  );
}

export default function NekoMotionLab() {
  const osReducedMotion = useReducedMotion();
  const [state, setState] = useState<NekoMotionState>("ready");
  const [energy, setEnergy] = useState(DEFAULTS.energy);
  const [gazeX, setGazeX] = useState(DEFAULTS.gazeX);
  const [gazeY, setGazeY] = useState(DEFAULTS.gazeY);
  const [tail, setTail] = useState(DEFAULTS.tail);
  const [stiffness, setStiffness] = useState(DEFAULTS.stiffness);
  const [damping, setDamping] = useState(DEFAULTS.damping);
  const [followPointer, setFollowPointer] = useState(false);
  const [pointerGaze, setPointerGaze] = useState({ x: 0, y: 0 });
  const [simulateReducedMotion, setSimulateReducedMotion] = useState(false);
  const [materialMode, setMaterialMode] = useState(false);
  const [blinkToken, setBlinkToken] = useState(0);
  const [demoRunning, setDemoRunning] = useState(false);
  const [demoStep, setDemoStep] = useState(0);
  const [events, setEvents] = useState<MotionEvent[]>([]);
  const eventId = useRef(0);
  const bootEventRecorded = useRef(false);
  const effectiveReducedMotion = Boolean(osReducedMotion || simulateReducedMotion);
  const preset = NEKO_MOTION_PRESETS[state];

  const addEvent = useCallback((kind: MotionEvent["kind"], message: string) => {
    eventId.current += 1;
    setEvents((current) => [
      { id: eventId.current, time: formatTime(), kind, message },
      ...current,
    ].slice(0, 12));
  }, []);

  const activeGaze = followPointer ? pointerGaze : { x: gazeX, y: gazeY };
  const pose = useMemo(
    () => resolveNekoPose(
      state,
      { energy, gazeX: activeGaze.x, gazeY: activeGaze.y, tail },
      effectiveReducedMotion,
    ),
    [activeGaze.x, activeGaze.y, effectiveReducedMotion, energy, state, tail],
  );

  const chooseState = useCallback((next: NekoMotionState, source = "manual") => {
    setDemoRunning(false);
    setState(next);
    addEvent("state", `${NEKO_MOTION_PRESETS[next].shortLabel} · ${source}`);
  }, [addEvent]);

  const blink = useCallback((source = "manual") => {
    if (effectiveReducedMotion) {
      addEvent("system", `Blink bỏ qua · reduced motion · ${source}`);
      return;
    }
    setBlinkToken((token) => token + 1);
    addEvent("gesture", `Blink · ${source}`);
  }, [addEvent, effectiveReducedMotion]);

  useEffect(() => {
    if (bootEventRecorded.current) return;
    bootEventRecorded.current = true;
    addEvent("system", osReducedMotion ? "OS yêu cầu reduced motion" : "Lab sẵn sàng · autoplay tắt");
  }, [addEvent, osReducedMotion]);

  useEffect(() => {
    if (!demoRunning) return;
    if (effectiveReducedMotion) {
      setDemoRunning(false);
      addEvent("system", "Demo dừng · reduced motion đang bật");
      return;
    }

    const next = NEKO_MOTION_STATES[demoStep];
    setState(next);
    addEvent("state", `${NEKO_MOTION_PRESETS[next].shortLabel} · demo ${demoStep + 1}/8`);
    if (next === "ready") setBlinkToken((token) => token + 1);

    const timer = window.setTimeout(() => {
      if (demoStep >= NEKO_MOTION_STATES.length - 1) {
        setDemoRunning(false);
        setState("ready");
        addEvent("system", "Demo hoàn tất · Neko đã settle về Ready");
      } else {
        setDemoStep((step) => step + 1);
      }
    }, NEKO_MOTION_PRESETS[next].holdMs);

    return () => window.clearTimeout(timer);
  }, [addEvent, demoRunning, demoStep, effectiveReducedMotion]);

  const startDemo = () => {
    if (effectiveReducedMotion) {
      addEvent("system", "Không chạy demo khi reduced motion đang bật");
      return;
    }
    setDemoStep(0);
    setDemoRunning(true);
  };

  const stopDemo = () => {
    setDemoRunning(false);
    addEvent("system", "Demo dừng theo yêu cầu");
  };

  const reset = () => {
    setDemoRunning(false);
    setState("ready");
    setEnergy(DEFAULTS.energy);
    setGazeX(DEFAULTS.gazeX);
    setGazeY(DEFAULTS.gazeY);
    setTail(DEFAULTS.tail);
    setStiffness(DEFAULTS.stiffness);
    setDamping(DEFAULTS.damping);
    setFollowPointer(false);
    setPointerGaze({ x: 0, y: 0 });
    setSimulateReducedMotion(false);
    setMaterialMode(false);
    addEvent("system", "Đã đặt lại baseline nghiên cứu");
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!followPointer || effectiveReducedMotion) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1;
    const y = ((event.clientY - bounds.top) / bounds.height) * 2 - 1;
    setPointerGaze({
      x: Math.max(-1, Math.min(1, x)),
      y: Math.max(-1, Math.min(1, y)),
    });
  };

  return (
    <main className="neko-motion-lab">
      <header className="neko-lab-header">
        <div className="neko-lab-header__identity">
          <img src="/icon-192.png" alt="" aria-hidden="true" />
          <div>
            <p>Wiii Character Systems · R&amp;D</p>
            <h1>Neko Motion Lab</h1>
          </div>
          <span className="neko-lab-badge">v0.1</span>
        </div>
        <div className="neko-lab-header__actions">
          <button
            type="button"
            className="neko-lab-button"
            onClick={() => blink()}
            disabled={materialMode || effectiveReducedMotion}
            title={materialMode ? "Chớp mắt chỉ khả dụng với rig tham số" : "Chớp mắt thủ công"}
          >
            <Eye size={15} /> Chớp mắt
          </button>
          {demoRunning ? (
            <button type="button" className="neko-lab-button" onClick={stopDemo}>
              <Square size={14} /> Dừng demo
            </button>
          ) : (
            <button
              type="button"
              className="neko-lab-button neko-lab-button--primary"
              onClick={startDemo}
              disabled={effectiveReducedMotion}
            >
              <Play size={14} fill="currentColor" /> Chạy 1 vòng
            </button>
          )}
          <button type="button" className="neko-lab-icon-button" onClick={reset} aria-label="Đặt lại lab" title="Đặt lại lab">
            <RotateCcw size={16} />
          </button>
        </div>
      </header>

      <div className="neko-lab-layout">
        <aside className="neko-lab-panel neko-lab-states" aria-label="Trạng thái Neko">
          <div className="neko-lab-section-heading">
            <span>State map</span>
            <small>8 trạng thái</small>
          </div>
          <div className="neko-lab-state-list">
            {NEKO_MOTION_STATES.map((item, index) => {
              const itemPreset = NEKO_MOTION_PRESETS[item];
              const active = state === item;
              return (
                <button
                  type="button"
                  key={item}
                  className="neko-lab-state"
                  data-active={active}
                  aria-pressed={active}
                  onClick={() => chooseState(item)}
                >
                  <span className="neko-lab-state__index">{String(index + 1).padStart(2, "0")}</span>
                  <span>
                    <strong>{itemPreset.label}</strong>
                    <small>{itemPreset.shortLabel}</small>
                  </span>
                  <i />
                </button>
              );
            })}
          </div>
          <div className="neko-lab-state-note">
            <Activity size={15} />
            <p>Chỉ runtime fact mới được đổi state. Mascot không tự suy diễn “thành công”.</p>
          </div>
        </aside>

        <section className="neko-lab-center">
          <div
            className="neko-lab-stage"
            onPointerMove={handlePointerMove}
            onPointerLeave={() => setPointerGaze({ x: 0, y: 0 })}
            onDoubleClick={() => blink("double click")}
          >
            <div className="neko-lab-stage__meta">
              <span><i data-state={state} /> {preset.label}</span>
              <span>{materialMode ? "Material render" : "Parametric rig"}</span>
            </div>
            <div
              className="neko-lab-character"
              role="img"
              aria-label={`Neko: ${preset.label}. ${preset.meaning}`}
            >
              <NekoRig
                pose={pose}
                blinkToken={blinkToken}
                reducedMotion={effectiveReducedMotion}
                stiffness={stiffness}
                damping={damping}
                materialMode={materialMode}
              />
            </div>
            <div className="neko-lab-stage__copy">
              <p>{preset.meaning}</p>
              <span>{preset.evidence}</span>
            </div>
            {followPointer && !effectiveReducedMotion && (
              <div className="neko-lab-pointer-hint"><MousePointer2 size={13} /> Neko đang theo con trỏ trong sân khấu</div>
            )}
          </div>

          <div className="neko-lab-strip" aria-label="Điều khiển nhanh">
            <button
              type="button"
              data-active={!materialMode}
              onClick={() => setMaterialMode(false)}
            >
              <Gauge size={15} /> Rig tham số
            </button>
            <button
              type="button"
              data-active={materialMode}
              onClick={() => setMaterialMode(true)}
            >
              <Sparkles size={15} /> Chất liệu 3D
            </button>
            <span />
            <button
              type="button"
              data-active={followPointer}
              aria-pressed={followPointer}
              onClick={() => {
                setFollowPointer((value) => !value);
                setPointerGaze({ x: 0, y: 0 });
              }}
              disabled={effectiveReducedMotion || materialMode}
            >
              <MousePointer2 size={15} /> Theo con trỏ
            </button>
          </div>

          <section className="neko-lab-contract">
            <div>
              <p>Motion contract</p>
              <h2>Một phản ứng ngắn, rồi đứng yên.</h2>
            </div>
            <dl>
              <div><dt>Tilt</dt><dd>{pose.tilt.toFixed(1)}°</dd></div>
              <div><dt>Lift</dt><dd>{pose.lift.toFixed(1)} px</dd></div>
              <div><dt>Gaze</dt><dd>{pose.gazeX.toFixed(2)} · {pose.gazeY.toFixed(2)}</dd></div>
              <div><dt>Eye</dt><dd>{Math.round(pose.eyeOpen * 100)}%</dd></div>
            </dl>
          </section>
        </section>

        <aside className="neko-lab-panel neko-lab-inspector" aria-label="Bộ điều khiển chuyển động">
          <div className="neko-lab-section-heading">
            <span>Inspector</span>
            <small>Live values</small>
          </div>

          <section className="neko-lab-control-group">
            <h2>Biểu cảm</h2>
            <RangeControl label="Năng lượng" value={energy} min={0} max={1} step={0.01} display={`${Math.round(energy * 100)}%`} onChange={setEnergy} />
            <RangeControl label="Ánh nhìn X" value={gazeX} min={-1} max={1} step={0.01} display={gazeX.toFixed(2)} disabled={followPointer || materialMode} onChange={setGazeX} />
            <RangeControl label="Ánh nhìn Y" value={gazeY} min={-1} max={1} step={0.01} display={gazeY.toFixed(2)} disabled={followPointer || materialMode} onChange={setGazeY} />
            <RangeControl label="Nhịp đuôi" value={tail} min={-1} max={1} step={0.01} display={tail.toFixed(2)} disabled={materialMode} onChange={setTail} />
          </section>

          <section className="neko-lab-control-group">
            <h2>Spring</h2>
            <RangeControl label="Stiffness" value={stiffness} min={100} max={520} step={5} display={String(stiffness)} disabled={effectiveReducedMotion} onChange={setStiffness} />
            <RangeControl label="Damping" value={damping} min={14} max={46} step={1} display={String(damping)} disabled={effectiveReducedMotion} onChange={setDamping} />
          </section>

          <section className="neko-lab-control-group">
            <h2>Khả năng tiếp cận</h2>
            <button
              type="button"
              className="neko-lab-toggle"
              data-active={effectiveReducedMotion}
              aria-pressed={effectiveReducedMotion}
              disabled={Boolean(osReducedMotion)}
              onClick={() => setSimulateReducedMotion((value) => !value)}
            >
              <span><CirclePause size={16} /><span><strong>Reduced motion</strong><small>{osReducedMotion ? "Hệ điều hành đang bật" : "Mô phỏng trong lab"}</small></span></span>
              <i />
            </button>
          </section>

          <section className="neko-lab-events" aria-live="polite">
            <div className="neko-lab-events__heading">
              <h2>Event ledger</h2>
              <button type="button" onClick={() => setEvents([])} aria-label="Xóa event ledger"><RefreshCcw size={13} /></button>
            </div>
            <div className="neko-lab-events__list">
              {events.length === 0 ? (
                <p>Chưa có sự kiện.</p>
              ) : events.map((event) => (
                <div key={event.id} data-kind={event.kind}>
                  <i />
                  <span>{event.message}</span>
                  <time>{event.time}</time>
                </div>
              ))}
            </div>
          </section>
        </aside>
      </div>

      <footer className="neko-lab-footer">
        <span>Identity locked · Neko Family v1</span>
        <button type="button" onClick={() => chooseState(nextNekoMotionState(state), "next state")}>
          State tiếp theo <span>→</span>
        </button>
      </footer>
    </main>
  );
}
