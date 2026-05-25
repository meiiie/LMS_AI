import { describe, it, expect, beforeEach } from "vitest";
import {
  buildCodeStudioActiveSessionContext,
  resolveCodeStudioSessionIdForVisualSession,
  useCodeStudioStore,
} from "@/stores/code-studio-store";

function resetStore() {
  useCodeStudioStore.setState({
    activeSessionId: null,
    sessions: {},
  });
}

describe("code-studio-store", () => {
  beforeEach(() => {
    resetStore();
  });

  describe("openSession", () => {
    it("creates a new session and sets it active", () => {
      useCodeStudioStore.getState().openSession("vs_1", "Chart", "html", 1);
      const state = useCodeStudioStore.getState();
      expect(state.activeSessionId).toBe("vs_1");
      expect(state.sessions["vs_1"]).toBeDefined();
      expect(state.sessions["vs_1"].title).toBe("Chart");
      expect(state.sessions["vs_1"].status).toBe("streaming");
      expect(state.sessions["vs_1"].code).toBe("");
    });

    it("resets streaming state for existing complete session (new version)", () => {
      const store = useCodeStudioStore.getState();
      store.openSession("vs_1", "Chart", "html", 1);
      store.setRequestedView("vs_1", "code");
      store.completeSession("vs_1", "<div>v1</div>", "html", 1);
      expect(useCodeStudioStore.getState().sessions["vs_1"].status).toBe("complete");

      store.openSession("vs_1", "Chart v2", "html", 2);
      const session = useCodeStudioStore.getState().sessions["vs_1"];
      expect(session.status).toBe("streaming");
      expect(session.code).toBe("");
      expect(session.title).toBe("Chart v2");
      expect(session.activeVersion).toBe(2);
      expect(session.versions).toHaveLength(1);
      expect(session.versions[0].version).toBe(1);
      expect(session.metadata.requestedView).toBe("code");
    });

    it("reuses an active streaming session without wiping streamed code", () => {
      const store = useCodeStudioStore.getState();
      store.openSession("vs_1", "Chart", "html", 1);
      store.appendCode("vs_1", "<div>Hello", 0, 0);

      store.openSession("vs_1", "Chart", "html", 1);

      const session = useCodeStudioStore.getState().sessions["vs_1"];
      expect(session.status).toBe("streaming");
      expect(session.code).toBe("<div>Hello");
      expect(session.chunkCount).toBe(1);
    });
  });

  describe("appendCode", () => {
    it("accumulates code chunks", () => {
      const store = useCodeStudioStore.getState();
      store.openSession("vs_1", "T", "html", 1);
      store.appendCode("vs_1", "<div>", 0, 100);
      store.appendCode("vs_1", "Hello", 1, 100);
      store.appendCode("vs_1", "</div>", 2, 100);
      expect(useCodeStudioStore.getState().sessions["vs_1"].code).toBe("<div>Hello</div>");
      expect(useCodeStudioStore.getState().sessions["vs_1"].chunkCount).toBe(3);
    });

    it("ignores appends to non-streaming session", () => {
      const store = useCodeStudioStore.getState();
      store.openSession("vs_1", "T", "html", 1);
      store.completeSession("vs_1", "done", "html", 1);
      store.appendCode("vs_1", "extra", 0, 5);
      expect(useCodeStudioStore.getState().sessions["vs_1"].code).toBe("done");
    });

    it("ignores appends to unknown session", () => {
      const store = useCodeStudioStore.getState();
      store.appendCode("nonexistent", "chunk", 0, 10);
      expect(Object.keys(useCodeStudioStore.getState().sessions)).toHaveLength(0);
    });

    it("deduplicates repeated chunk indexes instead of appending twice", () => {
      const store = useCodeStudioStore.getState();
      store.openSession("vs_1", "T", "html", 1);
      store.appendCode("vs_1", "<div>", 0, 0);
      store.appendCode("vs_1", "Hello", 1, 0);
      store.appendCode("vs_1", "Hello", 1, 0);

      const session = useCodeStudioStore.getState().sessions["vs_1"];
      expect(session.code).toBe("<div>Hello");
      expect(session.chunkCount).toBe(2);
    });

    it("restarts streamed code cleanly when chunk index resets to zero after retry", () => {
      const store = useCodeStudioStore.getState();
      store.openSession("vs_1", "T", "html", 1);
      store.appendCode("vs_1", "<div>", 0, 0);
      store.appendCode("vs_1", "old", 1, 0);

      store.appendCode("vs_1", "<section>", 0, 0);
      store.appendCode("vs_1", "new", 1, 0);

      const session = useCodeStudioStore.getState().sessions["vs_1"];
      expect(session.code).toBe("<section>new");
      expect(session.chunkCount).toBe(2);
    });
  });

  describe("completeSession", () => {
    it("sets status to complete and adds version", () => {
      const store = useCodeStudioStore.getState();
      store.openSession("vs_1", "T", "html", 1);
      store.appendCode("vs_1", "partial", 0, 7);
      store.completeSession("vs_1", "<full/>", "html", 1, { id: "vp1" } as any);

      const session = useCodeStudioStore.getState().sessions["vs_1"];
      expect(session.status).toBe("complete");
      expect(session.code).toBe("<full/>");
      expect(session.versions).toHaveLength(1);
      expect(session.versions[0].version).toBe(1);
      expect(session.versions[0].code).toBe("<full/>");
      expect(session.visualPayload).toEqual({ id: "vp1" });
    });

    it("accumulates multiple versions", () => {
      const store = useCodeStudioStore.getState();
      store.openSession("vs_1", "T", "html", 1);
      store.completeSession("vs_1", "v1code", "html", 1);
      store.openSession("vs_1", "T", "html", 2);
      store.completeSession("vs_1", "v2code", "html", 2);

      const session = useCodeStudioStore.getState().sessions["vs_1"];
      expect(session.versions).toHaveLength(2);
      expect(session.activeVersion).toBe(2);
    });

  });

  describe("resolveCodeStudioSessionIdForVisualSession", () => {
    it("resolves both direct session ids and mapped visual session ids", () => {
      const store = useCodeStudioStore.getState();
      store.openSession("cs_mapped", "Mapped App", "html", 1);
      store.completeSession(
        "cs_mapped",
        "<main />",
        "html",
        1,
        undefined,
        "vs_mapped",
      );

      const { sessions } = useCodeStudioStore.getState();
      expect(
        resolveCodeStudioSessionIdForVisualSession(sessions, "cs_mapped"),
      ).toBe("cs_mapped");
      expect(
        resolveCodeStudioSessionIdForVisualSession(sessions, "vs_mapped"),
      ).toBe("cs_mapped");
      expect(
        resolveCodeStudioSessionIdForVisualSession(sessions, "missing"),
      ).toBeNull();
    });
  });

  describe("switchVersion", () => {
    it("switches code and visual payload to target version", () => {
      const store = useCodeStudioStore.getState();
      store.openSession("vs_1", "T", "html", 1);
      store.completeSession("vs_1", "v1", "html", 1, { id: "p1" } as any);
      store.openSession("vs_1", "T", "html", 2);
      store.completeSession("vs_1", "v2", "html", 2, { id: "p2" } as any);

      store.switchVersion("vs_1", 1);
      const session = useCodeStudioStore.getState().sessions["vs_1"];
      expect(session.activeVersion).toBe(1);
      expect(session.code).toBe("v1");
      expect(session.visualPayload).toEqual({ id: "p1" });
    });

    it("no-op for unknown version", () => {
      const store = useCodeStudioStore.getState();
      store.openSession("vs_1", "T", "html", 1);
      store.completeSession("vs_1", "v1", "html", 1);
      store.switchVersion("vs_1", 99);
      expect(useCodeStudioStore.getState().sessions["vs_1"].activeVersion).toBe(1);
    });
  });

  describe("setActiveSession", () => {
    it("sets active session ID", () => {
      useCodeStudioStore.getState().setActiveSession("vs_x");
      expect(useCodeStudioStore.getState().activeSessionId).toBe("vs_x");
    });

    it("can clear active session", () => {
      useCodeStudioStore.getState().setActiveSession("vs_x");
      useCodeStudioStore.getState().setActiveSession(null);
      expect(useCodeStudioStore.getState().activeSessionId).toBeNull();
    });
  });

  describe("setRequestedView", () => {
    it("stores the requested code/preview tab for the active session context", () => {
      const store = useCodeStudioStore.getState();
      store.openSession("vs_1", "Pendulum", "html", 1);
      store.setRequestedView("vs_1", "code");

      expect(useCodeStudioStore.getState().sessions["vs_1"].metadata.requestedView).toBe("code");
    });
  });

  describe("getActiveSessionContext", () => {
    it("builds a typed active-session context payload", () => {
      const store = useCodeStudioStore.getState();
      store.openSession("vs_typed", "Typed Preview", "html", 2, {
        studioLane: "app",
        artifactKind: "html_app",
        qualityProfile: "premium",
        rendererContract: "host_shell",
        requestedView: "preview",
      });
      store.completeSession(
        "vs_typed",
        "<main />",
        "html",
        2,
        { id: "vp-typed" } as any,
      );

      const session = useCodeStudioStore.getState().sessions["vs_typed"];
      expect(buildCodeStudioActiveSessionContext(session)).toEqual({
        active_session: {
          session_id: "vs_typed",
          title: "Typed Preview",
          status: "complete",
          active_version: 2,
          version_count: 1,
          language: "html",
          studio_lane: "app",
          artifact_kind: "html_app",
          quality_profile: "premium",
          renderer_contract: "host_shell",
          requested_view: "preview",
          has_preview: true,
        },
        requested_view: "preview",
      });
    });

    it("returns active session metadata for follow-up turns", () => {
      const store = useCodeStudioStore.getState();
      store.openSession("vs_1", "Pendulum", "html", 1, {
        studioLane: "app",
        artifactKind: "html_app",
        qualityProfile: "premium",
        rendererContract: "host_shell",
      });
      store.setRequestedView("vs_1", "code");
      store.appendCode("vs_1", "<div>demo</div>", 0, 32);
      store.completeSession("vs_1", "<div>demo</div>", "html", 1, { id: "vp-1" } as any);

      const context = store.getActiveSessionContext();
      expect(context).toEqual({
        active_session: {
          session_id: "vs_1",
          title: "Pendulum",
          status: "complete",
          active_version: 1,
          version_count: 1,
          language: "html",
          studio_lane: "app",
          artifact_kind: "html_app",
          quality_profile: "premium",
          renderer_contract: "host_shell",
          requested_view: "code",
          has_preview: true,
        },
        requested_view: "code",
      });
    });

    it("returns undefined when there is no active session", () => {
      expect(useCodeStudioStore.getState().getActiveSessionContext()).toBeUndefined();
    });
  });

  describe("clearSessions", () => {
    it("clears all sessions and active ID", () => {
      const store = useCodeStudioStore.getState();
      store.openSession("vs_1", "A", "html", 1);
      store.openSession("vs_2", "B", "html", 1);
      store.clearSessions();
      const state = useCodeStudioStore.getState();
      expect(state.activeSessionId).toBeNull();
      expect(Object.keys(state.sessions)).toHaveLength(0);
    });
  });
});
