import { listProviderDefinitions } from "@/neko/provider-registry";
import type { NekoProviderAuthOwner } from "@/neko/contracts";
import type {
  WorkbenchHost,
  WorkbenchHostCapability,
} from "./host";

export type CapabilityKind = "runtime" | "knowledge" | "account";
export type CapabilityLocation = "local" | "remote";
export type CapabilityAuthOwner =
  | "runtime"
  | "wiii"
  | "api-credential"
  | "none";

export interface CapabilityDefinition {
  id: string;
  label: string;
  kind: CapabilityKind;
  location: CapabilityLocation;
  authOwner: CapabilityAuthOwner;
  hostRequirements: WorkbenchHostCapability[];
  description?: string;
}

export interface CapabilityAvailability {
  definition: CapabilityDefinition;
  available: boolean;
  missingRequirement?: WorkbenchHostCapability;
  reason?: string;
}

const PROVIDER_AUTH_OWNER: Record<NekoProviderAuthOwner, CapabilityAuthOwner> = {
  provider: "runtime",
  wiii: "wiii",
  "user-credential": "api-credential",
  none: "none",
};

const LOCAL_RUNTIME_DEFINITIONS: CapabilityDefinition[] = listProviderDefinitions().map(
  (provider) => ({
    id: provider.capabilityId,
    label: provider.name,
    kind: "runtime",
    location: "local",
    authOwner: PROVIDER_AUTH_OWNER[provider.authOwner],
    hostRequirements: ["localProcess", "localWorkspace"],
    description: provider.description,
  }),
);

export const RUNTIME_DEFINITIONS: CapabilityDefinition[] = [
  ...LOCAL_RUNTIME_DEFINITIONS,
  {
    id: "wiii-service",
    label: "Wiii Service",
    kind: "runtime",
    location: "remote",
    authOwner: "wiii",
    hostRequirements: ["remoteRuntime"],
    description: "Agent được quản lý, đồng bộ và các năng lực tổ chức của Wiii.",
  },
  {
    id: "claude-api",
    label: "Claude",
    kind: "runtime",
    location: "remote",
    authOwner: "api-credential",
    hostRequirements: ["remoteRuntime"],
    description: "Kết nối API hoặc cloud provider được Anthropic hỗ trợ.",
  },
];

export const KNOWLEDGE_DEFINITIONS: CapabilityDefinition[] = [
  {
    id: "project-files",
    label: "Tệp dự án",
    kind: "knowledge",
    location: "local",
    authOwner: "none",
    hostRequirements: ["localWorkspace"],
    description: "Tệp trong workspace người dùng đã chọn.",
  },
  {
    id: "wiii-knowledge",
    label: "Wiii Knowledge",
    kind: "knowledge",
    location: "remote",
    authOwner: "wiii",
    hostRequirements: ["remoteRuntime"],
    description: "RAG, citations và memory có phạm vi tài khoản hoặc tổ chức.",
  },
];

const REQUIREMENT_REASON: Record<WorkbenchHostCapability, string> = {
  localProcess: "Trình duyệt không thể chạy agent cục bộ; hãy dùng ứng dụng desktop.",
  localWorkspace: "Chỉ dùng được với workspace trên ứng dụng desktop.",
  nativeWindow: "Điều khiển cửa sổ chỉ có trên ứng dụng desktop.",
  tray: "Khay hệ thống chỉ có trên ứng dụng desktop.",
  secureSecretStore: "Máy này chưa có kho bí mật native được Wiii hỗ trợ.",
  remoteRuntime: "Host hiện tại không cho phép kết nối runtime từ xa.",
};

export function evaluateCapabilityAvailability(
  definition: CapabilityDefinition,
  host: WorkbenchHost,
): CapabilityAvailability {
  const missingRequirement = definition.hostRequirements.find(
    (requirement) => !host.capabilities[requirement],
  );
  if (!missingRequirement) return { definition, available: true };
  return {
    definition,
    available: false,
    missingRequirement,
    reason: REQUIREMENT_REASON[missingRequirement],
  };
}
