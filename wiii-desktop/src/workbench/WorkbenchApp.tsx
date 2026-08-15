import { useEffect, type ReactNode } from "react";
import type { WorkbenchHost } from "./host";
import { useWorkbenchStore } from "./workbench-store";

export interface WorkbenchNavigation {
  openLocal: () => void;
  openManaged: () => void;
}

interface WorkbenchAppProps {
  host: WorkbenchHost;
  renderLocal: (navigation: WorkbenchNavigation) => ReactNode;
  renderManaged: (navigation: WorkbenchNavigation) => ReactNode;
  loadingFallback?: ReactNode;
}

/**
 * Mount boundary for the two Workbench surfaces.
 *
 * Keeping the inactive surface unmounted is intentional: opening a local
 * workspace must not silently initialize cloud auth, RAG, or remote agents.
 */
export function WorkbenchApp({
  host,
  renderLocal,
  renderManaged,
  loadingFallback,
}: WorkbenchAppProps) {
  const surface = useWorkbenchStore((state) => state.surface);
  const isLoaded = useWorkbenchStore((state) => state.isLoaded);
  const load = useWorkbenchStore((state) => state.load);
  const setSurface = useWorkbenchStore((state) => state.setSurface);

  useEffect(() => {
    void load(host);
  }, [host, load]);

  if (!isLoaded) {
    return (
      loadingFallback ?? (
        <div className="flex min-h-screen items-center justify-center bg-background text-sm text-muted-foreground" role="status">
          Đang mở Wiii Workbench…
        </div>
      )
    );
  }

  const navigation: WorkbenchNavigation = {
    openLocal: () => {
      void setSurface("local", host);
    },
    openManaged: () => {
      void setSurface("managed", host);
    },
  };

  const canUseLocal =
    host.capabilities.localProcess && host.capabilities.localWorkspace;
  return surface === "local" && canUseLocal
    ? renderLocal(navigation)
    : renderManaged(navigation);
}
