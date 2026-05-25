import { useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";
import type {
  VisualBlockData,
  VisualPayload,
} from "@/api/types";
import { motion, AnimatePresence } from "motion/react";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { useChatStore } from "@/stores/chat-store";
import {
  resolveCodeStudioSessionIdForVisualSession,
  useCodeStudioStore,
} from "@/stores/code-studio-store";
import { useUIStore } from "@/stores/ui-store";
import { trackVisualTelemetry } from "@/lib/visual-telemetry";
import { staggerContainer } from "@/lib/animations";
import InlineHtmlWidget from "@/components/common/InlineHtmlWidget";
import { InlineVisualFrame } from "@/components/common/InlineVisualFrame";
import { EmbeddedAppFrame } from "@/components/common/EmbeddedAppFrame";
import { RechartsRenderer } from "./RechartsRenderer";
const asRecord = (value: unknown) => value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
const asText = (value: unknown, fallback = "") => typeof value === "string" ? value : fallback;
const sessionIdOf = (visual: Pick<VisualPayload, "visual_session_id" | "id">) => visual.visual_session_id || visual.id;

// Inline HTML/app visuals render in sandboxed frames. The structured template
// path was removed by the Visual Architecture Shift — only inline_html + recharts
// are live dispatch targets.

function normalizeNaturalText(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/gi, " ").replace(/\s+/g, " ").trim();
}

function cleanNarrativeSnippet(raw: string, visual: Pick<VisualPayload, "title">): string {
  if (!raw) return "";
  const cleaned = raw
    .replace(/^visual\s+[a-z_ ]+\s+de tom tat nhanh noi dung:\s*/i, "")
    .replace(/^visual\s+[a-z_ ]+:\s*/i, "")
    .replace(/^structured visual san sang:\s*/i, "")
    .replace(/^structured visual summary\s*/i, "")
    .replace(/^minh hoa da san sang:\s*/i, "")
    .replace(/^minh hoa nay\s*/i, "")
    .replace(/^summary\s*:\s*/i, "")
    .trim();
  if (!cleaned) return "";
  if (normalizeNaturalText(cleaned) === normalizeNaturalText(visual.title)) return "";
  return cleaned;
}

function cleanVisualSummary(visual: VisualPayload): string {
  const raw = visual.summary?.trim() || "";
  if (!raw) return "";
  const cleaned = cleanNarrativeSnippet(raw, visual);
  if (!cleaned) return "";
  return cleaned;
}

function cleanAnnotationTitle(value: string): string {
  const normalized = normalizeNaturalText(value);
  if (!normalized) return "Điểm nhấn";
  if (normalized === "summary" || normalized === "takeaway") return "Điểm chốt";
  if (/^annotation \d+$/.test(normalized)) return "Ghi chú";
  return value;
}

function getVisibleAnnotations(visual: VisualPayload) {
  return visual.annotations
    .map((annotation) => ({
      ...annotation,
      title: cleanAnnotationTitle(annotation.title),
      body: cleanNarrativeSnippet(annotation.body, visual),
    }))
    .filter((annotation) => annotation.title || annotation.body);
}


function getHtmlPayload(visual: VisualPayload): string | null {
  if (visual.fallback_html) return visual.fallback_html;
  // Also check code_html in spec (LLM may pass it there)
  const spec = asRecord(visual.spec);
  for (const key of ["code_html", "html", "markup", "custom_html", "template_html", "app_html"]) {
    const value = spec[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  return null;
}



export function VisualBlock({
  block,
  embedded = false,
  onSuggestedQuestion,
}: {
  block: VisualBlockData;
  embedded?: boolean;
  onSuggestedQuestion?: (prompt: string) => void;
}) {
  const initialVisual = block.visual;
  const sessionId = sessionIdOf(initialVisual);
  const session = useChatStore((state) => state.visualSessions[sessionId]);
  const update = useChatStore((state) => state.updateVisualSessionInteraction);
  const recordWidgetFeedback = useChatStore((state) => state.recordWidgetFeedback);
  const reduced = useReducedMotion();
  const figureRef = useRef<HTMLElement | null>(null);
  const previousRevisionRef = useRef<number | null>(null);
  const titleId = useId();
  const visibleSummaryId = useId();
  const srSummaryId = useId();
  const [stageCue, setStageCue] = useState<"idle" | "open" | "patch">("idle");
  const activeVisual = (session?.latestVisual || initialVisual) as VisualPayload;
  const visual = {
    ...activeVisual,
    scene: activeVisual.scene || { kind: activeVisual.type, nodes: [], panels: [] },
    controls: activeVisual.controls || [],
    annotations: activeVisual.annotations || [],
    interaction_mode: activeVisual.interaction_mode || "static",
    renderer_kind: activeVisual.renderer_kind || "template",
    shell_variant: activeVisual.shell_variant || (activeVisual.renderer_kind === "app" ? "immersive" : "editorial"),
    patch_strategy: activeVisual.patch_strategy || (activeVisual.renderer_kind === "app" ? "app_state" : activeVisual.renderer_kind === "inline_html" ? "replace_html" : "spec_merge"),
    figure_group_id: activeVisual.figure_group_id || activeVisual.visual_session_id || activeVisual.id,
    figure_index: activeVisual.figure_index || 1,
    figure_total: activeVisual.figure_total || 1,
    pedagogical_role: activeVisual.pedagogical_role || "mechanism",
    chrome_mode: activeVisual.chrome_mode || (activeVisual.renderer_kind === "app" ? "app" : "editorial"),
    claim: activeVisual.claim || cleanVisualSummary(activeVisual) || activeVisual.title,
    narrative_anchor: activeVisual.narrative_anchor || "after-lead",
  };

  // Inline visuals can be structured, inline_html, or app-backed. Keep the render path honest.
  const htmlPayload = getHtmlPayload(visual);
  const cleanedSummary = cleanVisualSummary(visual);
  const accessibleSummary = cleanedSummary || getVisibleAnnotations(visual)[0]?.body || visual.title;
  const describedById = embedded && cleanedSummary
    ? visibleSummaryId
    : accessibleSummary
      ? srSummaryId
      : undefined;
  const status = session?.status || block.status || "committed";
  const artifactHandoffPrompt = typeof visual.artifact_handoff_prompt === "string"
    ? visual.artifact_handoff_prompt.trim()
    : "";
  const canRequestArtifact = Boolean(
    visual.artifact_handoff_available
    && visual.artifact_handoff_mode === "followup_prompt"
    && artifactHandoffPrompt
    && onSuggestedQuestion,
  );

  // Delegate to Code Studio panel when it's open for this visual — avoid duplicate display
  const codeStudioPanelOpen = useUIStore((s) => s.codeStudioPanelOpen);
  const codeStudioActiveSessionId = useCodeStudioStore((s) => s.activeSessionId);
  const codeStudioSessionIdForThis = useCodeStudioStore((s) =>
    resolveCodeStudioSessionIdForVisualSession(s.sessions, sessionId),
  );
  const hasCodeStudioSessionForThis = Boolean(codeStudioSessionIdForThis);
  const delegateToCodeStudioPanel = codeStudioPanelOpen
    && hasCodeStudioSessionForThis
    && codeStudioActiveSessionId === codeStudioSessionIdForThis;

  let renderError: string | null = null;
  let usedFallback = false;
  let body: ReactNode = null;

  try {
    const isRechartsVisual = visual.renderer_kind === "recharts"
      || (typeof asRecord(visual.spec).chart_type === "string" && visual.renderer_kind !== "app" && visual.renderer_kind !== "inline_html");

    // Priority: inline_html FIRST (clean SVG/HTML), then Recharts, then template fallback
    const isInlineHtml = visual.renderer_kind === "inline_html" && htmlPayload;

    if (isInlineHtml) {
      body = (
        <InlineVisualFrame
          html={htmlPayload}
          title={visual.title}
          summary={visual.summary}
          sessionId={sessionId}
          shellVariant={visual.shell_variant}
          frameKind="inline_html"
          showFrameIntro={false}
          hostShellMode="force"
          showTweaksToggle
        />
      );
    } else if (isRechartsVisual) {
      body = (
        <div className={`visual-block-shell__canvas ${embedded ? "visual-block-shell__canvas--embedded" : ""}`.trim()}>
          <RechartsRenderer spec={asRecord(visual.spec)} />
        </div>
      );
    } else if (visual.renderer_kind === "app") {
      if (!htmlPayload) throw new Error("Missing html payload for app visual");
      body = (
        <EmbeddedAppFrame
          html={htmlPayload}
          title={visual.title}
          summary={visual.summary}
          sessionId={sessionId}
          shellVariant={visual.shell_variant}
          runtimeManifest={visual.runtime_manifest}
        />
      );
    } else if (htmlPayload) {
      body = (
        <InlineVisualFrame
          html={htmlPayload}
          title={visual.title}
          summary={visual.summary}
          sessionId={sessionId}
          shellVariant={visual.shell_variant}
          frameKind="inline_html"
          showFrameIntro={false}
          hostShellMode="force"
          showTweaksToggle
        />
      );
    } else {
      throw new Error("Missing html payload for visual");
    }
  } catch (error) {
    renderError = error instanceof Error ? error.message : "Unknown visual render error";
    body = htmlPayload
      ? <InlineHtmlWidget code={htmlPayload} />
      : <div className="flex items-center gap-3 rounded-2xl border border-border/60 bg-surface-secondary/50 px-5 py-4 text-sm text-text-tertiary">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="shrink-0 opacity-50"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/><path d="M9 21V9"/></svg>
          Visual đang được chuẩn bị...
        </div>;
    usedFallback = Boolean(htmlPayload);
  }

  useEffect(() => {
    const revision = session?.revisionCount || 1;
    const previousRevision = previousRevisionRef.current;
    const nextCue = previousRevision === null
      ? (visual.lifecycle_event === "visual_patch" ? "patch" : "open")
      : revision !== previousRevision
        ? (visual.lifecycle_event === "visual_patch" ? "patch" : "open")
        : null;

    previousRevisionRef.current = revision;
    if (!nextCue) return;

    setStageCue(nextCue);
    if (reduced) {
      setStageCue("idle");
      return;
    }

    const timeoutId = window.setTimeout(() => setStageCue("idle"), nextCue === "patch" ? 1150 : 900);
    return () => window.clearTimeout(timeoutId);
  }, [reduced, session?.revisionCount, visual.lifecycle_event]);

  useEffect(() => {
    const detail = {
      visual_id: visual.id,
      visual_session_id: sessionId,
      visual_type: visual.type,
      runtime: visual.runtime,
      renderer_kind: visual.renderer_kind,
      shell_variant: visual.shell_variant,
    };
    if (renderError) return void trackVisualTelemetry("visual_render_error", { ...detail, error: renderError });
    if (usedFallback) return void trackVisualTelemetry("visual_fallback_used", detail);
    trackVisualTelemetry("visual_rendered", detail);
  }, [renderError, sessionId, usedFallback, visual.id, visual.renderer_kind, visual.runtime, visual.shell_variant, visual.type]);

  useEffect(() => {
    const handleFrameEvent = (event: Event) => {
      const detail = (event as CustomEvent<Record<string, unknown>>).detail || {};
      if (detail.sessionId !== sessionId) return;

      if (detail.bridgeType === "control" && typeof detail.controlId === "string") {
        update(sessionId, {
          controlValues: { [detail.controlId]: detail.value as string | number | boolean },
          focusedNodeId: typeof detail.focusedNodeId === "string" && detail.focusedNodeId ? detail.focusedNodeId : undefined,
          interactionDelta: 1,
        });
        trackVisualTelemetry("visual_interacted", {
          visual_id: visual.id,
          visual_session_id: sessionId,
          visual_type: visual.type,
          control_id: detail.controlId,
          value: String(detail.value ?? ""),
          source: "frame_control",
        });
        return;
      }

      if (detail.bridgeType === "focus" && typeof detail.annotationId === "string") {
        update(sessionId, {
          focusedAnnotationId: detail.annotationId || undefined,
          interactionDelta: 1,
        });
        trackVisualTelemetry("visual_interacted", {
          visual_id: visual.id,
          visual_session_id: sessionId,
          visual_type: visual.type,
          control_id: "annotation_focus",
          value: detail.annotationId || "clear",
          source: "frame_focus",
        });
        return;
      }

      if (detail.bridgeType === "interaction") {
        const frameDetail = asRecord(detail.detail);
        update(sessionId, {
          focusedNodeId: asText(frameDetail.focusedNodeId) || undefined,
          interactionDelta: 1,
        });
        trackVisualTelemetry("visual_interacted", {
          visual_id: visual.id,
          visual_session_id: sessionId,
          visual_type: visual.type,
          source: "frame_interaction",
          ...frameDetail,
        });
        return;
      }

      if (detail.bridgeType === "telemetry" && typeof detail.name === "string" && detail.name.startsWith("visual_")) {
        trackVisualTelemetry(detail.name as `visual_${string}`, {
          visual_id: visual.id,
          visual_session_id: sessionId,
          visual_type: visual.type,
          source: "frame_telemetry",
          ...asRecord(detail.detail),
        });
        return;
      }

      if (detail.bridgeType === "result") {
        const payload = asRecord(detail.payload);
        recordWidgetFeedback({
          widget_id: String(detail.sessionId || sessionId),
          widget_kind: typeof detail.kind === "string" ? detail.kind : `${visual.type}_result`,
          summary: typeof detail.summary === "string" ? detail.summary : undefined,
          status: typeof detail.status === "string" && detail.status ? detail.status : status,
          title: typeof detail.title === "string" && detail.title ? detail.title : visual.title,
          visual_session_id: sessionId,
          score: typeof payload.score === "number" ? payload.score : undefined,
          correct_count: typeof payload.correct_count === "number" ? payload.correct_count : undefined,
          total_count: typeof payload.total_count === "number" ? payload.total_count : undefined,
          source: visual.renderer_kind,
          data: payload,
        });
      }
    };

    window.addEventListener("wiii:visual-frame", handleFrameEvent as EventListener);
    return () => window.removeEventListener("wiii:visual-frame", handleFrameEvent as EventListener);
  }, [recordWidgetFeedback, sessionId, status, update, visual.id, visual.renderer_kind, visual.title, visual.type]);

  useEffect(() => {
    if (!embedded || typeof window === "undefined") return;
    const element = figureRef.current;
    if (!element || typeof element.scrollIntoView !== "function") return;

    const rect = element.getBoundingClientRect();
    const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
    const topBuffer = 88;
    const bottomBuffer = 120;
    const isMostlyVisible = rect.top >= topBuffer / 2 && rect.bottom <= viewportHeight - bottomBuffer / 2;
    if (isMostlyVisible) return;

    const rafId = window.requestAnimationFrame(() => {
      element.scrollIntoView({
        block: "center",
        inline: "nearest",
        behavior: reduced ? "auto" : "smooth",
      });
    });

    return () => window.cancelAnimationFrame(rafId);
  }, [embedded, reduced, visual.lifecycle_event, visual.title, visual.summary, visual.type]);

  // Inline visual shell stays shared even when body switches between structured, inline_html, and app runtimes.
  // Progressive reveal: decorative skeleton overlay during "open" cue, content always rendered
  const isBuilding = stageCue === "open" && !reduced && status === "open";
  const figureClassName = [
    "visual-block-shell",
    "visual-block-shell--article",
    embedded ? "visual-block-shell--embedded" : "",
    embedded ? "" : "my-6",
  ].filter(Boolean).join(" ");

  if (delegateToCodeStudioPanel) {
    return (
      <figure data-testid="visual-block" className="my-4">
        <button
          type="button"
          className="flex items-center gap-2.5 w-full rounded-xl border border-border/60 bg-surface-secondary/40 px-4 py-3 text-left text-sm text-text-secondary hover:bg-surface-secondary transition-colors"
          onClick={() => {
            useCodeStudioStore.getState().setActiveSession(codeStudioSessionIdForThis || sessionId);
            useUIStore.getState().openCodeStudio();
          }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="shrink-0 text-[var(--accent)]"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
          <span className="truncate font-medium">{visual.title}</span>
          <span className="ml-auto text-xs text-text-tertiary shrink-0">Đang mở trong Code Studio</span>
        </button>
      </figure>
    );
  }

  // Inline visuals: render directly without shell header/badge/artifact chrome
  // Skip full shell for inline_html, recharts, and template (converted to inline_html)
  const skipShellChrome = visual.renderer_kind !== "app" && body;
  if (skipShellChrome) {
    return <figure
      ref={figureRef}
      data-testid="visual-block"
      className={figureClassName}
      aria-labelledby={titleId}
      data-visual-status={status}
      data-visual-lifecycle={visual.lifecycle_event}
      data-visual-embedded={embedded ? "true" : "false"}
    >
      <div className={`visual-block-shell__body ${embedded ? "visual-block-shell__body--embedded" : ""}`.trim()}>
        {body}
      </div>
      <figcaption className="sr-only">{visual.summary || visual.title}</figcaption>
    </figure>;
  }

  return <figure
    ref={figureRef}
    data-testid="visual-block"
    className={figureClassName}
    aria-labelledby={titleId}
    aria-describedby={describedById}
    data-visual-status={status}
    data-visual-lifecycle={visual.lifecycle_event}
    data-visual-cue={stageCue}
    data-visual-embedded={embedded ? "true" : "false"}
  >
    <div className={`visual-block-shell__header ${embedded ? "visual-block-shell__header--embedded" : ""}`.trim()}>
      <div className="space-y-4">
        {/* Badge/pill removed — visual_type/pedagogical_role are internal metadata */}
        <div className="space-y-2">
          <h3 id={titleId} className="font-serif text-[clamp(1.55rem,4vw,2.25rem)] leading-tight text-text">
            {visual.title}
          </h3>
          {embedded && cleanedSummary ? (
            <p
              id={visibleSummaryId}
              className="visual-block-shell__lede"
            >
              {cleanedSummary}
            </p>
          ) : null}
          {!embedded && visual.claim && normalizeNaturalText(visual.claim) !== normalizeNaturalText(visual.title) ? (
            <p className="visual-block-shell__claim">{visual.claim}</p>
          ) : null}
        </div>
      </div>
    </div>
    <div className={`visual-block-shell__body ${embedded ? "visual-block-shell__body--embedded" : ""}`.trim()}>
    <div className="visual-block-reveal" style={{ position: "relative" }}>
      <motion.div
        variants={staggerContainer}
        initial={reduced ? "visible" : "hidden"}
        animate="visible"
      >
        {body}
      </motion.div>
      {/* Building skeleton overlay — decorative, fades out when visual is ready */}
      <AnimatePresence>
        {isBuilding && (
          <motion.div
            className="visual-block-reveal__skeleton"
            initial={{ opacity: 1 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0, transition: { duration: 0.35, ease: "easeOut" } }}
            style={{ position: "absolute", inset: 0, zIndex: 2, pointerEvents: "none" }}
          >
            <div className="visual-block-reveal__skeleton-bar" />
            <div className="visual-block-reveal__skeleton-bar" style={{ width: "25%" }} />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
    {(htmlPayload || canRequestArtifact) && (
      <VisualActionBar
        htmlPayload={htmlPayload}
        title={visual.title}
        sessionId={sessionId}
        artifactHandoffLabel={visual.artifact_handoff_label || undefined}
        artifactHandoffPrompt={canRequestArtifact ? artifactHandoffPrompt : undefined}
        onSuggestedQuestion={onSuggestedQuestion}
      />
    )}
    </div>
    <figcaption id={srSummaryId} className="sr-only">{accessibleSummary}</figcaption>
  </figure>;
}

/** Action bar below visual — includes Code Studio link when session exists. */
function VisualActionBar({
  htmlPayload,
  title,
  sessionId,
  artifactHandoffLabel,
  artifactHandoffPrompt,
  onSuggestedQuestion,
}: {
  htmlPayload?: string | null;
  title: string;
  sessionId: string;
  artifactHandoffLabel?: string;
  artifactHandoffPrompt?: string;
  onSuggestedQuestion?: (prompt: string) => void;
}) {
  const codeStudioSessionId = useCodeStudioStore((s) =>
    resolveCodeStudioSessionIdForVisualSession(s.sessions, sessionId),
  );
  const hasCodeStudioSession = Boolean(codeStudioSessionId);
  const isStreaming = useChatStore((state) => state.isStreaming);

  const openInCodeStudio = () => {
    if (!codeStudioSessionId) return;
    useCodeStudioStore.getState().setActiveSession(codeStudioSessionId);
    useUIStore.getState().openCodeStudio();
  };

  const requestArtifactHandoff = () => {
    if (!artifactHandoffPrompt || !onSuggestedQuestion || isStreaming) return;
    trackVisualTelemetry("visual_artifact_handoff_requested", {
      visual_session_id: sessionId,
      source: "visual_action_bar",
    });
    onSuggestedQuestion(artifactHandoffPrompt);
  };

  return (
    <div className="visual-action-bar">
      {artifactHandoffPrompt && onSuggestedQuestion && (
        <button
          type="button"
          className="visual-action-bar__button visual-action-bar__button--artifact"
          onClick={requestArtifactHandoff}
          disabled={isStreaming}
          aria-label={artifactHandoffLabel || "Mở thành Artifact"}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 3l1.8 4.5L18 9.3l-4.2 1.8L12 15.6l-1.8-4.5L6 9.3l4.2-1.8L12 3z"/><path d="M19 14l.9 2.1L22 17l-2.1.9L19 20l-.9-2.1L16 17l2.1-.9L19 14z"/><path d="M5 14l.6 1.5L7 16l-1.4.5L5 18l-.6-1.5L3 16l1.4-.5L5 14z"/></svg>
          {artifactHandoffLabel || "Mở thành Artifact"}
        </button>
      )}
      {hasCodeStudioSession && (
        <button
          type="button"
          className="visual-action-bar__button visual-action-bar__button--studio"
          onClick={openInCodeStudio}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
          Code Studio
        </button>
      )}
      {htmlPayload && (
        <>
          <button
            type="button"
            className="visual-action-bar__button"
            onClick={() => {
              const blob = new Blob([htmlPayload], { type: "text/html" });
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = `${(title || "visual").replace(/[^a-zA-Z0-9\u00C0-\u024F]/g, "_").substring(0, 40)}.html`;
              a.click();
              URL.revokeObjectURL(url);
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            Tải HTML
          </button>
          <button
            type="button"
            className="visual-action-bar__button"
            onClick={() => { navigator.clipboard.writeText(htmlPayload); }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
            Sao chép
          </button>
        </>
      )}
    </div>
  );
}
