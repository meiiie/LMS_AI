import { afterAll, beforeEach, describe, expect, it, vi } from "vitest";

const values = new Map<string, unknown>();
let failNextSave = false;
let failEverySave = false;

const store = {
  get: vi.fn(async (key: string) => values.get(key)),
  set: vi.fn(async (key: string, value: unknown) => { values.set(key, value); }),
  delete: vi.fn(async (key: string) => { values.delete(key); }),
  save: vi.fn(async () => {
    if (failEverySave) throw new Error("desktop disk unavailable");
    if (failNextSave) {
      failNextSave = false;
      throw new Error("desktop disk unavailable");
    }
  }),
};

vi.mock("@tauri-apps/plugin-store", () => ({
  Store: { load: vi.fn(async () => store) },
}));

import { saveStoreStrict } from "@/lib/storage";

describe("saveStoreStrict in Tauri", () => {
  beforeEach(() => {
    values.clear();
    failNextSave = false;
    failEverySave = false;
    vi.clearAllMocks();
    Object.defineProperty(window, "__TAURI_INTERNALS__", {
      configurable: true,
      value: {},
    });
  });

  afterAll(() => {
    Reflect.deleteProperty(window, "__TAURI_INTERNALS__");
  });

  it("removes a newly staged value when desktop persistence rejects", async () => {
    failNextSave = true;

    await expect(saveStoreStrict("strict.json", "fact", "new"))
      .rejects.toThrow("desktop disk unavailable");

    expect(values.has("fact")).toBe(false);
    expect(store.delete).toHaveBeenCalledWith("fact");
  });

  it("restores the previous staged value when desktop persistence rejects", async () => {
    values.set("fact", "before");
    failNextSave = true;

    await expect(saveStoreStrict("strict.json", "fact", "after"))
      .rejects.toThrow("desktop disk unavailable");

    expect(values.get("fact")).toBe("before");
    expect(store.set).toHaveBeenLastCalledWith("fact", "before");
  });

  it("reports the save and compensation failures together", async () => {
    values.set("fact", "before");
    failEverySave = true;

    const failure = await saveStoreStrict("strict.json", "fact", "after").then(
      () => null,
      (error: unknown) => error,
    );

    expect(failure).toBeInstanceOf(AggregateError);
    expect((failure as AggregateError).errors).toEqual([
      expect.objectContaining({ message: "desktop disk unavailable" }),
      expect.objectContaining({ message: "desktop disk unavailable" }),
    ]);
  });
});
