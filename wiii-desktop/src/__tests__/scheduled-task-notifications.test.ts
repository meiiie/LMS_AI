import { describe, expect, it } from "vitest";
import {
  buildScheduledNotificationWebSocketUrl,
  parseAutonomousNotification,
  parseScheduledTaskNotification,
  proactiveNotificationToastMessage,
  scheduledTaskToastMessage,
} from "@/hooks/useScheduledTaskNotifications";

describe("scheduled task notifications", () => {
  it("builds an org-scoped WebSocket URL without leaking auth in the query", () => {
    const url = buildScheduledNotificationWebSocketUrl(
      "http://localhost:8000",
      "session 1",
      "org-1",
    );

    expect(url).toBe("ws://localhost:8000/api/v1/ws/session%201?org_id=org-1");
    expect(url).not.toContain("api_key");
    expect(url).not.toContain("token");
  });

  it("uses wss for HTTPS backends", () => {
    expect(
      buildScheduledNotificationWebSocketUrl(
        "https://wiii.example.test",
        "session-2",
      ),
    ).toBe("wss://wiii.example.test/api/v1/ws/session-2");
  });

  it("parses only scheduled_task WebSocket payloads", () => {
    const payload = parseScheduledTaskNotification(
      JSON.stringify({
        type: "scheduled_task",
        mode: "notification",
        content: "Review COLREG Rule 13",
      }),
    );

    expect(payload?.content).toBe("Review COLREG Rule 13");
    expect(parseScheduledTaskNotification(JSON.stringify({ type: "auth_ok" }))).toBeNull();
    expect(parseScheduledTaskNotification("not-json")).toBeNull();
  });

  it("parses proactive WebSocket payloads and legacy plain text", () => {
    const structured = parseAutonomousNotification(
      JSON.stringify({
        type: "proactive_message",
        trigger: "inactive_reengage",
        content: "Co lich hoc can quay lai.",
      }),
    );

    expect(structured?.type).toBe("proactive_message");
    expect(structured?.trigger).toBe("inactive_reengage");
    expect(structured?.content).toBe("Co lich hoc can quay lai.");
    expect(parseAutonomousNotification(JSON.stringify({ type: "auth_ok" }))).toBeNull();
    expect(parseAutonomousNotification("Tin nhan chu dong")).toEqual({
      type: "proactive_message",
      content: "Tin nhan chu dong",
      transport: "plain_text",
    });
  });

  it("formats Vietnamese-first toast copy for reminder and agent modes", () => {
    expect(
      scheduledTaskToastMessage({
        type: "scheduled_task",
        mode: "notification",
        content: "Review COLREG Rule 13",
      }),
    ).toBe("Nhắc việc: Review COLREG Rule 13");

    expect(
      scheduledTaskToastMessage({
        type: "scheduled_task",
        mode: "agent",
        content: "Scheduled MARPOL quiz ready",
      }),
    ).toBe("Task tự động: Scheduled MARPOL quiz ready");
  });

  it("formats Vietnamese-first proactive toast copy", () => {
    expect(
      proactiveNotificationToastMessage({
        type: "proactive_message",
        content: "Co lich hoc can quay lai.",
      }),
    ).toBe("Wiii ch\u1ee7 \u0111\u1ed9ng: Co lich hoc can quay lai.");
  });
});
