import { describe, expect, it } from "vitest";
import type { ContentBlock } from "@/api/types";
import {
  getVisibleStreamingBlocks,
  hasRenderableStreamingBlocks,
  shouldAutoFollowLatestMessage,
} from "@/components/chat/MessageList";

describe("MessageList streaming helpers", () => {
  it("keeps thinking blocks visible when the reasoning rail is enabled", () => {
    const blocks: ContentBlock[] = [
      { type: "thinking", id: "t1", content: "Mình đang nối mạch..." },
      { type: "action_text", id: "a1", content: "Calling tool_generate_visual" },
    ];

    const visible = getVisibleStreamingBlocks(blocks, true, "balanced");

    expect(visible.map((block) => block.type)).toEqual(["thinking", "action_text"]);
    expect(hasRenderableStreamingBlocks(visible)).toBe(true);
  });

  it("does not treat hidden technical trace blocks as renderable content", () => {
    const blocks: ContentBlock[] = [
      { type: "action_text", id: "a1", content: "tool_generate_visual" },
      {
        type: "tool_execution",
        id: "tool-1",
        status: "pending",
        tool: { id: "tool-1", name: "tool_generate_visual" },
      },
    ];

    const visible = getVisibleStreamingBlocks(blocks, true, "balanced");

    expect(visible.map((block) => block.type)).toEqual(["action_text", "tool_execution"]);
    expect(hasRenderableStreamingBlocks(visible)).toBe(true);
  });

  it("filters out empty thinking placeholders so the timer does not disappear too early", () => {
    const blocks: ContentBlock[] = [
      { type: "thinking", id: "t-empty", content: "", summary: "" },
      { type: "action_text", id: "a1", content: "tool_generate_visual" },
    ];

    const visible = getVisibleStreamingBlocks(blocks, true, "balanced");

    expect(visible.map((block) => block.type)).toEqual(["action_text"]);
    expect(hasRenderableStreamingBlocks(visible)).toBe(true);
  });

  it("resumes auto-follow when the latest message is from the user", () => {
    expect(shouldAutoFollowLatestMessage({ role: "user" })).toBe(true);
    expect(shouldAutoFollowLatestMessage({ role: "assistant" })).toBe(false);
    expect(shouldAutoFollowLatestMessage(null)).toBe(false);
  });
});
