import { describe, expect, it, vi } from "vitest";
import { codexBootstrapIdentity } from "@/neko-chill/codex-bootstrap-identity";

describe("Codex account bootstrap identity", () => {
  it("reuses one caller identity across uncertain retries", () => {
    const createId = vi.fn()
      .mockReturnValueOnce("first")
      .mockReturnValueOnce("second");
    const first = codexBootstrapIdentity(null, "C:/workspace", createId);
    const retry = codexBootstrapIdentity(first, "C:/workspace", createId);

    expect(retry).toBe(first);
    expect(retry.clientSessionId).toBe("codex-account-bootstrap-first");
    expect(createId).toHaveBeenCalledTimes(1);
  });

  it("mints a different caller scope for a different workspace", () => {
    const createId = vi.fn()
      .mockReturnValueOnce("first")
      .mockReturnValueOnce("second");
    const first = codexBootstrapIdentity(null, "C:/workspace-a", createId);
    const next = codexBootstrapIdentity(first, "C:/workspace-b", createId);

    expect(next.clientSessionId).toBe("codex-account-bootstrap-second");
    expect(createId).toHaveBeenCalledTimes(2);
  });
});
