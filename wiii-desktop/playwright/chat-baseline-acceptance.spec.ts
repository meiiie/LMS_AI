import { expect, test, type Page } from "@playwright/test";
import {
  assistantMessages,
  bootstrapLocalChat,
  expectNoBaselineToolSurfaces,
  expectNoRawChatBaselinePayload,
  installChatBaselineStreamMock,
  lastAssistantMessage,
  readPersistedAssistantMessages,
  sendPrompt,
  waitForObservedChatBaselineStream,
  waitForGenerationToSettle,
  type ChatBaselineScenario,
  type ChatBaselineTurnCapture,
  type ObservedChatBaselineStream,
} from "./support/local-chat-harness";

const CHAT_BASELINE_SCENARIOS: ChatBaselineScenario[] = [
  {
    id: "vietnamese-greeting",
    prompt: "xin chào Wiii, hôm nay bạn thế nào?",
    answerChunks: [
      "Chào bạn, mình vẫn ở đây ",
      "và sẵn sàng cùng bạn làm tiếp.",
    ],
    expectedText: "Chào bạn, mình vẫn ở đây",
    expectedTurnPath: "casual_chat",
  },
  {
    id: "daily-status-no-search",
    prompt: "hôm nay mình ăn cơm rồi",
    answerChunks: [
      "Vậy ổn rồi. Mình sẽ giữ nhịp trò chuyện nhẹ nhàng ",
      "và không kéo câu này sang tìm kiếm hay công cụ.",
    ],
    expectedText: "không kéo câu này sang tìm kiếm hay công cụ",
    expectedTurnPath: "casual_chat",
  },
  {
    id: "simple-factual-chat",
    prompt: "giải thích ngắn gọn sự khác nhau giữa API và SDK",
    answerChunks: [
      "API là giao diện để phần mềm gọi nhau; ",
      "SDK là bộ công cụ giúp lập trình viên dùng API đó dễ hơn.",
    ],
    expectedText: "API là giao diện để phần mềm gọi nhau",
    expectedTurnPath: "casual_chat",
  },
  {
    id: "inline-code-explanation",
    prompt: "cho mình ví dụ nhỏ về Promise trong JavaScript",
    answerChunks: [
      "Ví dụ nhỏ:\n\n```javascript\n",
      "Promise.resolve('x').then(console.log);\n",
      "```\n\nPromise giữ kết quả bất đồng bộ và gọi `.then` khi hoàn tất.",
    ],
    expectedText: "Promise.resolve",
    expectedTurnPath: "casual_chat",
    expectCodeBlock: true,
  },
];

const DISALLOWED_BASELINE_EVENTS = [
  "host_action",
  "pointy_action",
  "visual",
  "visual_open",
  "visual_patch",
  "visual_commit",
  "code_open",
  "code_delta",
  "code_complete",
  "tool_call",
  "tool_result",
];

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? value as Record<string, unknown> : {};
}

function nestedRecord(
  value: Record<string, unknown> | undefined,
  key: string,
): Record<string, unknown> {
  return asRecord(value?.[key]);
}

function eventTypes(stream: ObservedChatBaselineStream): string[] {
  return stream.events.map((event) => event.type);
}

function expectSafeRequestShape(capture: ChatBaselineTurnCapture, scenario: ChatBaselineScenario) {
  expect(capture.request.message).toBe(scenario.prompt);
  expect(capture.request.pointy_mode).toBe(false);
  expect(capture.request.force_skills).toBeUndefined();
  expect(capture.request.images).toBeUndefined();

  const userContext = asRecord(capture.request.user_context);
  expect(userContext.document_context).toBeUndefined();
  expect(userContext.host_action_feedback).toBeUndefined();
  expect(userContext.visual_context).toBeUndefined();
  expect(userContext.code_studio_context).toBeUndefined();
}

function expectSafeLedger(
  ledger: Record<string, unknown> | undefined,
  scenario: ChatBaselineScenario,
) {
  expect(ledger).toBeTruthy();

  const request = nestedRecord(ledger, "request");
  expect(request.host_surface).toBe("desktop_chat");
  expect(request.host_capabilities).toEqual([]);

  const context = nestedRecord(ledger, "context");
  expect(context.document_context_present).toBe(false);
  expect(context.uploaded_document_count).toBe(0);
  expect(context.source_ref_count).toBe(0);

  const route = nestedRecord(ledger, "route");
  expect(route.lane).toBe("native_turn");
  const turnPathDecision = nestedRecord(route, "turn_path_decision");
  expect(turnPathDecision.path).toBe(scenario.expectedTurnPath);
  expect(turnPathDecision.bind_tools).toBe(false);
  expect(turnPathDecision.force_tools).toBe(false);

  const tools = nestedRecord(ledger, "tools");
  expect(tools.observed).toEqual([]);
  expect(tools.suppressed).toEqual(expect.arrayContaining([
    "host_action",
    "pointy_action",
    "visual_runtime",
    "code_studio",
  ]));

  const hostActions = nestedRecord(ledger, "host_actions");
  expect(hostActions.preview_required).toBe(false);
  expect(hostActions.preview_emitted).toBe(false);
  expect(hostActions.approval_token_present).toBe(false);
  expect(hostActions.apply_attempted).toBe(false);
}

function expectTerminalLedger(
  ledger: Record<string, unknown> | undefined,
  scenario: ChatBaselineScenario,
) {
  expectSafeLedger(ledger, scenario);
  const stream = nestedRecord(ledger, "stream");
  expect(stream.metadata_seen).toBe(true);
  expect(stream.done_seen).toBe(true);
  expect(stream.event_sequence_tail).toEqual(expect.arrayContaining(["metadata", "done"]));

  const finalization = nestedRecord(ledger, "finalization");
  expect(finalization.status).toBe("saved");
  expect(finalization.save_response_immediately).toBe(false);
}

function terminalLedgerFrom(stream: ObservedChatBaselineStream): Record<string, unknown> | undefined {
  const ledger = stream.events.find((event) => event.type === "done")?.data?.runtime_flow_ledger;
  return ledger && typeof ledger === "object" ? ledger as Record<string, unknown> : undefined;
}

function chatLifecycleEventsFromStream(
  stream: ObservedChatBaselineStream,
): Record<string, unknown>[] {
  return stream.events
    .filter((event) => event.type === "chat_lifecycle")
    .map((event) => asRecord(event.data));
}

function chatLifecycleEventsFromMetadata(
  metadata: Record<string, unknown> | undefined,
): Record<string, unknown>[] {
  const lifecycle = metadata?.chat_lifecycle;
  expect(Array.isArray(lifecycle)).toBe(true);
  return (lifecycle as unknown[]).map((event) => asRecord(event));
}

function expectOptionalArrayValue(
  record: Record<string, unknown>,
  key: string,
): unknown[] {
  const value = record[key];
  if (typeof value === "undefined") return [];
  expect(Array.isArray(value)).toBe(true);
  return value as unknown[];
}

function expectChatLifecycleTelemetry(
  events: Record<string, unknown>[],
  scenario: ChatBaselineScenario,
) {
  expect(events.map((event) => event.event_name)).toEqual([
    "path.selected",
    "capability.checked",
    "finalization.completed",
    "chat.done",
  ]);

  const pathSelected = events[0];
  expect(pathSelected.schema_version).toBe("wiii.chat_runtime_lifecycle.v1");
  expect(pathSelected.phase).toBe("routing");
  expect(pathSelected.status).toBe("selected");
  expect(pathSelected.lane).toBe("native_turn");

  const capabilities = nestedRecord(pathSelected, "capabilities");
  expect(capabilities.host_surface).toBe("desktop_chat");
  expect(expectOptionalArrayValue(capabilities, "observed_tools")).toEqual([]);
  expect(expectOptionalArrayValue(capabilities, "suppressed_tools")).toEqual(
    expect.arrayContaining([
      "host_action",
      "pointy_action",
      "visual_runtime",
      "code_studio",
    ]),
  );
  expect(capabilities.preview_required).toBe(false);
  expect(capabilities.preview_emitted).toBe(false);
  expect(capabilities.approval_token_present).toBe(false);
  expect(capabilities.apply_attempted).toBe(false);

  const metadata = nestedRecord(pathSelected, "metadata");
  expect(metadata.model).toBe("browser-chat-baseline-mock");
  expect(metadata.turn_path).toBe(scenario.expectedTurnPath);
  expect(metadata.runtime_authoritative).toBe(true);

  const capabilityChecked = events[1];
  expect(capabilityChecked.phase).toBe("capability");
  expect(capabilityChecked.status).toBe("allowed");
  const finalization = events[2];
  expect(finalization.phase).toBe("finalization");
  expect(finalization.status).toBe("completed");
  const terminal = events[3];
  expect(terminal.phase).toBe("terminal");
  expect(terminal.status).toBe("completed");

  const serialized = JSON.stringify(events);
  expect(serialized).not.toContain("raw_payload");
  expect(serialized).not.toContain('"function_call"');
}

async function latestPersistedAssistant(
  page: Page,
  userId: string,
  minimumCount: number,
) {
  await expect
    .poll(
      async () => (await readPersistedAssistantMessages(page, userId)).length,
      { timeout: 30_000, intervals: [250, 500, 1_000] },
    )
    .toBeGreaterThanOrEqual(minimumCount);

  const messages = await readPersistedAssistantMessages(page, userId);
  return messages[messages.length - 1];
}

test.describe("browser chat-baseline acceptance", () => {
  test("sends ordinary Vietnamese prompts through the UI and keeps the no-tool chat lane", async ({ page }) => {
    const streamMock = await installChatBaselineStreamMock(page, CHAT_BASELINE_SCENARIOS);
    const bootstrap = await bootstrapLocalChat(page, {
      userId: `browser-chat-baseline-${Date.now()}`,
      displayName: "Browser Chat Baseline",
    });

    expect(bootstrap.authenticatedBy).toBe("dev-login-api");
    await expect(assistantMessages(page)).toHaveCount(0);

    for (let index = 0; index < CHAT_BASELINE_SCENARIOS.length; index += 1) {
      const scenario = CHAT_BASELINE_SCENARIOS[index];
      const previousCaptureCount = streamMock.captures.length;

      await sendPrompt(page, scenario.prompt);
      await expect
        .poll(() => streamMock.captures.length, {
          timeout: 30_000,
          intervals: [250, 500, 1_000],
        })
        .toBe(previousCaptureCount + 1);
      await waitForGenerationToSettle(page);

      const capture = streamMock.captures[streamMock.captures.length - 1];
      expect(capture.scenarioId).toBe(scenario.id);
      expectSafeRequestShape(capture, scenario);

      const observedStream = await waitForObservedChatBaselineStream(page, index);
      expect(observedStream.status).toBe(200);

      const observedEvents = eventTypes(observedStream);
      expect(observedEvents).toEqual(expect.arrayContaining([
        "chat_lifecycle",
        "status",
        "answer",
        "metadata",
        "done",
      ]));
      expect(observedEvents.filter((eventType) => eventType === "chat_lifecycle")).toHaveLength(4);
      expect(observedEvents.indexOf("chat_lifecycle")).toBeLessThan(observedEvents.indexOf("answer"));
      expect(observedEvents[observedEvents.length - 1]).toBe("done");
      for (const eventType of DISALLOWED_BASELINE_EVENTS) {
        expect(observedEvents).not.toContain(eventType);
      }
      expectChatLifecycleTelemetry(chatLifecycleEventsFromStream(observedStream), scenario);

      const assistant = lastAssistantMessage(page);
      await expect(assistant).toContainText(scenario.expectedText, { timeout: 30_000 });
      if (scenario.expectCodeBlock) {
        await expect(assistant.locator("pre code").first()).toContainText("Promise.resolve", {
          timeout: 30_000,
        });
      }

      const visibleText = await assistant.innerText();
      expectNoRawChatBaselinePayload(visibleText);
      await expectNoBaselineToolSurfaces(page);

      const terminalLedger = terminalLedgerFrom(observedStream);
      expectTerminalLedger(terminalLedger, scenario);

      const persisted = await latestPersistedAssistant(page, bootstrap.userId, index + 1);
      expect(persisted.content).toContain(scenario.expectedText);
      expectNoRawChatBaselinePayload(persisted.content || "");
      const persistedTurnPath = asRecord(persisted.metadata?.turn_path_decision);
      expect(persistedTurnPath.path).toBe(scenario.expectedTurnPath);
      expect(persistedTurnPath.bind_tools).toBe(false);
      expect(persistedTurnPath.force_tools).toBe(false);
      expectSafeLedger(asRecord(persisted.metadata?.runtime_flow_ledger), scenario);
      expectChatLifecycleTelemetry(
        chatLifecycleEventsFromMetadata(persisted.metadata),
        scenario,
      );
    }
  });
});
