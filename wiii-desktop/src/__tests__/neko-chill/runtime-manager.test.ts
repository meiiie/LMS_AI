import { describe, expect, it } from "vitest";
import type { Driver, PermissionDecision } from "@/neko-chill/drivers/types";
import {
  RuntimeCapabilityError,
  RuntimeRegistry,
  RuntimeScope,
} from "@/neko-chill/runtime-manager";

class FakeDriver implements Driver {
  readonly kind = "acp" as const;
  readonly runtime: Driver["runtime"];
  disposed = 0;

  constructor(
    readonly sessionId: string,
    capabilities: Driver["runtime"]["capabilities"] = [
      "prompt",
      "cancel",
      "permission-resolution",
      "session-config",
    ],
  ) {
    this.runtime = {
      capabilities,
      contextContinuity: "process",
      workspaceIsolation: "advisory",
    };
  }

  async start(): Promise<void> {}
  async prompt(): Promise<void> {}
  async cancel(): Promise<void> {}
  async resolvePermission(_: PermissionDecision): Promise<void> {}
  async setConfigOption(): Promise<void> {}
  async dispose(): Promise<void> {
    this.disposed += 1;
  }
}

describe("RuntimeScope", () => {
  it("disposes owned resources once in reverse order", async () => {
    const calls: string[] = [];
    const scope = new RuntimeScope();
    scope.add(() => calls.push("transport"));
    scope.add(async () => { calls.push("driver"); });

    await Promise.all([scope.dispose(), scope.dispose()]);
    expect(calls).toEqual(["driver", "transport"]);
  });

  it("continues disposing siblings after one disposer fails", async () => {
    const calls: string[] = [];
    const scope = new RuntimeScope();
    scope.add(() => calls.push("transport"));
    scope.add(() => {
      calls.push("driver");
      throw new Error("driver cleanup failed");
    });

    await expect(scope.dispose()).rejects.toThrow("driver cleanup failed");
    expect(calls).toEqual(["driver", "transport"]);
  });
});

describe("RuntimeRegistry", () => {
  it("keeps the old provider when replacement preparation fails", async () => {
    const registry = new RuntimeRegistry();
    const first = new FakeDriver("s1");
    const attached = await registry.replace("s1", "neko", async () => first);

    await expect(
      registry.replace("s1", "gemini", async () => {
        throw new Error("initialize failed");
      }),
    ).rejects.toThrow("initialize failed");

    expect(registry.get("s1")?.instanceId).toBe(attached.current.instanceId);
    expect(registry.require("s1", "prompt")).toBe(first);
    expect(first.disposed).toBe(0);
  });

  it("changes provider identity atomically and disposes each driver once", async () => {
    const registry = new RuntimeRegistry();
    const first = new FakeDriver("s1");
    const second = new FakeDriver("s1");
    const one = await registry.replace("s1", "neko", async () => first);
    const two = await registry.replace("s1", "neko", async () => second);

    expect(two.current.instanceId).not.toBe(one.current.instanceId);
    expect(two.previous?.instanceId).toBe(one.current.instanceId);
    expect(registry.require("s1", "prompt")).toBe(second);
    expect(first.disposed).toBe(1);

    await registry.detach("s1");
    await registry.detach("s1");
    expect(second.disposed).toBe(1);
  });

  it("fails closed when a consumer requests an undeclared capability", async () => {
    const registry = new RuntimeRegistry();
    await registry.replace("s1", "read-only", async () => new FakeDriver("s1", ["prompt"]));

    expect(() => registry.require("s1", "session-config")).toThrow(RuntimeCapabilityError);
  });

  it("disposes an in-flight provider if mode teardown wins the race", async () => {
    const registry = new RuntimeRegistry();
    const driver = new FakeDriver("s1");
    let finishCreate!: (driver: Driver) => void;
    const creating = registry.replace(
      "s1",
      "neko",
      async () => new Promise<Driver>((resolve) => { finishCreate = resolve; }),
    );

    await registry.disposeAll();
    finishCreate(driver);

    await expect(creating).rejects.toThrow("cancelled during teardown");
    expect(driver.disposed).toBe(1);
    expect(registry.get("s1")).toBeNull();
  });

  it("disposes an in-flight provider if that session closes first", async () => {
    const registry = new RuntimeRegistry();
    const driver = new FakeDriver("s1");
    let finishCreate!: (driver: Driver) => void;
    const creating = registry.replace(
      "s1",
      "neko",
      async () => new Promise<Driver>((resolve) => { finishCreate = resolve; }),
    );

    await registry.detach("s1");
    finishCreate(driver);

    await expect(creating).rejects.toThrow("cancelled during teardown");
    expect(driver.disposed).toBe(1);
    expect(registry.get("s1")).toBeNull();
  });
});
