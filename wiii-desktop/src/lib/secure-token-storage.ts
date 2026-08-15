/**
 * Sprint 176: Secure token storage — separates auth tokens from general settings.
 *
 * Tokens are stored in a dedicated "wiii_auth_tokens" store, separate from
 * the general auth_state store. This isolation:
 * - Prevents accidental token exposure in settings exports
 * - Enables future upgrade to OS keyring (tauri-plugin-keyring) when stable
 * - Makes token lifecycle management cleaner
 */
import { loadStore, saveStore, deleteStore } from "@/lib/storage";

const TOKEN_STORE_NAME = "wiii_auth_tokens";
const TOKEN_KEY = "tokens";

export interface SecureTokens {
  access_token: string;
  refresh_token: string;
  expires_at: number; // Unix timestamp (ms)
}

export async function storeTokens(
  accessToken: string,
  refreshToken: string,
  expiresAt: number,
): Promise<void> {
  const tokens: SecureTokens = {
    access_token: accessToken,
    refresh_token: refreshToken,
    expires_at: expiresAt,
  };
  await saveStore(TOKEN_STORE_NAME, TOKEN_KEY, tokens);
}

export async function loadTokens(): Promise<SecureTokens | null> {
  const tokens = await loadStore<SecureTokens | null>(
    TOKEN_STORE_NAME,
    TOKEN_KEY,
    null,
  );
  return tokens;
}

export async function clearTokens(): Promise<void> {
  await deleteStore(TOKEN_STORE_NAME, TOKEN_KEY);
}

// =============================================================================
// Sprint 192: Secure API Key Storage
// =============================================================================
const API_KEY_KEY = "api_key";
const GEMINI_API_KEY_KEY = "gemini_api_key";
const OPENAI_API_KEY_KEY = "openai_api_key";
const OPENROUTER_API_KEY_KEY = "openrouter_api_key";
const NVIDIA_API_KEY_KEY = "nvidia_api_key";
const ZHIPU_API_KEY_KEY = "zhipu_api_key";
const OLLAMA_API_KEY_KEY = "ollama_api_key";

export async function storeApiKey(apiKey: string): Promise<void> {
  await saveStore(TOKEN_STORE_NAME, API_KEY_KEY, apiKey);
}

export async function loadApiKey(): Promise<string | null> {
  const key = await loadStore<string | null>(TOKEN_STORE_NAME, API_KEY_KEY, null);
  return key;
}

export async function clearApiKey(): Promise<void> {
  await deleteStore(TOKEN_STORE_NAME, API_KEY_KEY);
}

export async function storeGeminiApiKey(apiKey: string): Promise<void> {
  await saveStore(TOKEN_STORE_NAME, GEMINI_API_KEY_KEY, apiKey);
}

export async function loadGeminiApiKey(): Promise<string | null> {
  return loadStore<string | null>(TOKEN_STORE_NAME, GEMINI_API_KEY_KEY, null);
}

export async function clearGeminiApiKey(): Promise<void> {
  await deleteStore(TOKEN_STORE_NAME, GEMINI_API_KEY_KEY);
}

export async function storeOpenAiApiKey(apiKey: string): Promise<void> {
  await saveStore(TOKEN_STORE_NAME, OPENAI_API_KEY_KEY, apiKey);
}

export async function loadOpenAiApiKey(): Promise<string | null> {
  return loadStore<string | null>(TOKEN_STORE_NAME, OPENAI_API_KEY_KEY, null);
}

export async function clearOpenAiApiKey(): Promise<void> {
  await deleteStore(TOKEN_STORE_NAME, OPENAI_API_KEY_KEY);
}

export async function storeOpenRouterApiKey(apiKey: string): Promise<void> {
  await saveStore(TOKEN_STORE_NAME, OPENROUTER_API_KEY_KEY, apiKey);
}

export async function loadOpenRouterApiKey(): Promise<string | null> {
  return loadStore<string | null>(TOKEN_STORE_NAME, OPENROUTER_API_KEY_KEY, null);
}

export async function clearOpenRouterApiKey(): Promise<void> {
  await deleteStore(TOKEN_STORE_NAME, OPENROUTER_API_KEY_KEY);
}

export async function storeNvidiaApiKey(apiKey: string): Promise<void> {
  await saveStore(TOKEN_STORE_NAME, NVIDIA_API_KEY_KEY, apiKey);
}

export async function loadNvidiaApiKey(): Promise<string | null> {
  return loadStore<string | null>(TOKEN_STORE_NAME, NVIDIA_API_KEY_KEY, null);
}

export async function clearNvidiaApiKey(): Promise<void> {
  await deleteStore(TOKEN_STORE_NAME, NVIDIA_API_KEY_KEY);
}

export async function storeZhipuApiKey(apiKey: string): Promise<void> {
  await saveStore(TOKEN_STORE_NAME, ZHIPU_API_KEY_KEY, apiKey);
}

export async function loadZhipuApiKey(): Promise<string | null> {
  return loadStore<string | null>(TOKEN_STORE_NAME, ZHIPU_API_KEY_KEY, null);
}

export async function clearZhipuApiKey(): Promise<void> {
  await deleteStore(TOKEN_STORE_NAME, ZHIPU_API_KEY_KEY);
}

export async function storeOllamaApiKey(apiKey: string): Promise<void> {
  await saveStore(TOKEN_STORE_NAME, OLLAMA_API_KEY_KEY, apiKey);
}

export async function loadOllamaApiKey(): Promise<string | null> {
  return loadStore<string | null>(TOKEN_STORE_NAME, OLLAMA_API_KEY_KEY, null);
}

export async function clearOllamaApiKey(): Promise<void> {
  await deleteStore(TOKEN_STORE_NAME, OLLAMA_API_KEY_KEY);
}

// =============================================================================
// Sprint 194b (H5): Secure Facebook Cookie Storage
// Moved from settings-store (plaintext localStorage) to secure token storage
// to prevent PII exposure via XSS attacks.
// =============================================================================
const FB_COOKIE_KEY = "facebook_cookie";

export async function storeFacebookCookie(cookie: string): Promise<void> {
  await saveStore(TOKEN_STORE_NAME, FB_COOKIE_KEY, cookie);
}

export async function loadFacebookCookie(): Promise<string | null> {
  const cookie = await loadStore<string | null>(TOKEN_STORE_NAME, FB_COOKIE_KEY, null);
  return cookie;
}

export async function clearFacebookCookie(): Promise<void> {
  await deleteStore(TOKEN_STORE_NAME, FB_COOKIE_KEY);
}
