/**
 * Shared DOM refresh hook for Pointy action paths.
 *
 * React/Tauri UI can re-render between the moment Wiii decides on a target
 * and the moment Pointy actually resolves it. Keep action-time selector
 * resolution honest by letting the mounted integration force a fresh scan.
 */

export type PointyDomRefreshHook = () => void;

type PointyRefreshWindow = Window & {
  __wiiiPointyRefreshContext__?: PointyDomRefreshHook;
};

function pointyWindow(): PointyRefreshWindow | null {
  return typeof window !== "undefined" ? (window as PointyRefreshWindow) : null;
}

export function setPointyDomRefreshHook(hook: PointyDomRefreshHook): void {
  const win = pointyWindow();
  if (!win) return;
  win.__wiiiPointyRefreshContext__ = hook;
}

export function clearPointyDomRefreshHook(hook?: PointyDomRefreshHook): void {
  const win = pointyWindow();
  if (!win) return;
  if (!hook || win.__wiiiPointyRefreshContext__ === hook) {
    delete win.__wiiiPointyRefreshContext__;
  }
}

export function refreshDomBeforePointyAction(source: string): void {
  const win = pointyWindow();
  const hook = win?.__wiiiPointyRefreshContext__;
  if (!hook) return;
  try {
    hook();
  } catch (err) {
    console.warn(
      `[POINTY] pre-action DOM refresh failed (${source}):`,
      err instanceof Error ? err.message : String(err),
    );
  }
}
