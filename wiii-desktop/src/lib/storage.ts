/**
 * Wrapper around tauri-plugin-store for persistent local storage.
 * Falls back to localStorage when running in browser (dev without Tauri).
 */

let Store: any = null;
let tauriAvailable: boolean | null = null;

/**
 * Get storage key prefix for embed mode.
 * In embed mode, keys are namespaced by org and user to avoid conflicts
 * between multiple embed instances and the main app.
 */
function getEmbedPrefix(): string {
  const config = (window as any).__WIII_EMBED_CONFIG__;
  if (!config) return "";
  const org = config.org || "default";
  const user = config.user_id || (config.token ? "jwt" : "anon");
  return `embed:${org}:${user}:`;
}

function isEmbedMode(): boolean {
  return !!(window as any).__WIII_EMBED__;
}

function namespacedStoreName(name: string): string {
  if (!isEmbedMode()) return name;
  return getEmbedPrefix() + name;
}

async function getStoreClass() {
  if (tauriAvailable === false) return null;
  if (Store && tauriAvailable) return Store;
  try {
    const mod = await import("@tauri-apps/plugin-store");
    // Verify Tauri runtime is actually available (not just the module)
    if (typeof window === "undefined" || !("__TAURI_INTERNALS__" in window)) {
      tauriAvailable = false;
      return null;
    }
    Store = mod.Store;
    tauriAvailable = true;
    return Store;
  } catch {
    tauriAvailable = false;
    return null;
  }
}

// In-memory fallback for browser dev mode
const memoryStore = new Map<string, Map<string, unknown>>();

function getMemoryStore(name: string): Map<string, unknown> {
  if (!memoryStore.has(name)) {
    // Try to hydrate from localStorage
    const map = new Map<string, unknown>();
    try {
      const raw = localStorage.getItem(`wiii:${name}`);
      if (raw) {
        const parsed = JSON.parse(raw);
        for (const [k, v] of Object.entries(parsed)) {
          map.set(k, v);
        }
      }
    } catch {
      // ignore
    }
    memoryStore.set(name, map);
  }
  return memoryStore.get(name)!;
}

function persistMemoryStore(name: string) {
  const map = getMemoryStore(name);
  const obj: Record<string, unknown> = {};
  for (const [k, v] of map.entries()) {
    obj[k] = v;
  }
  try {
    localStorage.setItem(`wiii:${name}`, JSON.stringify(obj));
  } catch {
    // localStorage full or unavailable
  }
}

function persistMemoryStoreStrict(name: string) {
  const map = getMemoryStore(name);
  const obj: Record<string, unknown> = {};
  for (const [k, v] of map.entries()) {
    obj[k] = v;
  }
  localStorage.setItem(`wiii:${name}`, JSON.stringify(obj));
}

export async function loadStore<T>(
  storeName: string,
  key: string,
  defaultValue: T
): Promise<T> {
  const effectiveName = namespacedStoreName(storeName);
  const StoreClass = await getStoreClass();

  if (StoreClass) {
    try {
      const store = await StoreClass.load(effectiveName);
      const value = (await store.get(key)) as T | undefined;
      return value ?? defaultValue;
    } catch (err) {
      console.warn(`[storage] Failed to load ${effectiveName}/${key}:`, err);
      return defaultValue;
    }
  }

  // Fallback: memory + localStorage
  const map = getMemoryStore(effectiveName);
  return (map.get(key) as T) ?? defaultValue;
}

/** Read authoritative state without converting I/O or parse failures to absence. */
export async function loadStoreStrict<T>(
  storeName: string,
  key: string,
  defaultValue: T,
): Promise<T> {
  const effectiveName = namespacedStoreName(storeName);
  const StoreClass = await getStoreClass();

  if (StoreClass) {
    const store = await StoreClass.load(effectiveName);
    const value = (await store.get(key)) as T | undefined;
    return value ?? defaultValue;
  }

  // localStorage is the durable browser authority. Refresh the memory mirror
  // only after a successful read/parse so transient failures cannot look like
  // a missing key and later overwrite existing data.
  const raw = localStorage.getItem(`wiii:${effectiveName}`);
  const parsed = raw ? JSON.parse(raw) as Record<string, unknown> : {};
  const map = new Map<string, unknown>(Object.entries(parsed));
  memoryStore.set(effectiveName, map);
  return (map.get(key) as T) ?? defaultValue;
}

export async function saveStore<T>(
  storeName: string,
  key: string,
  value: T
): Promise<void> {
  const effectiveName = namespacedStoreName(storeName);
  const StoreClass = await getStoreClass();

  if (StoreClass) {
    try {
      const store = await StoreClass.load(effectiveName);
      await store.set(key, value);
      await store.save();
      return;
    } catch (err) {
      console.warn(`[storage] Failed to save ${effectiveName}/${key}:`, err);
    }
  }

  // Fallback
  const map = getMemoryStore(effectiveName);
  map.set(key, value);
  persistMemoryStore(effectiveName);
}

/**
 * Persist without a best-effort fallback. Use this as a durability barrier
 * before an external runtime may observe state. A Tauri store failure is not
 * equivalent to a successful in-memory write, so it is deliberately exposed
 * to the caller.
 */
export async function saveStoreStrict<T>(
  storeName: string,
  key: string,
  value: T
): Promise<void> {
  const effectiveName = namespacedStoreName(storeName);
  const StoreClass = await getStoreClass();

  if (StoreClass) {
    const store = await StoreClass.load(effectiveName);
    const previous = await store.get(key);
    const hadPrevious = previous !== undefined;
    await store.set(key, value);
    try {
      await store.save();
    } catch (error) {
      // plugin-store keeps staged values in memory. Restore that staging area
      // so a later successful save cannot accidentally persist a fact whose
      // durability barrier already failed.
      let compensationError: unknown;
      try {
        if (hadPrevious) await store.set(key, previous);
        else await store.delete(key);
        await store.save();
      } catch (rollbackError) {
        compensationError = rollbackError;
      }
      if (compensationError) {
        throw new AggregateError(
          [error, compensationError],
          `Không thể lưu hoặc hoàn tác ${effectiveName}/${key}.`,
        );
      }
      throw error;
    }
    return;
  }

  const map = getMemoryStore(effectiveName);
  const hadPrevious = map.has(key);
  const previous = map.get(key);
  map.set(key, value);
  try {
    persistMemoryStoreStrict(effectiveName);
  } catch (error) {
    if (hadPrevious) map.set(key, previous);
    else map.delete(key);
    throw error;
  }
}

export async function deleteStore(
  storeName: string,
  key: string
): Promise<void> {
  const effectiveName = namespacedStoreName(storeName);
  const StoreClass = await getStoreClass();

  if (StoreClass) {
    try {
      const store = await StoreClass.load(effectiveName);
      await store.delete(key);
      await store.save();
      return;
    } catch (err) {
      console.warn(`[storage] Failed to delete ${effectiveName}/${key}:`, err);
    }
  }

  const map = getMemoryStore(effectiveName);
  map.delete(key);
  persistMemoryStore(effectiveName);
}

/** Delete a durable key or reject while restoring any staged prior value. */
export async function deleteStoreStrict(
  storeName: string,
  key: string,
): Promise<void> {
  const effectiveName = namespacedStoreName(storeName);
  const StoreClass = await getStoreClass();

  if (StoreClass) {
    const store = await StoreClass.load(effectiveName);
    const previous = await store.get(key);
    const hadPrevious = previous !== undefined;
    await store.delete(key);
    try {
      await store.save();
    } catch (error) {
      if (!hadPrevious) throw error;
      let compensationError: unknown;
      try {
        await store.set(key, previous);
        await store.save();
      } catch (rollbackError) {
        compensationError = rollbackError;
      }
      if (compensationError) {
        throw new AggregateError(
          [error, compensationError],
          `Không thể xóa hoặc hoàn tác ${effectiveName}/${key}.`,
        );
      }
      throw error;
    }
    return;
  }

  const map = getMemoryStore(effectiveName);
  const hadPrevious = map.has(key);
  const previous = map.get(key);
  map.delete(key);
  try {
    persistMemoryStoreStrict(effectiveName);
  } catch (error) {
    if (hadPrevious) map.set(key, previous);
    throw error;
  }
}

export async function clearStore(storeName: string): Promise<void> {
  const effectiveName = namespacedStoreName(storeName);
  const StoreClass = await getStoreClass();

  if (StoreClass) {
    try {
      const store = await StoreClass.load(effectiveName);
      await store.clear();
      await store.save();
      return;
    } catch (err) {
      console.warn(`[storage] Failed to clear ${effectiveName}:`, err);
    }
  }

  memoryStore.delete(effectiveName);
  try {
    localStorage.removeItem(`wiii:${effectiveName}`);
  } catch {
    // ignore
  }
}
