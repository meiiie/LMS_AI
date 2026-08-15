import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { WorkbenchHost } from "@/workbench/host";

const storage = new Map<string, unknown>();
const managedMount = vi.fn();

vi.mock("@/lib/storage", () => ({
  loadStore: vi.fn(async (store: string, key: string, fallback: unknown) =>
    storage.has(`${store}:${key}`) ? storage.get(`${store}:${key}`) : fallback,
  ),
  saveStore: vi.fn(async (store: string, key: string, value: unknown) => {
    storage.set(`${store}:${key}`, value);
  }),
}));

import { WorkbenchApp } from "@/workbench/WorkbenchApp";
import { useWorkbenchStore } from "@/workbench/workbench-store";

const desktop: WorkbenchHost = {
  kind: "desktop",
  capabilities: {
    localProcess: true,
    localWorkspace: true,
    nativeWindow: true,
    tray: true,
    secureSecretStore: false,
    remoteRuntime: true,
  },
};

const web: WorkbenchHost = {
  kind: "web",
  capabilities: {
    ...desktop.capabilities,
    localProcess: false,
    localWorkspace: false,
    nativeWindow: false,
    tray: false,
  },
};

function Managed({ openLocal }: { openLocal: () => void }) {
  managedMount();
  return <button onClick={openLocal}>managed</button>;
}

describe("WorkbenchApp bootstrap", () => {
  beforeEach(() => {
    storage.clear();
    managedMount.mockClear();
    useWorkbenchStore.setState({ surface: "local", isLoaded: false });
  });

  afterEach(() => cleanup());

  it("mounts local desktop first and does not initialize managed services", async () => {
    render(
      <WorkbenchApp
        host={desktop}
        renderLocal={({ openManaged }) => <button onClick={openManaged}>local</button>}
        renderManaged={({ openLocal }) => <Managed openLocal={openLocal} />}
      />,
    );

    await waitFor(() => expect(screen.getByRole("button", { name: "local" })).toBeTruthy());
    expect(managedMount).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "local" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "managed" })).toBeTruthy());
    expect(managedMount).toHaveBeenCalledTimes(1);
  });

  it("uses managed surface on hosted web and cannot navigate into local authority", async () => {
    render(
      <WorkbenchApp
        host={web}
        renderLocal={() => <div>local authority</div>}
        renderManaged={({ openLocal }) => <Managed openLocal={openLocal} />}
      />,
    );

    await waitFor(() => expect(screen.getByRole("button", { name: "managed" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "managed" }));
    expect(screen.queryByText("local authority")).toBeNull();
  });
});
