import { describe, expect, it } from "vitest";
import {
  KNOWLEDGE_DEFINITIONS,
  RUNTIME_DEFINITIONS,
  evaluateCapabilityAvailability,
  type CapabilityDefinition,
} from "@/workbench/capabilities";
import { resolveWorkbenchHost } from "@/workbench/host";

describe("Workbench capability catalog", () => {
  const desktop = resolveWorkbenchHost({ tauri: true });
  const web = resolveWorkbenchHost({ tauri: false });

  it("offers local and remote runtimes on desktop", () => {
    const states = RUNTIME_DEFINITIONS.map((definition) =>
      evaluateCapabilityAvailability(definition, desktop),
    );

    expect(states.find((item) => item.definition.id === "neko-core")?.available).toBe(true);
    expect(states.find((item) => item.definition.id === "codex")?.available).toBe(true);
    expect(states.find((item) => item.definition.id === "wiii-service")?.available).toBe(true);
  });

  it("blocks every local runtime and local knowledge source on hosted web", () => {
    for (const definition of [...RUNTIME_DEFINITIONS, ...KNOWLEDGE_DEFINITIONS]) {
      const result = evaluateCapabilityAvailability(definition, web);
      if (definition.location === "local") {
        expect(result.available, definition.id).toBe(false);
        expect(result.reason).toMatch(/trình duyệt|máy này|desktop/i);
      }
    }
  });

  it("explains the first missing host requirement", () => {
    const definition: CapabilityDefinition = {
      id: "native-test",
      label: "Native test",
      kind: "runtime",
      location: "local",
      authOwner: "none",
      hostRequirements: ["localWorkspace", "localProcess"],
    };

    expect(evaluateCapabilityAvailability(definition, web)).toEqual({
      definition,
      available: false,
      missingRequirement: "localWorkspace",
      reason: "Chỉ dùng được với workspace trên ứng dụng desktop.",
    });
  });

  it("keeps account ownership independent from location", () => {
    expect(RUNTIME_DEFINITIONS.find((item) => item.id === "codex")?.authOwner).toBe("runtime");
    expect(RUNTIME_DEFINITIONS.find((item) => item.id === "wiii-service")?.authOwner).toBe("wiii");
    expect(RUNTIME_DEFINITIONS.find((item) => item.id === "claude-api")?.authOwner).toBe("api-credential");
  });
});
