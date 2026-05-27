import { getClient } from "./client";
import type { WiiiConnectProviderRegistryResponse } from "./types";

export async function fetchWiiiConnectProviders(): Promise<WiiiConnectProviderRegistryResponse> {
  return getClient().get<WiiiConnectProviderRegistryResponse>("/api/v1/wiii-connect/providers");
}
