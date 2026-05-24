import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { VisualRuntimeManifest, VisualShellVariant } from "@/api/types";
import {
  buildVisualFrameDocument,
  frameLabel,
  readHostThemeOverrides,
} from "@/lib/visual-frame-document";
import {
  buildVisualFrameHostSyncMessage,
  clampVisualFrameContentHeight,
  getVisualFrameHeightProfile,
  parseVisualFrameBridgeMessage,
  resolveVisualFrameCssHeight,
  resolveVisualFrameSizingMode,
} from "@/lib/visual-frame-contract";
import type {
  VisualFrameKind,
  VisualFrameSizingMode,
} from "@/lib/visual-frame-contract";

interface InlineVisualFrameProps {
  html: string;
  className?: string;
  title?: string;
  summary?: string;
  sessionId?: string;
  shellVariant?: VisualShellVariant;
  frameKind?: VisualFrameKind;
  sizingMode?: VisualFrameSizingMode;
  runtimeManifest?: VisualRuntimeManifest | null;
  showFrameIntro?: boolean;
  hostShellMode?: "auto" | "force";
  onBridgeEvent?: (detail: Record<string, unknown>) => void;
  /** Whether to show the Tweaks toggle button. Default false. */
  showTweaksToggle?: boolean;
}

export const InlineVisualFrame = memo(function InlineVisualFrame({
  html,
  className = "",
  title = "",
  summary = "",
  sessionId = "",
  shellVariant = "editorial",
  frameKind = "inline_html",
  runtimeManifest,
  showFrameIntro = false,
  hostShellMode = frameKind === "legacy" ? "auto" : "force",
  onBridgeEvent,
  showTweaksToggle = false,
  sizingMode: requestedSizingMode,
}: InlineVisualFrameProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const blobUrlRef = useRef<string | null>(null);
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const sizingMode = useMemo(
    () => resolveVisualFrameSizingMode(frameKind, requestedSizingMode),
    [frameKind, requestedSizingMode],
  );
  const heightProfile = useMemo(
    () => getVisualFrameHeightProfile(frameKind, sizingMode),
    [frameKind, sizingMode],
  );
  const [height, setHeight] = useState(heightProfile.initialHeight);
  const [error, setError] = useState<string | null>(null);
  const [frameReady, setFrameReady] = useState(false);
  const [tweaksAvailable, setTweaksAvailable] = useState(false);
  const [tweaksActive, setTweaksActive] = useState(false);

  // Sprint 35e Item 2 — read host theme once per mount; the host CSS
  // is stable for the lifetime of an iframe, so we don't need to track
  // it reactively. Re-renders triggered by html/title/etc. naturally
  // pick up any newer values via re-read.
  const wrappedHtml = useMemo(
    () =>
      buildVisualFrameDocument(html, {
        title,
        summary,
        sessionId,
        shellVariant,
        frameKind,
        sizingMode,
        showFrameIntro,
        hostShellMode,
        hostThemeOverrides: readHostThemeOverrides(),
      }),
    [
      frameKind,
      hostShellMode,
      html,
      sessionId,
      shellVariant,
      sizingMode,
      showFrameIntro,
      summary,
      title,
    ],
  );

  useEffect(() => {
    if (blobUrlRef.current) URL.revokeObjectURL(blobUrlRef.current);
    try {
      const blob = new Blob([wrappedHtml], { type: "text/html" });
      const url = URL.createObjectURL(blob);
      blobUrlRef.current = url;
      setBlobUrl(url);
      setError(null);
      setFrameReady(false);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Không thể tạo visual frame",
      );
    }
    return () => {
      if (blobUrlRef.current) {
        URL.revokeObjectURL(blobUrlRef.current);
        blobUrlRef.current = null;
      }
    };
  }, [wrappedHtml]);

  useEffect(() => {
    setHeight(heightProfile.initialHeight);
  }, [heightProfile.initialHeight, html, sizingMode]);

  const postHostSync = useCallback(() => {
    const target = iframeRef.current?.contentWindow;
    if (!target) return;
    target.postMessage(
      buildVisualFrameHostSyncMessage({
        sessionId,
        frameKind,
        shellVariant,
        sizingMode,
        runtimeManifest: runtimeManifest || null,
      }),
      "*",
    );
  }, [frameKind, runtimeManifest, sessionId, shellVariant, sizingMode]);

  useEffect(() => {
    const handler = (event: MessageEvent) => {
      if (iframeRef.current && event.source !== iframeRef.current.contentWindow)
        return;
      const message = parseVisualFrameBridgeMessage(event.data);
      if (!message) return;

      // Tweaks protocol: iframe announces edit mode availability
      if (message.kind === "tweaks_available") {
        setTweaksAvailable(true);
        return;
      }

      // Tweaks protocol: collect persisted edits
      if (message.kind === "tweaks_persist") {
        // Fire a bridge event so the host can persist tweaks if desired
        onBridgeEvent?.({ bridgeType: "tweaks_persist", edits: message.edits });
        window.dispatchEvent(
          new CustomEvent("wiii:visual-frame", {
            detail: { bridgeType: "tweaks_persist", edits: message.edits },
          }),
        );
        return;
      }

      if (message.kind === "resize") {
        const nextHeight = clampVisualFrameContentHeight(
          message.height,
          heightProfile,
        );
        if (nextHeight !== null) {
          setHeight(nextHeight);
        }
        return;
      }
      if (message.kind === "ready") {
        setFrameReady(true);
        postHostSync();
        return;
      }
      if (message.kind === "bridge") {
        onBridgeEvent?.(message.detail);
        window.dispatchEvent(
          new CustomEvent("wiii:visual-frame", { detail: message.detail }),
        );
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [heightProfile, onBridgeEvent, postHostSync]);

  // Tweaks toggle: send activate/deactivate to iframe
  const handleTweaksToggle = useCallback(() => {
    const win = iframeRef.current?.contentWindow;
    if (!win) return;
    const nextActive = !tweaksActive;
    setTweaksActive(nextActive);
    win.postMessage(
      { type: nextActive ? "__activate_edit_mode" : "__deactivate_edit_mode" },
      "*",
    );
  }, [tweaksActive]);

  // Reset tweaks state when HTML changes
  useEffect(() => {
    setTweaksAvailable(false);
    setTweaksActive(false);
  }, [html]);

  if (error) {
    return (
      <div
        className={`rounded-[20px] border border-red-200 bg-red-50 px-4 py-4 text-sm text-red-700 ${className}`}
      >
        Lỗi frame: {error}
      </div>
    );
  }

  if (!blobUrl) return null;

  // Sprint V5: editorial = transparent + no card chrome (Claude-like seamless figure)
  // Phase2: overflow-visible for editorial (prevent text clip), overflow-clip for cards
  const wrapperClassName =
    frameKind === "legacy"
      ? shellVariant === "editorial"
        ? "overflow-visible bg-transparent"
        : "overflow-clip rounded-2xl border border-[var(--border)] bg-[rgba(255,255,255,0.92)] shadow-[var(--shadow-md)]"
      : shellVariant === "editorial"
        ? "overflow-visible bg-transparent"
        : "overflow-clip rounded-2xl bg-transparent";
  const iframeHeight = resolveVisualFrameCssHeight(height, heightProfile);

  return (
    <div
      className={`${wrapperClassName} ${className}`.trim()}
      data-inline-visual-frame={frameKind}
      data-inline-visual-shell={shellVariant}
      data-inline-visual-sizing={sizingMode}
      data-inline-visual-ready={frameReady ? "true" : "false"}
      aria-busy={frameReady ? undefined : true}
      style={{
        position: "relative",
        ...(sizingMode === "viewport" ? { height: "100%", minHeight: "0px" } : {}),
      }}
    >
      {/* eslint-disable-next-line react/iframe-missing-sandbox */}
      <iframe
        ref={iframeRef}
        src={blobUrl}
        sandbox="allow-scripts"
        // @ts-expect-error allowtransparency is a legacy but widely supported iframe attribute
        allowtransparency="true"
        onLoad={() => {
          setFrameReady(true);
          postHostSync();
        }}
        style={{
          width: "100%",
          height: iframeHeight,
          minHeight: `${heightProfile.minHeight}px`,
          border: "none",
          display: "block",
          background: "transparent",
          colorScheme: "normal",
          transition: "height 220ms var(--ease-default)",
        }}
        title={title || frameLabel(frameKind)}
      />
      {/* Tweaks toggle button — only shown when iframe announces edit mode availability */}
      {showTweaksToggle && tweaksAvailable && (
        <button
          onClick={handleTweaksToggle}
          className={`absolute bottom-2 right-2 z-50 flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all ${
            tweaksActive
              ? "bg-[var(--accent)] text-white shadow-md"
              : "bg-white/90 text-text-secondary border border-border shadow-sm hover:bg-white hover:border-[var(--accent)]/40"
          }`}
          title={tweaksActive ? "Tắt Tweaks" : "Tùy chỉnh Tweaks"}
          aria-label={tweaksActive ? "Tắt Tweaks" : "Bật Tweaks"}
          aria-pressed={tweaksActive}
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          >
            <circle cx="8" cy="8" r="2.5" />
            <path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.1 3.1l1.4 1.4M11.5 11.5l1.4 1.4M3.1 12.9l1.4-1.4M11.5 4.5l1.4-1.4" />
          </svg>
          {tweaksActive ? "Tweaks" : "Tweaks"}
        </button>
      )}
    </div>
  );
});
