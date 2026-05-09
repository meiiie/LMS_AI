import { synthesizePointySpeech } from "@/api/voice";
import { useSettingsStore } from "@/stores/settings-store";

interface PointyTargetEventDetail {
  selector?: string;
  caption?: string;
  duration_ms?: number;
  source?: string;
}

let installed = false;
let activeAudio: HTMLAudioElement | null = null;
let activeUrl: string | null = null;
let lastSpokenKey = "";
let lastSpokenAt = 0;
const REPEATED_TARGET_DEDUPE_MS = 12_000;

function shouldSpeak(text: string, selector?: string): boolean {
  const settings = useSettingsStore.getState().settings;
  if (settings.pointy_mode !== true) return false;
  if (settings.pointy_voice_enabled !== true) return false;
  const cleaned = text.trim();
  if (!cleaned) return false;
  const now = Date.now();
  const dedupeKey = (selector || cleaned).trim().toLowerCase();
  if (dedupeKey === lastSpokenKey && now - lastSpokenAt < REPEATED_TARGET_DEDUPE_MS) return false;
  return true;
}

function stopActiveAudio(): void {
  if (activeAudio) {
    activeAudio.pause();
    activeAudio.src = "";
    activeAudio = null;
  }
  if (activeUrl) {
    URL.revokeObjectURL(activeUrl);
    activeUrl = null;
  }
}

async function speak(text: string, selector?: string): Promise<void> {
  const cleaned = text.trim().slice(0, 320);
  if (!shouldSpeak(cleaned, selector)) return;
  lastSpokenKey = (selector || cleaned).trim().toLowerCase();
  lastSpokenAt = Date.now();
  try {
    const blob = await synthesizePointySpeech(cleaned);
    if (blob.size === 0) return;
    stopActiveAudio();
    activeUrl = URL.createObjectURL(blob);
    activeAudio = new Audio(activeUrl);
    activeAudio.preload = "auto";
    activeAudio.volume = 0.92;
    activeAudio.onended = stopActiveAudio;
    await activeAudio.play();
    if (import.meta.env.DEV) {
      console.info("[POINTY-VOICE] speech started", { bytes: blob.size });
    }
  } catch (err) {
    if (import.meta.env.DEV) {
      console.warn(
        "[POINTY-VOICE] speech skipped:",
        err instanceof Error ? err.message : String(err),
      );
    }
  }
}

export function ensurePointyVoiceBridge(): void {
  if (installed || typeof window === "undefined") return;
  installed = true;
  window.addEventListener("wiii:pointy:target", (event) => {
    const detail = (event as CustomEvent<PointyTargetEventDetail>).detail || {};
    const caption = typeof detail.caption === "string" ? detail.caption : "";
    const selector = typeof detail.selector === "string" ? detail.selector : undefined;
    void speak(caption, selector);
  });
  window.addEventListener("wiii:pointy:voice-stop", stopActiveAudio);
}

export function stopPointyVoice(): void {
  stopActiveAudio();
}
