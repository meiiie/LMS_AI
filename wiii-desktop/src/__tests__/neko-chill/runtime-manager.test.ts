import { describe, expect, it, vi } from "vitest";
import type { Driver, PermissionDecision } from "@/neko-chill/drivers/types";
import {
  RuntimeCapabilityError,
  RuntimeProviderChangedError,
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

class BlockingDisposeDriver extends FakeDriver {
  constructor(sessionId: string, private readonly gate: Promise<void>) {
    super(sessionId);
  }

  override async dispose(): Promise<void> {
    this.disposed += 1;
    await this.gate;
  }
}

class BlockingFailingDisposeDriver extends FakeDriver {
  constructor(sessionId: string, private readonly gate: Promise<void>) {
    super(sessionId);
  }

  override async dispose(): Promise<void> {
    this.disposed += 1;
    await this.gate;
    throw new Error("process kill failed");
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
  it("captures the provider contract observed when a known runtime attaches", async () => {
    const registry = new RuntimeRegistry();
    const driver = new FakeDriver("s1");
    Object.assign(driver.runtime, {
      observedProviderCapabilities: {
        resume: true,
        modelSelection: true,
        approvals: true,
      },
    });

    const attached = await registry.replace(
      "s1",
      "neko",
      async () => driver,
      { providerVersion: "0.24.17" },
    );

    expect(attached.current.providerCapabilities).toEqual(expect.objectContaining({
      v: 1,
      providerId: "neko",
      providerVersion: "0.24.17",
      integration: "acp",
      protocol: "acp-v1",
      capabilities: expect.objectContaining({
        resume: true,
        modelSelection: true,
        approvals: true,
        fork: false,
      }),
    }));
  });

  it("does not invent a capability contract for an unknown legacy provider", async () => {
    const registry = new RuntimeRegistry();
    const attached = await registry.replace("s1", "legacy-provider", async () => new FakeDriver("s1"));

    expect(attached.current.providerCapabilities).toBeUndefined();
  });

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
    expect(registry.requireInstance("s1", attached.current.instanceId, "prompt")).toBe(first);
    expect(first.disposed).toBe(0);
  });

  it("retains failed cleanup ownership after an owned preparation fails", async () => {
    const registry = new RuntimeRegistry();
    const failedDriver = new BlockingFailingDisposeDriver("s1", Promise.resolve());

    await expect(registry.replace("s1", "neko", async (_instanceId, own) => {
      own(failedDriver);
      throw new Error("initialize failed");
    })).rejects.toBeInstanceOf(AggregateError);

    expect(failedDriver.disposed).toBe(1);
    expect(registry.ownedSessionIds()).toEqual(["s1"]);
    let replacementAttempted = false;
    await expect(registry.replace("s1", "neko", async () => {
      replacementAttempted = true;
      return new FakeDriver("s1");
    })).rejects.toThrow("process kill failed");
    expect(replacementAttempted).toBe(false);
    await expect(registry.detach("s1")).rejects.toThrow("process kill failed");
  });

  it("changes provider identity atomically and disposes each driver once", async () => {
    const registry = new RuntimeRegistry();
    const first = new FakeDriver("s1");
    const second = new FakeDriver("s1");
    const one = await registry.replace("s1", "neko", async () => first);
    const two = await registry.replace("s1", "neko", async () => second);

    expect(two.current.instanceId).not.toBe(one.current.instanceId);
    expect(two.previous?.instanceId).toBe(one.current.instanceId);
    expect(registry.requireInstance("s1", two.current.instanceId, "prompt")).toBe(second);
    expect(first.disposed).toBe(1);

    await registry.detach("s1");
    await registry.detach("s1");
    expect(second.disposed).toBe(1);
  });

  it("joins an in-flight disposal when detach is called again", async () => {
    const registry = new RuntimeRegistry();
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    const driver = new BlockingDisposeDriver("s1", gate);
    await registry.replace("s1", "neko", async () => driver);

    const first = registry.detach("s1");
    await vi.waitFor(() => expect(driver.disposed).toBe(1));
    let secondSettled = false;
    const second = registry.detach("s1").finally(() => {
      secondSettled = true;
    });
    await Promise.resolve();

    expect(secondSettled).toBe(false);
    release();
    await Promise.all([first, second]);
    expect(driver.disposed).toBe(1);
  });

  it("reports a joined cleanup failure after the binding was already revoked", async () => {
    const registry = new RuntimeRegistry();
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    const driver = new BlockingFailingDisposeDriver("s1", gate);
    await registry.replace("s1", "neko", async () => driver);

    const firstOutcome = registry.detach("s1").then(
      () => null,
      (error) => error,
    );
    await vi.waitFor(() => expect(driver.disposed).toBe(1));
    const teardown = registry.disposeAll();
    release();

    expect(await firstOutcome).toBeInstanceOf(Error);
    const results = await teardown;
    expect(results).toHaveLength(1);
    expect(results[0]).toMatchObject({
      sessionId: "s1",
      provider: null,
      error: expect.objectContaining({ message: "process kill failed" }),
    });
    expect(registry.ownedSessionIds()).toEqual(["s1"]);
    let replacementAttempted = false;
    await expect(registry.replace("s1", "neko", async () => {
      replacementAttempted = true;
      return new FakeDriver("s1");
    })).rejects.toThrow("process kill failed");
    expect(replacementAttempted).toBe(false);
  });

  it("fails closed when a consumer requests an undeclared capability", async () => {
    const registry = new RuntimeRegistry();
    const attached = await registry.replace(
      "s1",
      "read-only",
      async () => new FakeDriver("s1", ["prompt"]),
    );

    expect(() => registry.requireInstance(
      "s1",
      attached.current.instanceId,
      "session-config",
    )).toThrow(RuntimeCapabilityError);
  });

  it("rejects a stale provider identity after replacement", async () => {
    const registry = new RuntimeRegistry();
    const first = new FakeDriver("s1");
    const one = await registry.replace("s1", "neko", async () => first);
    const second = new FakeDriver("s1");
    const two = await registry.replace("s1", "neko", async () => second);

    expect(() => registry.requireInstance("s1", one.current.instanceId, "prompt"))
      .toThrow(RuntimeProviderChangedError);
    expect(registry.requireInstance("s1", two.current.instanceId, "prompt")).toBe(second);
  });

  it("detaches only the exact provider instance requested", async () => {
    const registry = new RuntimeRegistry();
    const first = new FakeDriver("s1");
    const one = await registry.replace("s1", "neko", async () => first);
    const second = new FakeDriver("s1");
    const two = await registry.replace("s1", "neko", async () => second);

    await expect(registry.detachInstance("s1", one.current.instanceId))
      .resolves.toBeNull();
    expect(registry.get("s1")?.instanceId).toBe(two.current.instanceId);
    expect(second.disposed).toBe(0);

    const detached = await registry.detachInstance("s1", two.current.instanceId);
    expect(detached?.provider.instanceId).toBe(two.current.instanceId);
    expect(registry.get("s1")).toBeNull();
    expect(second.disposed).toBe(1);
  });

  it("revokes all bindings and starts every disposer before awaiting a stalled one", async () => {
    const registry = new RuntimeRegistry();
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    const first = new BlockingDisposeDriver("s1", gate);
    const second = new FakeDriver("s2");
    await registry.replace("s1", "neko", async () => first);
    await registry.replace("s2", "neko", async () => second);

    const disposing = registry.disposeAll();
    await Promise.resolve();

    expect(registry.get("s1")).toBeNull();
    expect(registry.get("s2")).toBeNull();
    expect(first.disposed).toBe(1);
    expect(second.disposed).toBe(1);

    release();
    await disposing;
  });

  it("does not report an attached provider when teardown wins during old cleanup", async () => {
    const registry = new RuntimeRegistry();
    let releaseOld!: () => void;
    const oldGate = new Promise<void>((resolve) => { releaseOld = resolve; });
    const old = new BlockingDisposeDriver("s1", oldGate);
    await registry.replace("s1", "old", async () => old);
    const replacement = new FakeDriver("s1");

    const replacing = registry.replace("s1", "new", async () => replacement);
    await vi.waitFor(() => expect(registry.get("s1")?.providerId).toBe("new"));
    const teardown = registry.disposeAll();
    releaseOld();

    await expect(replacing).rejects.toThrow(RuntimeProviderChangedError);
    await teardown;
    expect(registry.get("s1")).toBeNull();
    expect(replacement.disposed).toBe(1);
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

    let teardownSettled = false;
    const teardown = registry.disposeAll().finally(() => {
      teardownSettled = true;
    });
    await Promise.resolve();
    expect(teardownSettled).toBe(false);
    finishCreate(driver);

    await expect(creating).rejects.toThrow("cancelled during teardown");
    await teardown;
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

    let detachSettled = false;
    const detaching = registry.detach("s1").finally(() => {
      detachSettled = true;
    });
    await Promise.resolve();
    expect(detachSettled).toBe(false);
    finishCreate(driver);

    await expect(creating).rejects.toThrow("cancelled during teardown");
    await detaching;
    expect(driver.disposed).toBe(1);
    expect(registry.get("s1")).toBeNull();
  });

  it("awaits a late-owned driver's cleanup before detach completes", async () => {
    const registry = new RuntimeRegistry();
    let releaseDispose!: () => void;
    const disposeGate = new Promise<void>((resolve) => { releaseDispose = resolve; });
    const driver = new BlockingDisposeDriver("s1", disposeGate);
    let finishCreate!: (driver: Driver) => void;
    const creating = registry.replace(
      "s1",
      "neko",
      async () => new Promise<Driver>((resolve) => { finishCreate = resolve; }),
    );

    let detachSettled = false;
    const detaching = registry.detach("s1").finally(() => {
      detachSettled = true;
    });
    finishCreate(driver);
    await vi.waitFor(() => expect(driver.disposed).toBe(1));
    await Promise.resolve();

    expect(detachSettled).toBe(false);
    releaseDispose();
    await expect(creating).rejects.toThrow("cancelled during teardown");
    await detaching;
    expect(registry.get("s1")).toBeNull();
  });

  it("propagates a late-owned driver's cleanup failure to teardown", async () => {
    const registry = new RuntimeRegistry();
    let releaseDispose!: () => void;
    const disposeGate = new Promise<void>((resolve) => { releaseDispose = resolve; });
    const driver = new BlockingFailingDisposeDriver("s1", disposeGate);
    let finishCreate!: (driver: Driver) => void;
    const creating = registry.replace(
      "s1",
      "neko",
      async () => new Promise<Driver>((resolve) => { finishCreate = resolve; }),
    );
    const createOutcome = creating.then(
      () => null,
      (error) => error,
    );
    const detachOutcome = registry.detach("s1").then(
      () => null,
      (error) => error,
    );

    finishCreate(driver);
    await vi.waitFor(() => expect(driver.disposed).toBe(1));
    releaseDispose();

    expect(await createOutcome).toBeInstanceOf(AggregateError);
    expect(await detachOutcome).toMatchObject({ message: "process kill failed" });
    expect(registry.get("s1")).toBeNull();
  });

  it("owns and cancels a driver while its preparation is still pending", async () => {
    const registry = new RuntimeRegistry();
    const driver = new FakeDriver("s1");
    let rejectStart!: (error: Error) => void;
    const starting = new Promise<Driver>((_resolve, reject) => {
      rejectStart = reject;
    });
    const dispose = driver.dispose.bind(driver);
    driver.dispose = async () => {
      await dispose();
      rejectStart(new Error("client disposed"));
    };

    const creating = registry.replace("s1", "neko", async (_instanceId, own) => {
      own(driver);
      return starting;
    });
    await Promise.resolve();

    await expect(registry.detach("s1")).resolves.toBeNull();
    await expect(creating).rejects.toThrow("cancelled during teardown");
    expect(driver.disposed).toBe(1);
    expect(registry.get("s1")).toBeNull();
  });

  it("cleans up both drivers when a factory returns a different owned instance", async () => {
    const registry = new RuntimeRegistry();
    const owned = new FakeDriver("s1");
    const returned = new FakeDriver("s1");

    await expect(registry.replace("s1", "neko", async (_instanceId, own) => {
      own(owned);
      return returned;
    })).rejects.toThrow("more than one driver");

    expect(owned.disposed).toBe(1);
    expect(returned.disposed).toBe(1);
    expect(registry.get("s1")).toBeNull();
  });
});
