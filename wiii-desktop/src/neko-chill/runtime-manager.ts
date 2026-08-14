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
  private readonly pendingPreparations = new Map<string, number>();
  private generation = 0;

  get(sessionId: string): RuntimeProviderSnapshot | null {
    return this.bindings.get(sessionId)?.provider ?? null;
  }

  isCurrent(sessionId: string, instanceId: string): boolean {
    return this.bindings.get(sessionId)?.provider.instanceId === instanceId;
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
    create: (instanceId: string) => Promise<Driver>,
  ): Promise<RuntimeReplacement> {
    this.pendingPreparations.set(
      sessionId,
      (this.pendingPreparations.get(sessionId) ?? 0) + 1,
    );
    try {
      // Transaction prepare: no registry mutation until creation succeeds.
      const generation = this.generation;
      const sessionGeneration = this.sessionGenerations.get(sessionId) ?? 0;
      const instanceId = uuidv4();
      const driver = await create(instanceId);
      if (
        generation !== this.generation ||
        sessionGeneration !== (this.sessionGenerations.get(sessionId) ?? 0)
      ) {
        await driver.dispose().catch(() => {});
        throw new Error("Runtime preparation was cancelled during teardown.");
      }
      if (driver.sessionId !== sessionId) {
        await driver.dispose().catch(() => {});
        throw new Error("Driver trả về sai sessionId.");
      }

      const scope = new RuntimeScope();
      scope.add(() => driver.dispose());
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
      this.bindings.set(sessionId, { driver, provider, scope });
      let cleanupError: unknown;
      if (previous) {
        try {
          await previous.scope.dispose();
        } catch (error) {
          cleanupError = error;
        }
      }
      return {
        current: provider,
        previous: previous?.provider ?? null,
        ...(cleanupError ? { cleanupError } : {}),
      };
    } finally {
      const pending = (this.pendingPreparations.get(sessionId) ?? 1) - 1;
      if (pending > 0) {
        this.pendingPreparations.set(sessionId, pending);
      } else {
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
    if (!binding) {
      if (!this.pendingPreparations.has(sessionId)) {
        this.sessionGenerations.delete(sessionId);
      }
      return null;
    }
    this.bindings.delete(sessionId);
    try {
      await binding.scope.dispose();
      return binding.provider;
    } finally {
      if (!this.pendingPreparations.has(sessionId)) {
        this.sessionGenerations.delete(sessionId);
      }
    }
  }

  async disposeAll(): Promise<Array<{ provider: RuntimeProviderSnapshot; error?: unknown }>> {
    // Invalidates in-flight preparations before touching committed bindings.
    this.generation += 1;
    const bindings = [...this.bindings.values()];
    // Revoke every provider synchronously before awaiting any disposer. A
    // stalled process cannot leave unrelated sessions registered or unowned.
    this.bindings.clear();
    return Promise.all(bindings.map(async (binding) => {
      try {
        await binding.scope.dispose();
        return { provider: binding.provider };
      } catch (error) {
        return { provider: binding.provider, error };
      }
    }));
  }

  /** Simulates process loss/restart without touching test-owned fakes. */
  clearForTests(): void {
    this.generation += 1;
    this.sessionGenerations.clear();
    this.pendingPreparations.clear();
    this.bindings.clear();
  }
}
