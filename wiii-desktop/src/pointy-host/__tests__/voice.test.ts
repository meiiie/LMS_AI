import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { synthesizePointySpeech } from "@/api/voice";
import { useSettingsStore } from "@/stores/settings-store";
import { ensurePointyVoiceBridge, stopPointyVoice } from "../voice";

vi.mock("@/api/voice", () => ({
  synthesizePointySpeech: vi.fn(),
}));

describe("Pointy voice bridge", () => {
  type MockAudioInstance = {
    pause: ReturnType<typeof vi.fn>;
    play: ReturnType<typeof vi.fn>;
    src: string;
    preload: string;
    volume: number;
    onended: (() => void) | null;
  };

  const audioInstances: MockAudioInstance[] = [];
  let originalCreateObjectURL: PropertyDescriptor | undefined;
  let originalRevokeObjectURL: PropertyDescriptor | undefined;

  beforeEach(async () => {
    vi.clearAllMocks();
    audioInstances.length = 0;
    await useSettingsStore.getState().updateSettings({
      pointy_mode: true,
      pointy_voice_enabled: true,
    });

    originalCreateObjectURL = Object.getOwnPropertyDescriptor(URL, "createObjectURL");
    originalRevokeObjectURL = Object.getOwnPropertyDescriptor(URL, "revokeObjectURL");
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:wiii-pointy-voice"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });

    class MockAudio implements MockAudioInstance {
      pause = vi.fn();
      play = vi.fn().mockResolvedValue(undefined);
      src: string;
      preload = "";
      volume = 1;
      onended: (() => void) | null = null;

      constructor(src: string) {
        this.src = src;
        audioInstances.push(this);
      }
    }

    vi.stubGlobal("Audio", MockAudio);
  });

  afterEach(async () => {
    stopPointyVoice();
    vi.unstubAllGlobals();
    if (originalCreateObjectURL) {
      Object.defineProperty(URL, "createObjectURL", originalCreateObjectURL);
    } else {
      Reflect.deleteProperty(URL, "createObjectURL");
    }
    if (originalRevokeObjectURL) {
      Object.defineProperty(URL, "revokeObjectURL", originalRevokeObjectURL);
    } else {
      Reflect.deleteProperty(URL, "revokeObjectURL");
    }
    await useSettingsStore.getState().updateSettings({
      pointy_mode: false,
      pointy_voice_enabled: false,
    });
  });

  it("synthesizes a caption and starts browser audio playback", async () => {
    vi.mocked(synthesizePointySpeech).mockResolvedValue(
      new Blob([new Uint8Array([1, 2, 3, 4])], { type: "audio/mpeg" }),
    );

    ensurePointyVoiceBridge();
    window.dispatchEvent(
      new CustomEvent("wiii:pointy:target", {
        detail: {
          selector: "#send-message",
          caption: "Đây là nút gửi tin nhắn.",
        },
      }),
    );

    await vi.waitFor(() => {
      expect(synthesizePointySpeech).toHaveBeenCalledWith("Đây là nút gửi tin nhắn.");
      expect(audioInstances).toHaveLength(1);
      expect(audioInstances[0].play).toHaveBeenCalledTimes(1);
    });
    expect(audioInstances[0].src).toBe("blob:wiii-pointy-voice");
    expect(audioInstances[0].preload).toBe("auto");
    expect(audioInstances[0].volume).toBe(0.92);
  });

  it("skips playback when Pointy voice is disabled", async () => {
    await useSettingsStore.getState().updateSettings({
      pointy_mode: true,
      pointy_voice_enabled: false,
    });

    ensurePointyVoiceBridge();
    window.dispatchEvent(
      new CustomEvent("wiii:pointy:target", {
        detail: {
          selector: "#send-message",
          caption: "Đây là nút gửi tin nhắn.",
        },
      }),
    );

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(synthesizePointySpeech).not.toHaveBeenCalled();
    expect(audioInstances).toHaveLength(0);
  });
});
