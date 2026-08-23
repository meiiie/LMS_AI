import { v4 as uuidv4 } from "uuid";
import type {
  Driver,
  DriverCapability,
  DriverKind,
  DriverRuntimeDescriptor,
} from "./drivers/types";
import type { NekoProviderCapabilitySnapshot } from "@/neko/contracts";
import {
  createProviderCapabilitySnapshot,
  findProviderDefinition,
} from "@/neko/provider-registry";

type Disposer = () => void | Promise<void>;
type CleanupOutcome = { failed: false } | { failed: true; error: unknown };

async function observeCleanup(operation: Promise<unknown>): Promise<CleanupOutcome> {
  try {
    await operation;
    return { failed: false };
  } catch (error) {
    return { failed: true, error };
  }
}

/**
 * Owns every resource created for one runtime. Disposal is idempotent and
 * runs in reverse registration order, matching nested resource ownership.
 */
export class RuntimeScope {
  private readonly disposers: Disposer[] = [];
  private disposePromise: Promise<void> | null = null;
  private disposalStarted = false;

  add(disposer: Disposer): void {
    if (this.disposalStarted) {
      throw new Error("Không thể thêm tài nguyên vào runtime đã đóng.");
    }
    this.disposers.push(disposer);
  }

  dispose(): Promise<void> {
    if (this.disposePromise) return this.disposePromise;
    this.disposalStarted = true;
    if (this.disposers.length === 0) return Promise.resolve();
    const attempt = (async () => {
      let failed = false;
      let firstError: unknown;
      const failedDisposers: Disposer[] = [];
      for (const disposer of [...this.disposers].reverse()) {
        try {
          await disposer();
        } catch (error) {
          failedDisposers.push(disposer);
          if (!failed) {
            failed = true;
            firstError = error;
          }
        }
      }
      // Successful siblings are permanently released. Failed idempotent
      // cleanup authorities remain in registration order for an explicit
      // later retry with the same provider cancellation identity.
      this.disposers.splice(0, this.disposers.length, ...failedDisposers.reverse());
      if (failed) throw firstError;
    })();
    this.disposePromise = attempt;
    void attempt.then(
      () => {
        if (this.disposePromise === attempt) this.disposePromise = null;
      },
      () => {
        if (this.disposePromise === attempt) this.disposePromise = null;
      },
    );
    return attempt;
  }
}

export interface RuntimeProviderSnapshot extends DriverRuntimeDescriptor {
  sessionId: string;
  providerId: string;
  instanceId: string;
  kind: DriverKind;
  backendSessionId: string | null;
  /** Historical contract observed at attach time; absent on legacy/unknown providers. */
  providerCapabilities?: NekoProviderCapabilitySnapshot;
}

interface RuntimeBinding {
  driver: Driver;
  provider: RuntimeProviderSnapshot;
  scope: RuntimeScope;
}

interface RuntimePreparation {
  scope: RuntimeScope;
  completion: Promise<void>;
  complete: (outcome: { ok: true } | { ok: false; error: unknown }) => void;
}

export interface RuntimeReplacement {
  current: RuntimeProviderSnapshot;
  previous: RuntimeProviderSnapshot | null;
  cleanupFailed: boolean;
  cleanupError?: unknown;
}

export interface RuntimeDisposalResult {
  provider: RuntimeProviderSnapshot;
  cleanupFailed: boolean;
  error?: unknown;
}

export interface RuntimeSessionDisposalResult {
  sessionId: string;
  provider: RuntimeProviderSnapshot | null;
  cleanupFailed: boolean;
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
  private readonly retainedCleanupScopes = new Map<string, Set<RuntimeScope>>();
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
        ...this.retainedCleanupScopes.keys(),
      ]),
    ];
  }

  private joinDisposal(
    sessionId: string,
    work?: () => Promise<void>,
  ): Promise<void> | null {
    const previous = this.inFlightDisposals.get(sessionId);
    if (!work) return previous ?? null;
    // A later cleanup request joins the active attempt, then gets one chance
    // to retry any authority retained by that attempt. Prior rejection is not
    // itself permanent state; the retained scope is.
    const combined = previous
      ? previous.then(work, work)
      : Promise.resolve().then(work);
    let tracked!: Promise<void>;
    tracked = combined.then(
      () => {
        if (this.inFlightDisposals.get(sessionId) === tracked) {
          this.inFlightDisposals.delete(sessionId);
        }
      },
      (error) => {
        if (this.inFlightDisposals.get(sessionId) === tracked) {
          this.inFlightDisposals.delete(sessionId);
        }
        throw error;
      },
    );
    this.inFlightDisposals.set(sessionId, tracked);
    return tracked;
  }

  private cleanupSession(
    sessionId: string,
    scopes: Iterable<RuntimeScope>,
    completions: Iterable<Promise<void>> = [],
  ): Promise<void> | null {
    const suppliedScopes = [...new Set(scopes)];
    if (suppliedScopes.length > 0) {
      const retained = this.retainedCleanupScopes.get(sessionId) ?? new Set<RuntimeScope>();
      for (const scope of suppliedScopes) retained.add(scope);
      this.retainedCleanupScopes.set(sessionId, retained);
    }
    const completionList = [...new Set(completions)];
    if (!this.retainedCleanupScopes.has(sessionId) && completionList.length === 0) {
      return this.joinDisposal(sessionId);
    }
    return this.joinDisposal(sessionId, async () => {
      const retained = [
        ...(this.retainedCleanupScopes.get(sessionId) ?? new Set<RuntimeScope>()),
      ];
      const results = await Promise.allSettled([
        ...retained.map((scope) => scope.dispose()),
        ...completionList,
      ]);
      const retainedSet = this.retainedCleanupScopes.get(sessionId);
      retained.forEach((scope, index) => {
        if (results[index]?.status === "fulfilled") retainedSet?.delete(scope);
      });
      if (retainedSet?.size === 0) this.retainedCleanupScopes.delete(sessionId);
      const failed = results.find(
        (result): result is PromiseRejectedResult => result.status === "rejected",
      );
      if (failed) throw failed.reason;
    });
  }

  private retainCleanupScope(sessionId: string, scope: RuntimeScope): void {
    const retained = this.retainedCleanupScopes.get(sessionId) ?? new Set<RuntimeScope>();
    retained.add(scope);
    this.retainedCleanupScopes.set(sessionId, retained);
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
    const priorCleanup = this.cleanupSession(sessionId, []);
    if (priorCleanup) await priorCleanup;
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
      complete: (outcome) => {
        if (outcome.ok) completePreparation();
        else rejectPreparation(outcome.error);
      },
    };
    const preparations =
      this.pendingPreparations.get(sessionId) ?? new Set<RuntimePreparation>();
    preparations.add(preparation);
    this.pendingPreparations.set(sessionId, preparations);
    let ownedDriver: Driver | null = null;
    const unownedCleanups: Promise<void>[] = [];
    let preparationCleanupFailed = false;
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
          preparationCleanupFailed = true;
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
        const cleanup = await observeCleanup(preparation.scope.dispose());
        if (cleanup.failed) {
          preparationCleanupFailed = true;
          preparationCleanupError = cleanup.error;
          throw new AggregateError(
            [new Error("Runtime preparation was cancelled during teardown."), cleanup.error],
            "Runtime preparation cancellation and cleanup both failed.",
          );
        }
        throw new Error("Runtime preparation was cancelled during teardown.");
      }
      if (driver.sessionId !== sessionId) {
        const cleanup = await observeCleanup(preparation.scope.dispose());
        if (cleanup.failed) {
          preparationCleanupFailed = true;
          preparationCleanupError = cleanup.error;
          throw new AggregateError(
            [new Error("Driver trả về sai sessionId."), cleanup.error],
            "Invalid runtime preparation and cleanup both failed.",
          );
        }
        throw new Error("Driver trả về sai sessionId.");
      }

      const providerDefinition = findProviderDefinition(providerId);
      const providerCapabilities = providerDefinition
        ? createProviderCapabilitySnapshot({
            providerId,
            providerVersion: driver.runtime.providerVersion ?? null,
            established: driver.runtime.observedProviderCapabilities,
            extensions: driver.runtime.providerExtensions,
          })
        : undefined;
      const provider: RuntimeProviderSnapshot = {
        sessionId,
        providerId,
        instanceId,
        kind: driver.kind,
        backendSessionId: driver.backendSessionId ?? null,
        capabilities: [...new Set(driver.runtime.capabilities)],
        contextContinuity: driver.runtime.contextContinuity,
        workspaceIsolation: driver.runtime.workspaceIsolation,
        ...(providerCapabilities ? { providerCapabilities } : {}),
      };
      const previous = this.bindings.get(sessionId) ?? null;

      // Commit: all consumers resolve to the new provider identity atomically.
      this.bindings.set(sessionId, { driver, provider, scope: preparation.scope });
      let cleanupFailed = false;
      let cleanupError: unknown;
      if (previous) {
        try {
          await this.cleanupSession(sessionId, [previous.scope]);
        } catch (error) {
          cleanupFailed = true;
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
        cleanupFailed,
        ...(cleanupFailed ? { cleanupError } : {}),
      };
    } finally {
      if (preparationCleanupFailed) {
        this.retainCleanupScope(sessionId, preparation.scope);
      }
      preparation.complete(
        preparationCleanupFailed
          ? { ok: false, error: preparationCleanupError }
          : { ok: true },
      );
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
      const cleanup = this.cleanupSession(sessionId, []);
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
    let cleanupFailed = false;
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
      cleanupFailed = true;
      error = disposeError;
    } finally {
      if (!this.pendingPreparations.has(sessionId)) {
        this.sessionGenerations.delete(sessionId);
      }
    }
    return {
      provider: binding.provider,
      cleanupFailed,
      ...(cleanupFailed ? { error } : {}),
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
      ...this.retainedCleanupScopes.keys(),
    ]);
    // Revoke every provider synchronously before awaiting any disposer. A
    // stalled process cannot leave unrelated sessions registered or unowned.
    this.bindings.clear();
    const cleanupFailures = new Set<string>();
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
        cleanupFailures.add(sessionId);
        cleanupResults.set(sessionId, error);
      }
    }));
    return [...sessionIds].map((sessionId) => {
      const provider = bindings.find(
        (binding) => binding.provider.sessionId === sessionId,
      )?.provider ?? null;
      const error = cleanupResults.get(sessionId);
      const cleanupFailed = cleanupFailures.has(sessionId);
      return {
        sessionId,
        provider,
        cleanupFailed,
        ...(cleanupFailed ? { error } : {}),
      };
    });
  }

  /** Simulates process loss/restart without touching test-owned fakes. */
  clearForTests(): void {
    this.generation += 1;
    this.sessionGenerations.clear();
    this.pendingPreparations.clear();
    this.inFlightDisposals.clear();
    this.retainedCleanupScopes.clear();
    this.bindings.clear();
  }
}
