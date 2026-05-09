import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ModelSwitchPromptCard } from "@/components/chat/ModelSwitchPromptCard";

const addToast = vi.fn();
const setActiveProvider = vi.fn();
const setNextTurnProvider = vi.fn();
const refreshIfStale = vi.fn();

vi.mock("@/stores/toast-store", () => ({
  useToastStore: () => ({ addToast }),
}));

vi.mock("@/stores/model-store", () => ({
  useModelStore: () => ({
    providers: [
      {
        id: "zhipu",
        displayName: "Zhipu GLM",
        available: true,
        isPrimary: false,
        isFallback: true,
        state: "selectable",
        strictPin: false,
        selectedModel: "glm-5",
      },
      {
        id: "openrouter",
        displayName: "OpenRouter",
        available: true,
        isPrimary: false,
        isFallback: true,
        state: "selectable",
        strictPin: false,
        selectedModel: "openai/gpt-5.4-mini",
      },
    ],
    activeProvider: "auto",
    setActiveProvider,
    setNextTurnProvider,
    refreshIfStale,
  }),
}));

describe("ModelSwitchPromptCard", () => {
  beforeEach(() => {
    addToast.mockReset();
    setActiveProvider.mockReset();
    setNextTurnProvider.mockReset();
    refreshIfStale.mockReset();
  });

  it("renders retry and session actions from explicit prompt metadata", () => {
    render(
      <ModelSwitchPromptCard
        metadata={{
          model_switch_prompt: {
            trigger: "provider_unavailable",
            title: "Đổi model để tiếp tục?",
            message: "Gemini dang cham gioi han.",
            recommended_provider: "zhipu",
            options: [
              {
                provider: "zhipu",
                label: "Zhipu GLM",
                selected_model: "glm-5",
              },
              {
                provider: "openrouter",
                label: "OpenRouter",
                selected_model: "openai/gpt-5.4-mini",
              },
            ],
            allow_retry_once: true,
            allow_session_switch: true,
          },
        }}
        onRetryOnce={vi.fn()}
      />,
    );

    expect(screen.getByText("Đổi model để tiếp tục?")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Thử lượt này bằng Zhipu GLM" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Dùng Zhipu GLM cho cả phiên" }),
    ).toBeTruthy();
  });

  it("uses one-shot override for retry-once action", () => {
    const onRetryOnce = vi.fn();
    render(
      <ModelSwitchPromptCard
        metadata={{
          model_switch_prompt: {
            trigger: "provider_unavailable",
            title: "Đổi model để tiếp tục?",
            message: "Gemini dang cham gioi han.",
            recommended_provider: "zhipu",
            options: [
              {
                provider: "zhipu",
                label: "Zhipu GLM",
                selected_model: "glm-5",
              },
            ],
            allow_retry_once: true,
            allow_session_switch: false,
          },
        }}
        onRetryOnce={onRetryOnce}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Thử lượt này bằng Zhipu GLM" }),
    );

    expect(setNextTurnProvider).toHaveBeenCalledWith("zhipu");
    expect(onRetryOnce).toHaveBeenCalledOnce();
  });

  it("lets user keep fallback provider for the whole session", () => {
    render(
      <ModelSwitchPromptCard
        metadata={{
          failover: {
            switched: true,
            switch_count: 1,
            initial_provider: "google",
            final_provider: "zhipu",
            last_reason_code: "auth_error",
            last_reason_category: "auth_error",
            route: [],
          },
        }}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Dùng Zhipu GLM cho cả phiên" }),
    );

    expect(setActiveProvider).toHaveBeenCalledWith("zhipu");
  });
});
