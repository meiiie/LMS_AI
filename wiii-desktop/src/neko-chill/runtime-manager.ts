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

interface RuntimeCleanupAuthority {
  scope: RuntimeScope;
  provider: RuntimeProviderSnapshot | null;
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
  private readonly retainedCleanupScopes = new Map<
    string,
    Map<RuntimeScope, RuntimeProviderSnapshot | null>
  >();
  private generation = 0;

  get(sessionId: string): RuntimeProviderSnapshot | null {
    return this.bindings.get(sessionId)?.provider ?? null;
  }

  isCurrent(sessionId: string, instanceId: string): boolean {
    return this.bindings.get(sessionId)?.provider.instanceId === instanceId;
  }

  hasRetainedCleanup(sessionId: string): boolean {
    return (this.retainedCleanupScopes.get(sessionId)?.size ?? 0) > 0;
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
    authorities: Iterable<RuntimeCleanupAuthority>,
    completions: Iterable<Promise<void>> = [],
  ): Promise<void> | null {
    const suppliedAuthorities = [...authorities];
    if (suppliedAuthorities.length > 0) {
      const retained = this.retainedCleanupScopes.get(sessionId) ?? new Map();
      for (const authority of suppliedAuthorities) {
        const existing = retained.get(authority.scope);
        if (!retained.has(authority.scope) || (existing === null && authority.provider)) {
          retained.set(authority.scope, authority.provider);
        }
      }
      this.retainedCleanupScopes.set(sessionId, retained);
    }
    const completionList = [...new Set(completions)];
    if (!this.retainedCleanupScopes.has(sessionId) && completionList.length === 0) {
      return this.joinDisposal(sessionId);
    }
    return this.joinDisposal(sessionId, async () => {
      const retained = [...(this.retainedCleanupScopes.get(sessionId) ?? new Map()).keys()];
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

  private retainCleanupScope(
    sessionId: string,
    scope: RuntimeScope,
    provider: RuntimeProviderSnapshot | null = null,
  ): void {
    const retained = this.retainedCleanupScopes.get(sessionId) ?? new Map();
    const existing = retained.get(scope);
    if (!retained.has(scope) || (existing === null && provider)) {
      retained.set(scope, provider);
    }
    this.retainedCleanupScopes.set(sessionId, retained);
  }

  private retainedProvider(sessionId: string): RuntimeProviderSnapshot | null {
    for (const provider of this.retainedCleanupScopes.get(sessionId)?.values() ?? []) {
      if (provider) return provider;
    }
    return null;
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
    const recoveredProvider = this.retainedProvider(sessionId);
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
    const unownedScopes: RuntimeScope[] = [];
    let preparationCleanupFailed = false;
    let preparationCleanupError: unknown;
    const own = (driver: Driver) => {
      if (ownedDriver && ownedDriver !== driver) {
        const scope = new RuntimeScope();
        scope.add(() => driver.dispose());
        unownedScopes.push(scope);
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
        const scope = new RuntimeScope();
        scope.add(() => driver.dispose());
        unownedScopes.push(scope);
        throw error;
      }
    };
    const disposePreparation = async (): Promise<CleanupOutcome> => {
      const scopes = [preparation.scope, ...unownedScopes];
      const results = await Promise.allSettled(scopes.map((scope) => scope.dispose()));
      const failed = results.find(
        (result): result is PromiseRejectedResult => result.status === "rejected",
      );
      if (!failed) return { failed: false };
      for (const scope of scopes) this.retainCleanupScope(sessionId, scope);
      return { failed: true, error: failed.reason };
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
        const cleanup = await disposePreparation();
        if (cleanup.failed) {
          preparationCleanupFailed = true;
          preparationCleanupError = cleanup.error;
          throw new AggregateError(
            [error, cleanup.error],
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
        const cleanup = await disposePreparation();
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
        const cleanup = await disposePreparation();
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

      // Revoke the old identity before cleanup, but never publish the new one
      // until the old process/transport has been proven closed.
      if (previous) {
        if (this.bindings.get(sessionId)?.provider.instanceId !== previous.provider.instanceId) {
          const cleanup = await disposePreparation();
          if (cleanup.failed) {
            preparationCleanupFailed = true;
            preparationCleanupError = cleanup.error;
          }
          throw new RuntimeProviderChangedError();
        }
        this.bindings.delete(sessionId);
        try {
          await this.cleanupSession(sessionId, [{ scope: previous.scope, provider: previous.provider }]);
        } catch (error) {
          const cleanup = await disposePreparation();
          if (cleanup.failed) {
            preparationCleanupFailed = true;
            preparationCleanupError = cleanup.error;
            throw new AggregateError(
              [error, cleanup.error],
              "Previous runtime cleanup and replacement cleanup both failed.",
            );
          }
          throw error;
        }
      }
      if (
        generation !== this.generation ||
        sessionGeneration !== (this.sessionGenerations.get(sessionId) ?? 0) ||
        this.bindings.has(sessionId)
      ) {
        const cleanup = await disposePreparation();
        if (cleanup.failed) {
          preparationCleanupFailed = true;
          preparationCleanupError = cleanup.error;
        }
        throw new RuntimeProviderChangedError();
      }
      // Commit: all consumers resolve to the new provider identity atomically.
      this.bindings.set(sessionId, { driver, provider, scope: preparation.scope });
      return {
        current: provider,
        previous: previous?.provider ?? recoveredProvider,
        cleanupFailed: false,
      };
    } finally {
      if (preparationCleanupFailed) {
        this.retainCleanupScope(sessionId, preparation.scope);
        for (const scope of unownedScopes) this.retainCleanupScope(sessionId, scope);
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
    const retainedProvider = this.retainedProvider(sessionId);
    const preparations = [...(this.pendingPreparations.get(sessionId) ?? [])];
    if (binding) this.bindings.delete(sessionId);
    try {
      const authorities: RuntimeCleanupAuthority[] = [
        ...preparations.map((preparation) => ({ scope: preparation.scope, provider: null })),
        ...(binding ? [{ scope: binding.scope, provider: binding.provider }] : []),
      ];
      const cleanup = this.cleanupSession(
        sessionId,
        authorities,
        preparations.map((preparation) => preparation.completion),
      );
      if (cleanup) await cleanup;
      return binding?.provider ?? retainedProvider;
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
      const provider = this.retainedProvider(sessionId);
      const cleanup = this.cleanupSession(sessionId, []);
      if (cleanup) await cleanup;
      return provider
        ? { provider, cleanupFailed: false }
        : null;
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
        [
          { scope: binding.scope, provider: binding.provider },
          ...preparations.map((preparation) => ({ scope: preparation.scope, provider: null })),
        ],
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
    const providers = new Map<string, RuntimeProviderSnapshot | null>(
      [...sessionIds].map((sessionId) => [
        sessionId,
        bindings.find((binding) => binding.provider.sessionId === sessionId)?.provider ??
          this.retainedProvider(sessionId),
      ]),
    );
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
          ...sessionBindings.map((binding) => ({ scope: binding.scope, provider: binding.provider })),
          ...sessionPreparations.map((preparation) => ({ scope: preparation.scope, provider: null })),
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
      const provider = providers.get(sessionId) ?? null;
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
