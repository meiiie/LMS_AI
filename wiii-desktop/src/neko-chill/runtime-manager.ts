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

interface RuntimePreparation {
  scope: RuntimeScope;
  completion: Promise<void>;
  complete: (error?: unknown) => void;
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

export interface RuntimeSessionDisposalResult {
  sessionId: string;
  provider: RuntimeProviderSnapshot | null;
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
  private readonly pendingPreparations = new Map<string, Set<RuntimePreparation>>();
  private readonly inFlightDisposals = new Map<string, Promise<void>>();
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
      ...new Set([
        ...this.bindings.keys(),
        ...this.pendingPreparations.keys(),
        ...this.inFlightDisposals.keys(),
      ]),
    ];
  }

  private joinDisposal(sessionId: string, work?: Promise<void>): Promise<void> | null {
    const previous = this.inFlightDisposals.get(sessionId);
    if (!work) return previous ?? null;
    const combined = previous
      ? Promise.allSettled([previous, work]).then((results) => {
          const failed = results.find(
            (result): result is PromiseRejectedResult => result.status === "rejected",
          );
          if (failed) throw failed.reason;
        })
      : work;
    let tracked!: Promise<void>;
    tracked = combined.finally(() => {
      if (this.inFlightDisposals.get(sessionId) === tracked) {
        this.inFlightDisposals.delete(sessionId);
      }
    });
    this.inFlightDisposals.set(sessionId, tracked);
    return tracked;
  }

  private cleanupSession(
    sessionId: string,
    scopes: Iterable<RuntimeScope>,
    completions: Iterable<Promise<void>> = [],
  ): Promise<void> | null {
    const tasks = [
      ...new Set([
        ...[...scopes].map((scope) => scope.dispose()),
        ...completions,
      ]),
    ];
    if (tasks.length === 0) return this.joinDisposal(sessionId);
    const work = Promise.allSettled(tasks).then((results) => {
      const failed = results.find(
        (result): result is PromiseRejectedResult => result.status === "rejected",
      );
      if (failed) throw failed.reason;
    });
    return this.joinDisposal(sessionId, work);
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
    let completePreparation!: () => void;
    let rejectPreparation!: (error: unknown) => void;
    const preparationCompletion = new Promise<void>((resolve, reject) => {
      completePreparation = resolve;
      rejectPreparation = reject;
    });
    // replace() reports the same cleanup failure to its caller. This handler
    // prevents an unobserved rejection when no teardown is concurrently joining.
    void preparationCompletion.catch(() => {});
    const preparation: RuntimePreparation = {
      scope: new RuntimeScope(),
      completion: preparationCompletion,
      complete: (error) => {
        if (error === undefined) completePreparation();
        else rejectPreparation(error);
      },
    };
    const preparations =
      this.pendingPreparations.get(sessionId) ?? new Set<RuntimePreparation>();
    preparations.add(preparation);
    this.pendingPreparations.set(sessionId, preparations);
    let ownedDriver: Driver | null = null;
    const unownedCleanups: Promise<void>[] = [];
    let preparationCleanupError: unknown;
    const own = (driver: Driver) => {
      if (ownedDriver && ownedDriver !== driver) {
        unownedCleanups.push(driver.dispose());
        throw new Error("Runtime preparation returned more than one driver.");
      }
      if (ownedDriver) return;
      ownedDriver = driver;
      try {
        preparation.scope.add(() => driver.dispose());
      } catch (error) {
        // Teardown may have disposed an empty preparation scope while the
        // factory was still constructing its transport. Retain this cleanup;
        // the preparation completion below does not resolve until it settles.
        unownedCleanups.push(driver.dispose());
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
        const cleanupResults = await Promise.allSettled([
          preparation.scope.dispose(),
          ...unownedCleanups,
        ]);
        const cleanupError = cleanupResults.find(
          (result): result is PromiseRejectedResult => result.status === "rejected",
        );
        if (cleanupError) {
          preparationCleanupError = cleanupError.reason;
          throw new AggregateError(
            [error, cleanupError.reason],
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
        const cleanupError = await preparation.scope.dispose().then(
          () => null,
          (error) => error,
        );
        if (cleanupError) {
          preparationCleanupError = cleanupError;
          throw new AggregateError(
            [new Error("Runtime preparation was cancelled during teardown."), cleanupError],
            "Runtime preparation cancellation and cleanup both failed.",
          );
        }
        throw new Error("Runtime preparation was cancelled during teardown.");
      }
      if (driver.sessionId !== sessionId) {
        const cleanupError = await preparation.scope.dispose().then(
          () => null,
          (error) => error,
        );
        if (cleanupError) {
          preparationCleanupError = cleanupError;
          throw new AggregateError(
            [new Error("Driver trả về sai sessionId."), cleanupError],
            "Invalid runtime preparation and cleanup both failed.",
          );
        }
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
      this.bindings.set(sessionId, { driver, provider, scope: preparation.scope });
      let cleanupError: unknown;
      if (previous) {
        try {
          await this.joinDisposal(sessionId, previous.scope.dispose());
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
      preparation.complete(preparationCleanupError);
      const pending = this.pendingPreparations.get(sessionId);
      pending?.delete(preparation);
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
        ...preparations.map((preparation) => preparation.scope),
        ...(binding ? [binding.scope] : []),
      ]);
      const cleanup = this.cleanupSession(
        sessionId,
        scopes,
        preparations.map((preparation) => preparation.completion),
      );
      if (cleanup) await cleanup;
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
    if (!binding || binding.provider.instanceId !== instanceId) {
      const cleanup = this.joinDisposal(sessionId);
      if (cleanup) await cleanup;
      return null;
    }
    this.sessionGenerations.set(
      sessionId,
      (this.sessionGenerations.get(sessionId) ?? 0) + 1,
    );
    // Revoke synchronously so no further consumer can dispatch while cleanup
    // awaits a process or transport disposer.
    this.bindings.delete(sessionId);
    let error: unknown;
    try {
      const preparations = [...(this.pendingPreparations.get(sessionId) ?? [])];
      const cleanup = this.cleanupSession(
        sessionId,
        [binding.scope, ...preparations.map((preparation) => preparation.scope)],
        preparations.map((preparation) => preparation.completion),
      );
      if (cleanup) await cleanup;
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

  async disposeAll(): Promise<RuntimeSessionDisposalResult[]> {
    // Invalidates in-flight preparations before touching committed bindings.
    this.generation += 1;
    const bindings = [...this.bindings.values()];
    const preparations = [...this.pendingPreparations.values()].flatMap((pending) => [...pending]);
    const sessionIds = new Set([
      ...bindings.map((binding) => binding.provider.sessionId),
      ...this.pendingPreparations.keys(),
      ...this.inFlightDisposals.keys(),
    ]);
    // Revoke every provider synchronously before awaiting any disposer. A
    // stalled process cannot leave unrelated sessions registered or unowned.
    this.bindings.clear();
    const cleanupResults = new Map<string, unknown>();
    await Promise.all([...sessionIds].map(async (sessionId) => {
      const sessionBindings = bindings.filter(
        (binding) => binding.provider.sessionId === sessionId,
      );
      const sessionPreparations = preparations.filter((preparation) =>
        this.pendingPreparations.get(sessionId)?.has(preparation));
      const cleanup = this.cleanupSession(
        sessionId,
        [
          ...sessionBindings.map((binding) => binding.scope),
          ...sessionPreparations.map((preparation) => preparation.scope),
        ],
        sessionPreparations.map((preparation) => preparation.completion),
      );
      if (!cleanup) return;
      try {
        await cleanup;
      } catch (error) {
        cleanupResults.set(sessionId, error);
      }
    }));
    return [...sessionIds].map((sessionId) => {
      const provider = bindings.find(
        (binding) => binding.provider.sessionId === sessionId,
      )?.provider ?? null;
      const error = cleanupResults.get(sessionId);
      return {
        sessionId,
        provider,
        ...(error ? { error } : {}),
      };
    });
  }

  /** Simulates process loss/restart without touching test-owned fakes. */
  clearForTests(): void {
    this.generation += 1;
    this.sessionGenerations.clear();
    this.pendingPreparations.clear();
    this.inFlightDisposals.clear();
    this.bindings.clear();
  }
}
