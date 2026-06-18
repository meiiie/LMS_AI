import { describe, expect, it } from "vitest";
import { readOAuthCallbackParams } from "@/App";

describe("App OAuth callback hash parser", () => {
  it("accepts Google callback hashes containing both access and refresh tokens", () => {
    const params = readOAuthCallbackParams(
      "#access_token=access-123&refresh_token=refresh-456&expires_in=900",
    );

    expect(params?.get("access_token")).toBe("access-123");
    expect(params?.get("refresh_token")).toBe("refresh-456");
  });

  it("ignores non-auth hashes and partial callbacks", () => {
    expect(readOAuthCallbackParams("#preview=pointy")).toBeNull();
    expect(readOAuthCallbackParams("#access_token=access-only")).toBeNull();
    expect(readOAuthCallbackParams("")).toBeNull();
  });
});
