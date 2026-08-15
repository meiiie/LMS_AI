import { describe, expect, it } from "vitest";
import {
  providerIntegrationPolicy,
  PROVIDER_INTEGRATION_POLICIES,
} from "@/workbench/provider-policy";

describe("provider auth and billing ownership", () => {
  it("keeps Codex credentials inside the provider runtime", () => {
    expect(providerIntegrationPolicy("codex")).toEqual(expect.objectContaining({
      enabled: true,
      authOwner: "runtime",
      credentialStorage: "provider",
    }));
  });

  it("permits Claude only through an API-safe server path", () => {
    expect(providerIntegrationPolicy("claude-api")).toEqual(expect.objectContaining({
      enabled: true,
      authOwner: "api-credential",
      credentialStorage: "server",
    }));
  });

  it("fails closed for third-party Claude subscription login", () => {
    expect(providerIntegrationPolicy("claude-subscription")).toEqual(expect.objectContaining({
      enabled: false,
      credentialStorage: "none",
    }));
  });

  it("defines ownership for every advertised provider path", () => {
    expect(new Set(PROVIDER_INTEGRATION_POLICIES.map((item) => item.id)).size)
      .toBe(PROVIDER_INTEGRATION_POLICIES.length);
  });
});
