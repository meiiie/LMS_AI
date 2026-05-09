import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getVoiceStatus, updateVoiceConfig } from "@/api/voice";
import { PointyModeToggle } from "@/components/chat/PointyModeToggle";
import { useSettingsStore } from "@/stores/settings-store";
import { useToastStore } from "@/stores/toast-store";

vi.mock("@/api/voice", () => ({
  getVoiceStatus: vi.fn(),
  updateVoiceConfig: vi.fn(),
}));

const readyStatus = {
  enabled: true,
  configured: true,
  provider: "elevenlabs" as const,
  voice_id: "voice-id",
  model_id: "eleven_flash_v2_5",
  output_format: "mp3_22050_32",
  reason: null,
};

const savedConfigStatus = {
  ...readyStatus,
  persisted: true,
  updated_at: "2026-05-08T00:00:00+00:00",
  key_hint: "sk-t...7890",
};

const missingKeyStatus = {
  ...readyStatus,
  configured: false,
  reason: "elevenlabs_api_key_or_voice_id_missing",
};

describe("PointyModeToggle voice readiness", () => {
  beforeEach(async () => {
    useToastStore.setState({ toasts: [] });
    vi.mocked(getVoiceStatus).mockReset();
    vi.mocked(updateVoiceConfig).mockReset();
    await act(async () => {
      await useSettingsStore.getState().updateSettings({
        api_key: "local-dev-key",
        pointy_mode: true,
        pointy_voice_enabled: false,
      });
    });
  });

  it("keeps voice off and opens secure setup when ElevenLabs is not configured", async () => {
    vi.mocked(getVoiceStatus).mockResolvedValue(missingKeyStatus);

    render(<PointyModeToggle />);

    fireEvent.click(await screen.findByRole("button", { name: "Bật Pointy voice" }));

    await waitFor(() => {
      expect(useSettingsStore.getState().settings.pointy_voice_enabled).toBe(false);
      expect(useToastStore.getState().toasts.at(-1)?.message).toContain(
        "ElevenLabs key",
      );
    });
    expect(await screen.findByLabelText("ElevenLabs API key")).toBeTruthy();
  });

  it("enables voice only after backend reports a configured ElevenLabs proxy", async () => {
    vi.mocked(getVoiceStatus).mockResolvedValue(readyStatus);

    render(<PointyModeToggle />);

    fireEvent.click(await screen.findByRole("button", { name: "Bật Pointy voice" }));

    await waitFor(() => {
      expect(useSettingsStore.getState().settings.pointy_voice_enabled).toBe(true);
      expect(useToastStore.getState().toasts.at(-1)?.type).toBe("success");
    });
  });

  it("saves an ElevenLabs key server-side before enabling Pointy voice", async () => {
    vi.mocked(getVoiceStatus).mockResolvedValue(missingKeyStatus);
    vi.mocked(updateVoiceConfig).mockResolvedValue(savedConfigStatus);

    render(<PointyModeToggle />);

    fireEvent.click(await screen.findByRole("button", { name: "Bật Pointy voice" }));
    const keyInput = await screen.findByLabelText("ElevenLabs API key");
    fireEvent.change(keyInput, { target: { value: "unit-test-elevenlabs-key" } });
    fireEvent.click(screen.getByRole("button", { name: "Lưu key và bật Voice" }));

    await waitFor(() => {
      expect(updateVoiceConfig).toHaveBeenCalledWith({
        enabled: true,
        api_key: "unit-test-elevenlabs-key",
      });
      expect(useSettingsStore.getState().settings.pointy_voice_enabled).toBe(true);
      expect(useToastStore.getState().toasts.at(-1)?.type).toBe("success");
    });
    expect(screen.queryByLabelText("ElevenLabs API key")).toBeNull();
  });
});
