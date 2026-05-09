import { describe, expect, it } from "vitest";
import { normalizeLoadedSettingsForHost } from "@/stores/settings-store";
import { resolveDevModeSettingsPatch } from "@/components/auth/LoginScreen";
import { DEFAULT_SERVER_URL } from "@/lib/constants";

const localPreviewDefault = DEFAULT_SERVER_URL || "http://localhost:8080";

describe("local preview bootstrap", () => {
  it("hydrates blank server_url to localhost backend on local preview", () => {
    const normalized = normalizeLoadedSettingsForHost(
      {
        server_url: "",
        api_key: "local-dev-key",
        user_role: "student",
        user_id: "test-user",
      },
      "127.0.0.1",
    );

    expect(normalized.server_url).toBe(localPreviewDefault);
  });

  it("promotes local-dev-key developer mode to admin on localhost", () => {
    const patch = resolveDevModeSettingsPatch(
      {
        server_url: "",
        api_key: "local-dev-key",
        user_role: "student",
      },
      "127.0.0.1",
    );

    expect(patch.server_url).toBe(localPreviewDefault);
    expect(patch.user_role).toBe("admin");
  });

  it("migrates stale localhost:8001 settings back to localhost:8080 on local preview", () => {
    const normalized = normalizeLoadedSettingsForHost(
      {
        server_url: "http://localhost:8001",
        api_key: "local-dev-key",
        user_role: "student",
        user_id: "test-user",
      },
      "localhost",
    );

    expect(normalized.server_url).toBe(localPreviewDefault);
  });

  it("migrates stale 127.0.0.1:8001 settings back to localhost:8080 on local preview", () => {
    const normalized = normalizeLoadedSettingsForHost(
      {
        server_url: "http://127.0.0.1:8001",
        api_key: "local-dev-key",
        user_role: "student",
        user_id: "test-user",
      },
      "127.0.0.1",
    );

    expect(normalized.server_url).toBe(localPreviewDefault);
  });

  it("migrates stale localhost:8080 proxy settings to the active local preview default", () => {
    const normalized = normalizeLoadedSettingsForHost(
      {
        server_url: "http://localhost:8080",
        api_key: "local-dev-key",
        user_role: "student",
        user_id: "test-user",
      },
      "127.0.0.1",
    );

    expect(normalized.server_url).toBe(localPreviewDefault);
  });

  it("does not override explicit non-local settings", () => {
    const patch = resolveDevModeSettingsPatch(
      {
        server_url: "https://api.example.com",
        api_key: "prod-key",
        user_role: "teacher",
      },
      "wiii.app",
    );

    expect(patch).toEqual({});
  });
});
