import { v4 as uuidv4 } from "uuid";
import type {
  Driver,
  DriverCapability,
  DriverKind,
  DriverRuntimeDescriptor,
} from "./drivers/types";

type Disposer = () => void | Promise<void>;

/**
 * Owns every resource created for one runtime. Disposal is idempotent and
 * runs in reverse registration order, matching nested resource ownership.
 */
export class RuntimeScope {
  private readonly disposers: Disposer[] = [];
  private disposePromise: Promise<void> | null = null;

  add(disposer: Disposer): void {
    if (this.disposePromise) {
      throw new Error("Không thể thêm tài nguyên vào runtime đã đóng.");
    }
    this.disposers.push(disposer);
  }

  dispose(): Promise<void> {
    if (this.disposePromise) return this.disposePromise;
    this.disposePromise = (async () => {
      let firstError: unknown;
      for (const disposer of [...this.disposers].reverse()) {
        try {
          await disposer();
        } catch (error) {
          firstError ??= error;
        }
      }
      this.disposers.length = 0;
      if (firstError) throw firstError;
    })();
    return this.disposePromise;
  }
}

export interface RuntimeProviderSnapshot extends DriverRuntimeDescriptor {
  sessionId: string;
  providerId: string;
  instanceId: string;
  kind: DriverKind;
}

interface RuntimeBinding {
  driver: Driver;
  provider: RuntimeProviderSnapshot;
  scope: RuntimeScope;
}

export interface RuntimeReplacement {
  current: RuntimeProviderSnapshot;
  previous: RuntimeProviderSnapshot | null;
  cleanupError?: unknown;
}

export interface RuntimeDisposalResult {
  provider: RuntimeProviderSnapshot;
  error?: unknown;
}

export class RuntimeCapabilityError extends Error {
  constructor(capability: DriverCapability) {
    super(`Runtime hiện tại không công bố capability "${capability}".`);
    this.name = "RuntimeCapabilityError";
  }
}

export class RuntimeProviderChangedError extends Error {
  constructor() {
    super("Runtime provider đã thay đổi trước khi thao tác được gửi.");
    this.name = "RuntimeProviderChangedError";
  }
}

/**
 * Live runtimes stay outside Zustand, but no longer live in an unowned map.
 * A replacement is prepared first; factory failure leaves the prior binding
 * untouched. A fresh instanceId makes provider identity changes observable.
 */
export class RuntimeRegistry {
  private readonly bindings = new Map<string, RuntimeBinding>();
  private readonly sessionGenerations = new Map<string, number>();
  private readonly pendingPreparations = new Map<string, Set<RuntimeScope>>();
  private generation = 0;

  get(sessionId: string): RuntimeProviderSnapshot | null {
    return this.bindings.get(sessionId)?.provider ?? null;
  }

  isCurrent(sessionId: string, instanceId: string): boolean {
    return this.bindings.get(sessionId)?.provider.instanceId === instanceId;
  }

  /** Sessions with either a committed provider or an owned preparation. */
  ownedSessionIds(): string[] {
    return [
      ...new Set([...this.bindings.keys(), ...this.pendingPreparations.keys()]),
    ];
  }

  requireInstance(
    sessionId: string,
    instanceId: string,
    capability: DriverCapability,
  ): Driver {
    const binding = this.bindings.get(sessionId);
    if (!binding || binding.provider.instanceId !== instanceId) {
      throw new RuntimeProviderChangedError();
    }
    if (!binding.provider.capabilities.includes(capability)) {
      throw new RuntimeCapabilityError(capability);
    }
    return binding.driver;
  }

  async replace(
    sessionId: string,
    providerId: string,
    create: (instanceId: string, own: (driver: Driver) => void) => Promise<Driver>,
  ): Promise<RuntimeReplacement> {
    const preparationScope = new RuntimeScope();
    const preparations =
      this.pendingPreparations.get(sessionId) ?? new Set<RuntimeScope>();
    preparations.add(preparationScope);
    this.pendingPreparations.set(sessionId, preparations);
    let ownedDriver: Driver | null = null;
    const own = (driver: Driver) => {
      if (ownedDriver && ownedDriver !== driver) {
        void driver.dispose().catch(() => {});
        throw new Error("Runtime preparation returned more than one driver.");
      }
      if (ownedDriver) return;
      ownedDriver = driver;
      try {
        preparationScope.add(() => driver.dispose());
      } catch (error) {
        void driver.dispose().catch(() => {});
        throw error;
      }
    };
    try {
      // Transaction prepare: no registry mutation until creation succeeds.
      const generation = this.generation;
      const sessionGeneration = this.sessionGenerations.get(sessionId) ?? 0;
      const instanceId = uuidv4();
      let driver: Driver;
      try {
        driver = await create(instanceId, own);
        own(driver);
      } catch (error) {
        try {
          await preparationScope.dispose();
        } catch (cleanupError) {
          throw new AggregateError(
            [error, cleanupError],
            "Runtime preparation and cleanup both failed.",
          );
        }
        if (
          generation !== this.generation ||
          sessionGeneration !== (this.sessionGenerations.get(sessionId) ?? 0)
        ) {
          throw new Error("Runtime preparation was cancelled during teardown.");
        }
        throw error;
      }
      if (
        generation !== this.generation ||
        sessionGeneration !== (this.sessionGenerations.get(sessionId) ?? 0)
      ) {
        await preparationScope.dispose().catch(() => {});
        throw new Error("Runtime preparation was cancelled during teardown.");
      }
      if (driver.sessionId !== sessionId) {
        await preparationScope.dispose().catch(() => {});
        throw new Error("Driver trả về sai sessionId.");
      }

      const provider: RuntimeProviderSnapshot = {
        sessionId,
        providerId,
        instanceId,
        kind: driver.kind,
        capabilities: [...new Set(driver.runtime.capabilities)],
        contextContinuity: driver.runtime.contextContinuity,
        workspaceIsolation: driver.runtime.workspaceIsolation,
      };
      const previous = this.bindings.get(sessionId) ?? null;

      // Commit: all consumers resolve to the new provider identity atomically.
      this.bindings.set(sessionId, { driver, provider, scope: preparationScope });
      let cleanupError: unknown;
      if (previous) {
        try {
          await previous.scope.dispose();
        } catch (error) {
          cleanupError = error;
        }
      }
      if (this.bindings.get(sessionId)?.provider.instanceId !== instanceId) {
        // Teardown or another replacement won while the prior scope was
        // closing. Never report a provider whose ownership was revoked.
        throw new RuntimeProviderChangedError();
      }
      return {
        current: provider,
        previous: previous?.provider ?? null,
        ...(cleanupError ? { cleanupError } : {}),
      };
    } finally {
      const pending = this.pendingPreparations.get(sessionId);
      pending?.delete(preparationScope);
      if (!pending || pending.size === 0) {
        this.pendingPreparations.delete(sessionId);
        this.sessionGenerations.delete(sessionId);
      }
    }
  }

  async detach(sessionId: string): Promise<RuntimeProviderSnapshot | null> {
    this.sessionGenerations.set(
      sessionId,
      (this.sessionGenerations.get(sessionId) ?? 0) + 1,
    );
    const binding = this.bindings.get(sessionId);
    const preparations = [...(this.pendingPreparations.get(sessionId) ?? [])];
    if (binding) this.bindings.delete(sessionId);
    try {
      const scopes = new Set([
        ...preparations,
        ...(binding ? [binding.scope] : []),
      ]);
      const results = await Promise.allSettled([...scopes].map((scope) => scope.dispose()));
      const failed = results.find(
        (result): result is PromiseRejectedResult => result.status === "rejected",
      );
      if (failed) throw failed.reason;
      return binding?.provider ?? null;
    } finally {
      if (!this.pendingPreparations.has(sessionId)) {
        this.sessionGenerations.delete(sessionId);
      }
    }
  }

  /** Revoke only the provider that observed an uncertain operation. */
  async detachInstance(
    sessionId: string,
    instanceId: string,
  ): Promise<RuntimeDisposalResult | null> {
    const binding = this.bindings.get(sessionId);
    if (!binding || binding.provider.instanceId !== instanceId) return null;
    this.sessionGenerations.set(
      sessionId,
      (this.sessionGenerations.get(sessionId) ?? 0) + 1,
    );
    // Revoke synchronously so no further consumer can dispatch while cleanup
    // awaits a process or transport disposer.
    this.bindings.delete(sessionId);
    let error: unknown;
    try {
      await binding.scope.dispose();
    } catch (disposeError) {
      error = disposeError;
    } finally {
      if (!this.pendingPreparations.has(sessionId)) {
        this.sessionGenerations.delete(sessionId);
      }
    }
    return {
      provider: binding.provider,
      ...(error ? { error } : {}),
    };
  }

  async disposeAll(): Promise<Array<{ provider: RuntimeProviderSnapshot; error?: unknown }>> {
    // Invalidates in-flight preparations before touching committed bindings.
    this.generation += 1;
    const bindings = [...this.bindings.values()];
    const preparationScopes = [
      ...new Set([...this.pendingPreparations.values()].flatMap((scopes) => [...scopes])),
    ];
    // Revoke every provider synchronously before awaiting any disposer. A
    // stalled process cannot leave unrelated sessions registered or unowned.
    this.bindings.clear();
    const bindingScopes = new Set(bindings.map((binding) => binding.scope));
    const pendingDisposals = preparationScopes
      .filter((scope) => !bindingScopes.has(scope))
      .map((scope) => scope.dispose().catch(() => {}));
    const bindingResults = Promise.all(bindings.map(async (binding) => {
      try {
        await binding.scope.dispose();
        return { provider: binding.provider };
      } catch (error) {
        return { provider: binding.provider, error };
      }
    }));
    const [results] = await Promise.all([bindingResults, Promise.all(pendingDisposals)]);
    return results;
  }

  /** Simulates process loss/restart without touching test-owned fakes. */
  clearForTests(): void {
    this.generation += 1;
    this.sessionGenerations.clear();
    this.pendingPreparations.clear();
    this.bindings.clear();
  }
}
