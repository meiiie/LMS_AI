import { afterAll, beforeEach, describe, expect, it, vi } from "vitest";
import {
  clearStore,
  deleteStoreStrict,
  loadStore,
  loadStoreStrict,
  saveStoreStrict,
} from "@/lib/storage";

const STORE = "storage-strict-test.json";
const browserStorage = new Map<string, string>();
let failWrites = false;
let failReads = false;

const localStorageStub: Storage = {
  get length() { return browserStorage.size; },
  clear: () => browserStorage.clear(),
  getItem: (key) => {
    if (failReads) throw new DOMException("read unavailable", "InvalidStateError");
    return browserStorage.get(key) ?? null;
  },
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
    failReads = false;
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

  it("propagates authoritative browser read failures", async () => {
    await saveStoreStrict(STORE, "fact", "before");
    failReads = true;

    await expect(loadStoreStrict(STORE, "fact", null)).rejects.toThrow("read unavailable");
  });

  it("restores a browser value when strict deletion cannot persist", async () => {
    await saveStoreStrict(STORE, "fact", "before");
    failWrites = true;

    await expect(deleteStoreStrict(STORE, "fact")).rejects.toThrow("quota exceeded");
    failWrites = false;
    await expect(loadStoreStrict(STORE, "fact", null)).resolves.toBe("before");
  });
});
