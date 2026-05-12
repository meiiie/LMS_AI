import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ModelSelector } from "@/components/chat/ModelSelector";
import { useModelStore } from "@/stores/model-store";
import { useSettingsStore } from "@/stores/settings-store";

const getMock = vi.fn();

vi.mock("@/api/client", () => ({
  getClient: () => ({
    get: getMock,
  }),
}));

describe("ModelSelector", () => {
  beforeEach(() => {
    getMock.mockResolvedValue({
      providers: [
        {
          id: "google",
          display_name: "Gemini",
          available: false,
          is_primary: true,
          is_fallback: false,
          state: "disabled",
          reason_code: "busy",
          reason_label: "Provider tam thoi ban hoac da cham gioi han.",
          selected_model: "gemini-3.1-flash-lite-preview",
          strict_pin: true,
          verified_at: "2026-03-23T00:00:00Z",
        },
        {
          id: "zhipu",
          display_name: "Zhipu GLM",
          available: true,
          is_primary: false,
          is_fallback: true,
          state: "selectable",
          reason_code: null,
          reason_label: null,
          selected_model: "glm-4.5-air",
          strict_pin: true,
          verified_at: "2026-03-23T00:00:00Z",
        },
        {
          id: "openai",
          display_name: "OpenAI",
          available: false,
          is_primary: false,
          is_fallback: false,
          state: "hidden",
          reason_code: null,
          reason_label: null,
          selected_model: "gpt-5-mini",
          strict_pin: true,
          verified_at: "2026-03-23T00:00:00Z",
        },
      ],
    });
    useSettingsStore.setState({
      settings: {
        server_url: "http://localhost:8000",
        api_key: "key",
        llm_provider: "google",
        user_id: "user",
        user_role: "student",
        display_name: "Minh",
        default_domain: "maritime",
        theme: "system",
        language: "vi",
        show_thinking: true,
        show_reasoning_trace: false,
        streaming_version: "v3",
        thinking_level: "balanced",
        model_provider: "auto",
      },
      isLoaded: true,
    });
    useModelStore.setState({
      activeProvider: "auto",
      providers: [],
      isLoading: false,
      lastFetchedAt: null,
    });
  });

  it("hides hidden providers and prevents selecting disabled ones", async () => {
    render(<ModelSelector />);

    await waitFor(() => {
      expect(useModelStore.getState().providers.length).toBe(3);
    });

    expect(screen.getByText("Tự động")).not.toBeNull();

    fireEvent.click(screen.getByTestId("model-selector-trigger"));

    expect(screen.getAllByText("Tự động").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText("OpenAI")).toBeNull();
    expect(screen.getByText("Provider tam thoi ban hoac da cham gioi han.")).not.toBeNull();

    fireEvent.click(screen.getByText("Gemini"));
    expect(useModelStore.getState().activeProvider).toBe("auto");

    fireEvent.click(screen.getByText("Zhipu GLM"));
    expect(useModelStore.getState().activeProvider).toBe("zhipu");
  });

  it("forces a fresh provider fetch whenever the dropdown opens", async () => {
    render(<ModelSelector />);

    await waitFor(() => {
      expect(getMock).toHaveBeenCalledTimes(1);
    });

    fireEvent.click(screen.getByTestId("model-selector-trigger"));

    await waitFor(() => {
      expect(getMock).toHaveBeenCalledTimes(2);
    });
  });
});
