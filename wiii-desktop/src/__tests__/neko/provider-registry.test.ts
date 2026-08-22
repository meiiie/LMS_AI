import { describe, expect, it } from "vitest";
import {
  isNekoProviderCapabilitySnapshot,
} from "@/neko/contracts";
import {
  createProviderCapabilitySnapshot,
  listProviderDefinitions,
  requireProviderDefinition,
} from "@/neko/provider-registry";

describe("Neko provider registry", () => {
  it("is the product metadata truth without WebView launch arguments", () => {
    expect(listProviderDefinitions().map((provider) => ({
      id: provider.id,
      capabilityId: provider.capabilityId,
      integration: provider.integration,
      protocol: provider.protocol,
      authOwner: provider.authOwner,
    }))).toEqual([
      {
        id: "neko",
        capabilityId: "neko-core",
        integration: "acp",
        protocol: "acp-v1",
        authOwner: "provider",
      },
      {
        id: "gemini",
        capabilityId: "gemini-cli",
        integration: "acp",
        protocol: "acp-v1",
        authOwner: "provider",
      },
      {
        id: "codex",
        capabilityId: "codex",
        integration: "native-structured",
        protocol: "codex-app-server",
        authOwner: "provider",
      },
    ]);

    for (const provider of listProviderDefinitions()) {
      expect(provider).not.toHaveProperty("launchArgs");
      expect(provider).not.toHaveProperty("profileArgument");
    }
  });

  it("fails closed for an unknown provider", () => {
    expect(() => requireProviderDefinition("unknown")).toThrow(/unknown/i);
  });

  it("creates a versioned, bounded historical capability snapshot", () => {
    const snapshot = createProviderCapabilitySnapshot({
      providerId: "codex",
      providerVersion: "0.149.0",
      established: {
        resume: true,
        modelSelection: true,
        reasoning: true,
        approvals: true,
        toolEvents: true,
        diff: true,
      },
      extensions: { accountType: "chatgpt" },
    });

    expect(snapshot).toEqual(expect.objectContaining({
      v: 1,
      providerId: "codex",
      providerVersion: "0.149.0",
      integration: "native-structured",
      protocol: "codex-app-server",
      capabilities: expect.objectContaining({
        resume: true,
        fork: false,
        modelSelection: true,
        toolEvents: true,
      }),
    }));
    expect(isNekoProviderCapabilitySnapshot(JSON.parse(JSON.stringify(snapshot)))).toBe(true);
  });

  it("normalizes an empty version probe to an unknown version", () => {
    expect(createProviderCapabilitySnapshot({
      providerId: "neko",
      providerVersion: "   ",
    }).providerVersion).toBeNull();
  });

  it("rejects secret-like or unbounded provider extensions", () => {
    expect(() => createProviderCapabilitySnapshot({
      providerId: "codex",
      providerVersion: null,
      extensions: { apiToken: "do-not-store" },
    })).toThrow(/extension/i);

    expect(() => createProviderCapabilitySnapshot({
      providerId: "codex",
      providerVersion: null,
      extensions: { note: "x".repeat(257) },
    })).toThrow(/extension/i);
  });
});
