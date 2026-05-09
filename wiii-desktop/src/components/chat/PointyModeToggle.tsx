/**
 * Pointy mode controls.
 *
 * Pointy mode routes the next chat turns through Wiii's cursor body.
 * Pointy voice is a separate opt-in layer: the cursor can speak short
 * captions through the backend ElevenLabs proxy without exposing API keys.
 */

import { useEffect, useState } from "react";
import { MousePointer2, Volume2, VolumeX } from "lucide-react";
import { ApiHttpError } from "@/api/client";
import { getVoiceStatus, updateVoiceConfig } from "@/api/voice";
import type { VoiceConfigResponse, VoiceStatusResponse } from "@/api/voice";
import {
  ensurePointyVoiceBridge,
  stopPointyVoice,
} from "@/pointy-host/voice";
import { useSettingsStore } from "@/stores/settings-store";
import { useToastStore } from "@/stores/toast-store";

type VoiceRuntimeStatus = VoiceStatusResponse | VoiceConfigResponse;

function getKeyHint(status: VoiceRuntimeStatus | null): string | null {
  if (!status || !("key_hint" in status)) return null;
  return status.key_hint ?? null;
}

export function PointyModeToggle() {
  const pointyMode = useSettingsStore(
    (s) => s.settings.pointy_mode === true,
  );
  const pointyVoiceEnabled = useSettingsStore(
    (s) => s.settings.pointy_voice_enabled === true,
  );
  const updateSettings = useSettingsStore((s) => s.updateSettings);
  const addToast = useToastStore((s) => s.addToast);
  const [voiceStatus, setVoiceStatus] = useState<VoiceRuntimeStatus | null>(null);
  const [voiceStatusLoading, setVoiceStatusLoading] = useState(false);
  const [voiceStatusError, setVoiceStatusError] = useState(false);
  const [showVoiceSetup, setShowVoiceSetup] = useState(false);
  const [apiKeyDraft, setApiKeyDraft] = useState("");
  const [savingVoiceConfig, setSavingVoiceConfig] = useState(false);

  useEffect(() => {
    ensurePointyVoiceBridge();
  }, []);

  useEffect(() => {
    if (!pointyMode) {
      setVoiceStatus(null);
      setVoiceStatusError(false);
      setShowVoiceSetup(false);
      setApiKeyDraft("");
      return;
    }
    let cancelled = false;
    setVoiceStatusLoading(true);
    setVoiceStatusError(false);
    void getVoiceStatus()
      .then((status) => {
        if (!cancelled) setVoiceStatus(status);
      })
      .catch(() => {
        if (!cancelled) setVoiceStatusError(true);
      })
      .finally(() => {
        if (!cancelled) setVoiceStatusLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [pointyMode]);

  const onToggle = () => {
    void updateSettings({ pointy_mode: !pointyMode });
    if (pointyMode) {
      stopPointyVoice();
      setShowVoiceSetup(false);
      setApiKeyDraft("");
    }
  };

  const onVoiceToggle = async () => {
    const next = !pointyVoiceEnabled;
    if (next) {
      setVoiceStatusLoading(true);
      setVoiceStatusError(false);
      try {
        const status = await getVoiceStatus();
        setVoiceStatus(status);
        if (!status.enabled || !status.configured) {
          setShowVoiceSetup(true);
          addToast(
            "info",
            "Pointy voice chưa sẵn sàng. Dán ElevenLabs key vào ô vừa mở để Wiii lưu server-side.",
            5200,
          );
          return;
        }
      } catch {
        setVoiceStatusError(true);
        addToast("error", "Wiii chưa kiểm tra được backend voice. Thử lại sau nhé.", 4500);
        return;
      } finally {
        setVoiceStatusLoading(false);
      }
    }
    void updateSettings({ pointy_voice_enabled: next });
    if (!next) {
      stopPointyVoice();
    } else {
      addToast("success", "Pointy voice đã sẵn sàng nói cùng con trỏ.", 3200);
    }
  };

  const onSaveVoiceConfig = async () => {
    const apiKey = apiKeyDraft.trim();
    if (!apiKey) {
      addToast("error", "Dán ElevenLabs API key trước khi lưu nhé.", 3600);
      return;
    }
    setSavingVoiceConfig(true);
    try {
      const status = await updateVoiceConfig({
        enabled: true,
        api_key: apiKey,
      });
      setVoiceStatus(status);
      setApiKeyDraft("");
      if (!status.configured) {
        addToast("error", "Đã lưu key nhưng voice_id vẫn thiếu. Kiểm tra cấu hình backend nhé.", 5200);
        return;
      }
      await updateSettings({ pointy_voice_enabled: true });
      setShowVoiceSetup(false);
      addToast("success", "Đã lưu ElevenLabs key an toàn và bật Pointy voice.", 4200);
    } catch (error) {
      const needsAdmin = error instanceof ApiHttpError && error.status === 403;
      addToast(
        "error",
        needsAdmin
          ? "Cần quyền platform admin để lưu key voice cho workspace này."
          : "Chưa lưu được ElevenLabs key. Backend voice config chưa sẵn sàng.",
        5200,
      );
    } finally {
      setSavingVoiceConfig(false);
    }
  };

  const voiceReady = voiceStatus?.enabled === true && voiceStatus.configured === true;
  const keyHint = getKeyHint(voiceStatus);
  const voiceTitle = voiceStatusLoading
    ? "Wiii đang kiểm tra ElevenLabs backend..."
    : pointyVoiceEnabled
      ? "Pointy voice đang BẬT. Wiii sẽ phát âm thanh cho caption ngắn của con trỏ."
      : voiceReady
        ? "Bật giọng nói Pointy bằng ElevenLabs."
        : voiceStatusError
          ? "Chưa kiểm tra được backend voice. Click để thử lại."
          : "Pointy voice cần ElevenLabs key được lưu server-side trước khi bật.";

  return (
    <div
      className="relative inline-flex"
      role="group"
      aria-label="Điều khiển Pointy mode và Pointy voice"
      data-wiii-id="pointy-mode-controls"
    >
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={onToggle}
          className={`
            flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs
            transition-colors
            ${
              pointyMode
                ? "bg-orange-500 text-white hover:bg-orange-600"
                : "text-text-secondary hover:text-text hover:bg-surface-tertiary"
            }
          `}
          title={
            pointyMode
              ? "Pointy mode đang BẬT - gõ chat sẽ điều khiển cursor trực tiếp. Click để tắt."
              : "Pointy mode đang TẮT - gõ chat trò chuyện bình thường. Click để BẬT cursor agent mode."
          }
          aria-label={pointyMode ? "Tắt Pointy mode" : "Bật Pointy mode"}
          aria-pressed={pointyMode}
          data-wiii-id="pointy-mode-toggle"
        >
          <MousePointer2 size={13} strokeWidth={pointyMode ? 2.5 : 2} />
          <span>Pointy{pointyMode ? " ON" : ""}</span>
        </button>
        {pointyMode && (
          <button
            type="button"
            onClick={onVoiceToggle}
            className={`
              flex items-center gap-1 px-2 py-1 rounded-full text-xs transition-colors
              ${
                pointyVoiceEnabled
                  ? "bg-amber-100 text-amber-800 hover:bg-amber-200"
                  : "text-text-secondary hover:text-text hover:bg-surface-tertiary"
              }
            `}
            title={voiceTitle}
            aria-label={pointyVoiceEnabled ? "Tắt Pointy voice" : "Bật Pointy voice"}
            aria-pressed={pointyVoiceEnabled}
            data-wiii-id="pointy-voice-toggle"
          >
            {pointyVoiceEnabled ? (
              <Volume2 size={13} strokeWidth={2.3} />
            ) : (
              <VolumeX size={13} strokeWidth={2} />
            )}
            <span
              aria-hidden="true"
              className={`h-1.5 w-1.5 rounded-full ${
                pointyVoiceEnabled
                  ? "bg-emerald-500"
                  : voiceStatusLoading
                    ? "animate-pulse bg-amber-400"
                    : voiceReady
                      ? "bg-emerald-400"
                      : "bg-stone-300"
              }`}
            />
            <span>{voiceStatusLoading ? "Voice..." : "Voice"}</span>
          </button>
        )}
      </div>

      {pointyMode && showVoiceSetup && (
        <div
          className="
            absolute bottom-full left-0 z-50 mb-2 w-[min(22rem,calc(100vw-2rem))]
            rounded-2xl border border-border bg-surface-primary/95 p-3 text-xs
            shadow-2xl backdrop-blur
          "
          data-wiii-id="pointy-voice-setup"
          role="dialog"
          aria-label="Cấu hình ElevenLabs cho Pointy voice"
        >
          <label
            htmlFor="pointy-elevenlabs-key"
            className="mb-1 block font-medium text-text"
          >
            ElevenLabs API key
          </label>
          <input
            id="pointy-elevenlabs-key"
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={apiKeyDraft}
            onChange={(event) => setApiKeyDraft(event.target.value)}
            placeholder="sk_..."
            className="
              w-full rounded-xl border border-border bg-surface-secondary px-3 py-2
              text-text outline-none transition focus:border-orange-400 focus:ring-2
              focus:ring-orange-400/20
            "
          />
          <p className="mt-2 text-[11px] leading-4 text-text-tertiary">
            Key chỉ gửi về backend và lưu server-side dạng mã hóa. UI không lưu raw key trong localStorage.
            {keyHint ? ` Key hiện tại: ${keyHint}.` : ""}
          </p>
          <div className="mt-3 flex items-center gap-2">
            <button
              type="button"
              onClick={onSaveVoiceConfig}
              disabled={savingVoiceConfig}
              className="
                rounded-full bg-orange-500 px-3 py-1.5 font-medium text-white
                transition hover:bg-orange-600 disabled:cursor-not-allowed
                disabled:opacity-60
              "
            >
              {savingVoiceConfig ? "Đang lưu..." : "Lưu key và bật Voice"}
            </button>
            <button
              type="button"
              onClick={() => {
                setShowVoiceSetup(false);
                setApiKeyDraft("");
              }}
              className="
                rounded-full px-3 py-1.5 text-text-secondary transition
                hover:bg-surface-tertiary hover:text-text
              "
            >
              Hủy
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
