/**
 * Tests for CursorIdentity — pin down the contracts that other cursors
 * (Soul Bridge peers, demo page, future multi-user) will rely on.
 */

import { describe, it, expect } from "vitest";
import {
  WIII_IDENTITY,
  CURSOR_PALETTE,
  colorForSessionId,
  identityFor,
} from "../identity";

describe("Wiii identity", () => {
  it("is the AI canonical identity with reserved orange", () => {
    expect(WIII_IDENTITY.id).toBe("wiii");
    expect(WIII_IDENTITY.color).toBe("#F97316");
    expect(WIII_IDENTITY.role).toBe("ai");
    expect(WIII_IDENTITY.avatar).toBe("W");
  });

  it("Wiii orange is reserved at palette index 0", () => {
    expect(CURSOR_PALETTE[0]).toBe(WIII_IDENTITY.color);
  });
});

describe("colorForSessionId", () => {
  it("returns Wiii orange for the Wiii session id", () => {
    expect(colorForSessionId("wiii")).toBe(WIII_IDENTITY.color);
  });

  it("never returns Wiii orange for other session ids", () => {
    // Try many distinct ids — none should collide on the reserved colour.
    const ids = [
      "subsoul-bro", "alex", "user-42", "peer-uuid-abc",
      "tester", "guest-1", "x", "0", "session-foo",
      "session-bar", "session-baz", "session-qux",
    ];
    for (const id of ids) {
      expect(colorForSessionId(id)).not.toBe(WIII_IDENTITY.color);
    }
  });

  it("is stable across calls — same id, same colour", () => {
    const a = colorForSessionId("subsoul-bro");
    const b = colorForSessionId("subsoul-bro");
    const c = colorForSessionId("subsoul-bro");
    expect(a).toBe(b);
    expect(b).toBe(c);
  });

  it("returns a valid palette colour", () => {
    const colour = colorForSessionId("any-id-here");
    expect(CURSOR_PALETTE).toContain(colour);
  });
});

describe("identityFor", () => {
  it("returns the canonical Wiii identity for the wiii id", () => {
    const ident = identityFor("wiii", "Wiii");
    expect(ident).toBe(WIII_IDENTITY); // exact reference
  });

  it("derives an avatar from the name's first grapheme", () => {
    const ident = identityFor("peer-1", "Bro");
    expect(ident.avatar).toBe("B");
  });

  it("uppercases the avatar character", () => {
    const ident = identityFor("peer-2", "alex");
    expect(ident.avatar).toBe("A");
  });

  it("falls back to ? when the name is empty", () => {
    const ident = identityFor("peer-3", "");
    expect(ident.avatar).toBe("?");
  });

  it("respects an explicit avatar override", () => {
    const ident = identityFor("peer-4", "Bro", { avatar: "🤖" });
    expect(ident.avatar).toBe("🤖");
  });

  it("defaults non-Wiii peers to ai-peer role", () => {
    const ident = identityFor("peer-5", "Other");
    expect(ident.role).toBe("ai-peer");
  });

  it("respects an explicit role override", () => {
    const ident = identityFor("peer-6", "Alex", { role: "user" });
    expect(ident.role).toBe("user");
  });

  it("assigns a stable colour from the palette", () => {
    const a = identityFor("peer-7", "Sam");
    const b = identityFor("peer-7", "Sam");
    expect(a.color).toBe(b.color);
    expect(CURSOR_PALETTE).toContain(a.color);
    expect(a.color).not.toBe(WIII_IDENTITY.color);
  });
});
