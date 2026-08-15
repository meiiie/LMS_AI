export type ProviderIntegrationId =
  | "neko-core"
  | "gemini-cli"
  | "codex"
  | "wiii-service"
  | "claude-api"
  | "claude-subscription";

export interface ProviderIntegrationPolicy {
  id: ProviderIntegrationId;
  label: string;
  enabled: boolean;
  authOwner: "runtime" | "wiii" | "api-credential";
  billingOwner: "provider-account" | "wiii-deployment" | "api-credential";
  credentialStorage: "provider" | "server" | "none";
  explanation: string;
}

export const PROVIDER_INTEGRATION_POLICIES: ProviderIntegrationPolicy[] = [
  {
    id: "neko-core",
    label: "Neko Core",
    enabled: true,
    authOwner: "runtime",
    billingOwner: "provider-account",
    credentialStorage: "provider",
    explanation: "Neko Core sở hữu profile, model và thông tin nhà cung cấp.",
  },
  {
    id: "gemini-cli",
    label: "Gemini CLI",
    enabled: true,
    authOwner: "runtime",
    billingOwner: "provider-account",
    credentialStorage: "provider",
    explanation: "Gemini CLI sở hữu tài khoản; Wiii chỉ kết nối qua ACP.",
  },
  {
    id: "codex",
    label: "Codex",
    enabled: true,
    authOwner: "runtime",
    billingOwner: "provider-account",
    credentialStorage: "provider",
    explanation: "Codex App Server sở hữu login, token, model và thread.",
  },
  {
    id: "wiii-service",
    label: "Wiii Service",
    enabled: true,
    authOwner: "wiii",
    billingOwner: "wiii-deployment",
    credentialStorage: "server",
    explanation: "Tài khoản Wiii cấp RAG, memory, đồng bộ và runtime được quản lý.",
  },
  {
    id: "claude-api",
    label: "Claude API / cloud provider",
    enabled: true,
    authOwner: "api-credential",
    billingOwner: "api-credential",
    credentialStorage: "server",
    explanation: "Chỉ bật qua API hoặc nhà cung cấp cloud được Anthropic hỗ trợ; khóa nằm phía server.",
  },
  {
    id: "claude-subscription",
    label: "Claude subscription login",
    enabled: false,
    authOwner: "runtime",
    billingOwner: "provider-account",
    credentialStorage: "none",
    explanation: "Không cung cấp đăng nhập thuê bao Claude trong ứng dụng bên thứ ba khi chưa có chấp thuận chính thức.",
  },
];

export function providerIntegrationPolicy(
  id: ProviderIntegrationId,
): ProviderIntegrationPolicy {
  const policy = PROVIDER_INTEGRATION_POLICIES.find((candidate) => candidate.id === id);
  if (!policy) throw new Error(`Unknown provider integration policy: ${id}`);
  return policy;
}
