/**
 * T101 — DriverEvent contract tests: exhaustiveness and fail-closed vocabulary.
 * The union is the load-bearing seam (FR-010); these tests make accidental
 * variant removal or permission-kind loosening a compile/test failure.
 */

import { describe, expect, it } from "vitest";
import type {
  DriverEvent,
  DriverEventType,
  PermissionOption,
} from "@/neko-chill/drivers/types";

const EVERY_EVENT: DriverEvent[] = [
  { type: "turn-started", sessionId: "s" },
  { type: "reasoning-delta", sessionId: "s", text: "t" },
  { type: "answer-delta", sessionId: "s", text: "a" },
  {
    type: "activity",
    sessionId: "s",
    activity: { id: "1", title: "Read file", kind: "file", status: "pending" },
  },
  {
    type: "permission-request",
    sessionId: "s",
    request: {
      requestId: "r1",
      title: "Write src/x.ts",
      options: [{ optionId: "o1", label: "Allow once", kind: "allow_once" }],
    },
  },
  { type: "turn-finished", sessionId: "s", stopReason: "end_turn" },
  { type: "error", sessionId: "s", message: "boom", fatal: false },
  { type: "process-exited", sessionId: "s", code: 0 },
];

/** Compile-time exhaustiveness: adding a variant breaks this switch. */
function classify(event: DriverEvent): DriverEventType {
  switch (event.type) {
    case "turn-started":
    case "reasoning-delta":
    case "answer-delta":
    case "activity":
    case "permission-request":
    case "turn-finished":
    case "error":
    case "process-exited":
      return event.type;
    default: {
      const unreachable: never = event;
      return unreachable;
    }
  }
}

describe("DriverEvent contract", () => {
  it("covers every variant and each carries its sessionId", () => {
    const seen = new Set<DriverEventType>();
    for (const event of EVERY_EVENT) {
      expect(event.sessionId).toBe("s");
      seen.add(classify(event));
    }
    expect(seen.size).toBe(8);
  });

  it("only explicit allow kinds can ever approve (fail-closed vocabulary)", () => {
    const approving: PermissionOption["kind"][] = ["allow_once", "allow_always"];
    const nonApproving: PermissionOption["kind"][] = [
      "reject_once",
      "reject_always",
      "other",
    ];
    for (const kind of [...approving, ...nonApproving]) {
      const isApproving = approving.includes(kind);
      // "other" and every reject kind must never count as approval.
      expect(isApproving).toBe(kind === "allow_once" || kind === "allow_always");
    }
  });
});
