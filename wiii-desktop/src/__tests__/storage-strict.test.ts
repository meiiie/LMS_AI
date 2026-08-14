import { afterAll, beforeEach, describe, expect, it, vi } from "vitest";
import { clearStore, loadStore, saveStoreStrict } from "@/lib/storage";

const STORE = "storage-strict-test.json";
const browserStorage = new Map<string, string>();
let failWrites = false;

const localStorageStub: Storage = {
  get length() { return browserStorage.size; },
  clear: () => browserStorage.clear(),
  getItem: (key) => browserStorage.get(key) ?? null,
  key: (index) => [...browserStorage.keys()][index] ?? null,
  removeItem: (key) => { browserStorage.delete(key); },
  setItem: (key, value) => {
    if (failWrites) throw new DOMException("quota exceeded", "QuotaExceededError");
    browserStorage.set(key, value);
  },
};

describe("saveStoreStrict", () => {
  beforeEach(async () => {
    vi.restoreAllMocks();
    vi.stubGlobal("localStorage", localStorageStub);
    failWrites = false;
    await clearStore(STORE);
  });

  afterAll(() => vi.unstubAllGlobals());

  it("persists normally in the browser fallback", async () => {
    await saveStoreStrict(STORE, "fact", { value: "durable" });

    await expect(loadStore(STORE, "fact", null)).resolves.toEqual({ value: "durable" });
  });

  it("propagates storage failure and restores the prior in-memory value", async () => {
    await saveStoreStrict(STORE, "fact", "before");
    failWrites = true;

    await expect(saveStoreStrict(STORE, "fact", "after")).rejects.toThrow("quota exceeded");
    failWrites = false;

    await expect(loadStore(STORE, "fact", null)).resolves.toBe("before");
  });
});
