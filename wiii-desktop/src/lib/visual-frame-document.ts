import type { VisualShellVariant } from "@/api/types";
import type {
  VisualFrameKind,
  VisualFrameSizingMode,
} from "@/lib/visual-frame-contract";

export type VisualFrameHostShellMode = "auto" | "force";

export interface VisualFrameDocumentOptions {
  title?: string;
  summary?: string;
  sessionId?: string;
  shellVariant?: VisualShellVariant;
  frameKind?: VisualFrameKind;
  sizingMode?: VisualFrameSizingMode;
  showFrameIntro?: boolean;
  hostShellMode?: VisualFrameHostShellMode;
  hostThemeOverrides?: Record<string, string>;
}

const ALLOWED_CDNS = [
  "https://cdn.jsdelivr.net",
  "https://cdnjs.cloudflare.com",
  "https://unpkg.com",
  "https://d3js.org",
  "https://cdn.katex.org",
  "https://cdn.tailwindcss.com",
];

const FRAME_CSP = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline' blob: ${ALLOWED_CDNS.join(" ")}; style-src 'unsafe-inline' ${ALLOWED_CDNS.join(" ")}; img-src blob: data: ${ALLOWED_CDNS.join(" ")}; font-src data: ${ALLOWED_CDNS.join(" ")}; connect-src 'none';">`;

const BLOCKED_EXTERNAL_FONT_LINK_RE =
  /<link\b[^>]*href=(["'])https:\/\/fonts\.(?:googleapis|gstatic)\.com(?:\/[^"']*)?\1[^>]*>/gi;
const BLOCKED_EXTERNAL_FONT_IMPORT_RE =
  /@import\s+(?:url\()?["']?https:\/\/fonts\.googleapis\.com\/[^"')]+["']?\)?\s*;?/gi;

const STORAGE_SHIM = `
<script>
  (function () {
    function createMemoryStorage() {
      var store = {};
      return {
        getItem: function (key) {
          return Object.prototype.hasOwnProperty.call(store, key) ? store[key] : null;
        },
        setItem: function (key, value) {
          store[String(key)] = String(value);
        },
        removeItem: function (key) {
          delete store[String(key)];
        },
        clear: function () {
          store = {};
        },
        key: function (index) {
          return Object.keys(store)[index] || null;
        },
        get length() {
          return Object.keys(store).length;
        }
      };
    }

    var safeStorage = createMemoryStorage();
    ['localStorage', 'sessionStorage'].forEach(function (name) {
      try {
        var candidate = window[name];
        if (candidate) return;
      } catch (error) {
        try {
          Object.defineProperty(window, name, {
            configurable: true,
            enumerable: false,
            get: function () { return safeStorage; }
          });
        } catch (defineError) {
          window.__WIII_STORAGE_SHIM_ERROR__ = String(defineError);
        }
      }
    });
  })();
</script>`;

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function stripBlockedExternalFontAssets(content: string): string {
  return content
    .replace(BLOCKED_EXTERNAL_FONT_LINK_RE, "")
    .replace(BLOCKED_EXTERNAL_FONT_IMPORT_RE, "");
}

/**
 * Sprint 35e Item 2 — Theme inheritance bridge.
 *
 * Reads a curated subset of Wiii host CSS variables off
 * ``document.documentElement`` and maps them into the iframe-local
 * ``--wiii-*`` namespace. Pattern reference: VISUAL_CODE_GEN.md v6.2.0
 * §12 "Theme inheritance contract" — host owns the source of truth, the
 * iframe inherits a stable, scoped subset.
 *
 * Each var falls back to ``""`` when the host stylesheet has not loaded
 * yet (e.g. during SSR / first paint), so the iframe :root defaults stay
 * authoritative until a real value lands.
 */
export function readHostThemeOverrides(): Record<string, string> {
  if (typeof document === "undefined") return {};
  let style: CSSStyleDeclaration;
  try {
    style = getComputedStyle(document.documentElement);
  } catch {
    return {};
  }
  const pull = (name: string) => style.getPropertyValue(name).trim();
  const overrides: Record<string, string> = {};
  const accent = pull("--accent");
  if (accent) overrides["--wiii-accent"] = accent;
  const surface = pull("--surface");
  if (surface) overrides["--wiii-bg"] = surface;
  const surfaceWhite = pull("--surface-white");
  if (surfaceWhite) overrides["--wiii-panel"] = surfaceWhite;
  const border = pull("--border");
  if (border) overrides["--wiii-border"] = border;
  const text = pull("--text");
  if (text) overrides["--wiii-text"] = text;
  const textSecondary = pull("--text-secondary");
  if (textSecondary) overrides["--wiii-text-secondary"] = textSecondary;
  const muted = pull("--text-tertiary");
  if (muted) overrides["--wiii-muted"] = muted;
  return overrides;
}

function renderHostThemeOverrideBlock(
  overrides: Record<string, string> | undefined,
): string {
  if (!overrides) return "";
  const safeEntries = Object.entries(overrides).filter(([key, value]) => {
    // CSS variable names: ``--<ident>`` only — no whitespace, no closing braces.
    if (!/^--[a-zA-Z0-9_-]+$/.test(key)) return false;
    if (value.length > 200) return false;
    if (/[<>{}\\]/.test(value)) return false;
    return Boolean(value);
  });
  if (safeEntries.length === 0) return "";
  const declarations = safeEntries
    .map(([key, value]) => `      ${key}: ${value};`)
    .join("\n");
  return `
  <style data-wiii-host-theme="overrides">
    :root {
${declarations}
    }
  </style>`;
}

export function frameLabel(frameKind: VisualFrameKind) {
  if (frameKind === "app") return "Embedded App";
  if (frameKind === "inline_html") return "Inline Visual";
  return "Interactive Widget";
}

function mergeBodyClassAttribute(attrs: string, extraClass: string) {
  if (!extraClass) return attrs;
  if (!/\bclass=/i.test(attrs)) return `${attrs} class="${extraClass}"`;
  return attrs.replace(
    /\bclass=(["'])(.*?)\1/i,
    (_match, quote: string, value: string) =>
      `class=${quote}${value} ${extraClass}${quote}`,
  );
}

/**
 * Tweaks protocol — PostMessage-based live editing (Claude Design pattern).
 * Injected into every visual iframe so the host can toggle a floating Tweaks panel.
 */
const TWEAKS_INJECT = `
<style>
  #wiii-tweaks-panel{display:none;position:fixed;bottom:12px;right:12px;z-index:9999;
    width:260px;max-height:70vh;overflow-y:auto;background:rgba(255,255,255,0.95);
    border:1px solid rgba(0,0,0,0.08);border-radius:10px;box-shadow:0 8px 30px rgba(0,0,0,0.12);
    padding:12px;font:12px/1.5 system-ui,sans-serif;color:#1c1917;backdrop-filter:blur(8px)}
  #wiii-tweaks-panel.visible{display:block}
  .tw-hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;
    font-weight:600;font-size:11px;letter-spacing:0.06em;text-transform:uppercase;color:#78716c}
  .tw-close{cursor:pointer;background:none;border:none;font-size:16px;color:#a8a29e;padding:0 2px}
  .tw-row{display:flex;align-items:center;gap:6px;margin-bottom:6px}
  .tw-row label{flex:0 0 90px;font-size:11px;color:#78716c;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .tw-row input[type=color]{width:28px;height:22px;border:1px solid #d6d3d1;border-radius:4px;cursor:pointer;padding:0}
  .tw-row input[type=range]{flex:1;height:3px;-webkit-appearance:none;appearance:none;background:#e7e5e4;border-radius:2px}
  .tw-row input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:12px;height:12px;border-radius:50%;background:#fff;border:1px solid #a8a29e;cursor:pointer}
</style>
<script id="wiii-tweak-state">/*EDITMODE-BEGIN*/{}/*EDITMODE-END*/</script>
<script>
(function(){
  var _p=document.getElementById('wiii-tweaks-panel');
  var _ts=document.getElementById('wiii-tweak-state');
  if(!_ts)return;
  var _rm=/\\/\\*EDITMODE-BEGIN\\*\\/([\\s\\S]*?)\\/\\*EDITMODE-END\\*\\//;
  function _gj(){var m=_ts.textContent.match(_rm);try{return m?JSON.parse(m[1]):{}}catch(e){return{}}}
  function _sj(j){_ts.textContent='/*EDITMODE-BEGIN*/'+JSON.stringify(j)+'/*EDITMODE-END*/';}
  function _ctrl(k,v){
    var r=document.createElement('div');r.className='tw-row';
    var lb=document.createElement('label');lb.textContent=k;lb.title=k;
    var inp=document.createElement('input');
    if(/#[0-9a-f]{3,8}/i.test(v)){inp.type='color';inp.value=v;inp.addEventListener('input',function(e){_apply(k,e.target.value);});}
    else{var n=parseFloat(v);if(!isNaN(n)){inp.type='range';inp.min='0';inp.max=String(Math.max(n*3,1));inp.step='any';inp.value=v;
      inp.addEventListener('input',function(e){_apply(k,e.target.value);});}
    else{inp.type='text';inp.value=v;inp.addEventListener('input',function(e){_apply(k,e.target.value);});}}
    r.appendChild(lb);r.appendChild(inp);return r;
  }
  function _apply(k,v){document.documentElement.style.setProperty(k,v);
    var j=_gj();j[k]=v;_sj(j);parent.postMessage({type:'__edit_mode_set_keys',edits:j},'*');}
  function _render(){
    if(!_p){_p=document.createElement('div');_p.id='wiii-tweaks-panel';document.body.appendChild(_p);}
    _p.innerHTML='';
    var h=document.createElement('div');h.className='tw-hdr';
    h.textContent='Tweaks';
    var cb=document.createElement('button');cb.className='tw-close';cb.innerHTML='\\u2715';
    cb.onclick=function(){_p.classList.remove('visible');parent.postMessage({type:'__deactivate_edit_mode'},'*');};
    h.appendChild(cb);_p.appendChild(h);
    var j=_gj();var ks=Object.keys(j);
    if(!ks.length){var em=document.createElement('div');em.style.cssText='font-size:11px;color:#a8a29e';
      em.textContent='No tweakable properties';_p.appendChild(em);return;}
    ks.forEach(function(k){_p.appendChild(_ctrl(k,j[k]));});
  }
  window.addEventListener('message',function(e){
    var d=e.data;if(!d||typeof d!=='object')return;
    if(d.type==='__activate_edit_mode'){_render();if(_p)_p.classList.add('visible');}
    if(d.type==='__deactivate_edit_mode'){if(_p)_p.classList.remove('visible');}
  });
  parent.postMessage({type:'__edit_mode_available'},'*');
})();
</script>`;

function injectIntoHead(content: string, payload: string) {
  if (/<head[^>]*>/i.test(content)) {
    return content.replace(/<head[^>]*>/i, (match) => `${match}\n${payload}`);
  }
  if (/<html[^>]*>/i.test(content)) {
    return content.replace(
      /<html[^>]*>/i,
      (match) => `${match}\n<head>\n${payload}\n</head>`,
    );
  }
  return `<!DOCTYPE html>\n<html>\n<head>\n${payload}\n</head>\n${content}\n</html>`;
}

export function buildVisualFrameDocument(
  content: string,
  {
    title = "",
    summary = "",
    sessionId = "",
    shellVariant = "editorial",
    frameKind = "inline_html",
    sizingMode = "content",
    showFrameIntro = false,
    hostShellMode = frameKind === "legacy" ? "auto" : "force",
    hostThemeOverrides = undefined,
}: VisualFrameDocumentOptions = {},
): string {
  const sanitizedContent = stripBlockedExternalFontAssets(content);
  const hasIntro = showFrameIntro && Boolean(title || summary);
  const bridgeScript = `
  <script>
    (function () {
      var reducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      var state = {
        sessionId: ${JSON.stringify(sessionId)},
        title: ${JSON.stringify(title)},
        summary: ${JSON.stringify(summary)},
        shellVariant: ${JSON.stringify(shellVariant)},
        frameKind: ${JSON.stringify(frameKind)},
        sizingMode: ${JSON.stringify(sizingMode)},
        reducedMotion: reducedMotion
      };

      function applyRuntimeDataset() {
        document.documentElement.dataset.wiiiFrameKind = state.frameKind;
        document.documentElement.dataset.wiiiShellVariant = state.shellVariant;
        document.documentElement.dataset.wiiiSizingMode = state.sizingMode;
        if (document.body) {
          document.body.dataset.wiiiFrameKind = state.frameKind;
          document.body.dataset.wiiiShellVariant = state.shellVariant;
          document.body.dataset.wiiiSizingMode = state.sizingMode;
        }
      }

      function post(type, payload) {
        parent.postMessage({ type: type, payload: payload || {} }, '*');
      }

      function measureHeight() {
        var body = document.body || {};
        var doc = document.documentElement || {};
        var rectHeight = body.getBoundingClientRect ? body.getBoundingClientRect().height : 0;
        return Math.ceil(Math.max(
          body.scrollHeight || 0,
          body.offsetHeight || 0,
          doc.scrollHeight || 0,
          doc.offsetHeight || 0,
          rectHeight || 0
        ));
      }

      function notifyResize() {
        post('wiii-frame-resize', { height: measureHeight(), sessionId: state.sessionId });
      }

      function queueResize() {
        if (window.requestAnimationFrame) {
          window.requestAnimationFrame(notifyResize);
        } else {
          setTimeout(notifyResize, 0);
        }
      }

      window.WiiiVisualBridge = {
        resize: notifyResize,
        getState: function () { return state; },
        telemetry: function (name, detail) {
          post('wiii-frame-telemetry', { name: name, detail: detail || {}, sessionId: state.sessionId });
        },
        interaction: function (detail) {
          post('wiii-frame-interaction', { detail: detail || {}, sessionId: state.sessionId });
        },
        setControlValue: function (controlId, value, focusedNodeId) {
          post('wiii-frame-control', { controlId: controlId, value: value, focusedNodeId: focusedNodeId || '', sessionId: state.sessionId });
        },
        focusAnnotation: function (annotationId) {
          post('wiii-frame-focus', { annotationId: annotationId || '', sessionId: state.sessionId });
        },
        reportResult: function (kind, payload, summary, status) {
          post('wiii-frame-result', {
            kind: kind || 'widget_result',
            payload: payload || {},
            summary: summary || '',
            status: status || '',
            sessionId: state.sessionId,
            title: state.title,
            frameKind: state.frameKind
          });
        }
      };

      window.addEventListener('message', function (event) {
        var data = event.data;
        if (!data || typeof data !== 'object') return;
        if (data.type === 'wiii-visual-sync') {
          state.parentState = data.payload || {};
          if (state.parentState && typeof state.parentState.sizingMode === 'string') {
            state.sizingMode = state.parentState.sizingMode;
          }
          applyRuntimeDataset();
          notifyResize();
        }
      });

      window.addEventListener('load', function () {
        applyRuntimeDataset();
        notifyResize();
        if (window.ResizeObserver) {
          var resizeObserver = new ResizeObserver(function () { queueResize(); });
          resizeObserver.observe(document.body);
          resizeObserver.observe(document.documentElement);
        }
        setTimeout(notifyResize, 120);
        setTimeout(notifyResize, 500);
        post('wiii-frame-ready', { sessionId: state.sessionId, frameKind: state.frameKind, shellVariant: state.shellVariant, sizingMode: state.sizingMode });
      });
    })();
  </script>`;

  // Sprint V5: All shells transparent — no more white card container
  const isEditorialLegacy =
    frameKind === "legacy" && shellVariant === "editorial";
  const shellBorder = isEditorialLegacy
    ? "none"
    : frameKind === "legacy"
      ? "1px solid var(--wiii-border)"
      : "1px solid transparent";
  const shellShadow = isEditorialLegacy
    ? "none"
    : frameKind === "legacy"
      ? "var(--wiii-shadow)"
      : "none";
  const shellBackground = isEditorialLegacy
    ? "transparent"
    : frameKind === "legacy"
      ? "var(--wiii-panel)"
      : "transparent";
  const bodyPadding = isEditorialLegacy
    ? "0"
    : frameKind === "legacy"
      ? "14px"
      : shellVariant === "immersive"
        ? "6px 0 0"
        : "4px 0 0";
  const contentPadding = isEditorialLegacy
    ? "0"
    : frameKind === "legacy"
      ? shellVariant === "immersive"
        ? "16px"
        : "14px"
      : shellVariant === "immersive"
        ? "2px 0 0"
        : "0";

  const shellStyle = `
  <style>
    :root {
      color-scheme: light;
      --wiii-bg: #fcfaf6;
      --wiii-panel: rgba(255,255,255,0.92);
      --wiii-border: rgba(161,145,127,0.26);
      --wiii-text: #1c1917;
      --wiii-muted: #5f5a52;
      --wiii-accent: #b85a33;
      --wiii-blue: #2d79c7;
      --wiii-shadow: 0 14px 40px rgba(30,24,18,0.10);
      --wiii-radius: 24px;
      --wiii-body: "Manrope", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      --wiii-display: "Newsreader", Georgia, serif;
      /* Sprint 35e: Scaffold theme inheritance contract.
       * The graceful HTML scaffold (code_studio_template_scaffold.py)
       * consumes these so its palette tracks the host theme automatically
       * when the iframe inherits Wiii's --wiii-* values, and per-deployment
       * overrides land via the host theme override block below. */
      --wiii-text-secondary: var(--wiii-muted);
      --wiii-font-sans: var(--wiii-body);
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; padding: 0; background: transparent; color: var(--wiii-text); font-family: var(--wiii-body); }

    /* Sprint V5: Host-owned form element styling (Claude pattern — bare elements auto-styled) */
    button:not([class]) {
      padding: 6px 14px; font-size: 13px; background: transparent;
      color: var(--wiii-text); border: 0.5px solid var(--wiii-border);
      border-radius: 6px; cursor: pointer; font-family: inherit;
      transition: background 0.15s, transform 0.1s;
    }
    button:not([class]):hover { background: var(--wiii-bg-secondary); }
    button:not([class]):active { transform: scale(0.98); }
    input[type="range"] {
      -webkit-appearance: none; appearance: none; width: 100%; height: 3px;
      background: light-dark(rgba(0,0,0,0.08), rgba(255,255,255,0.1));
      border-radius: 2px; outline: none;
    }
    input[type="range"]::-webkit-slider-thumb {
      -webkit-appearance: none; width: 16px; height: 16px; border-radius: 50%;
      background: var(--wiii-bg); border: 1px solid var(--wiii-border); cursor: pointer;
    }
    h1,h2,h3,h4,h5,h6 { color: var(--wiii-text); }

    /* Sprint V5: SVG utility classes (Claude pattern — .t .ts .th .box .arr) */
    .t { font-size: 14px; fill: var(--wiii-text); }
    .ts { font-size: 12px; fill: var(--wiii-text-secondary); }
    .th { font-size: 14px; fill: var(--wiii-text); font-weight: 600; }
    .box { fill: var(--wiii-bg-secondary); stroke: var(--wiii-border); }
    .arr { stroke: var(--wiii-text-tertiary); fill: none; stroke-width: 1.5; }
    .leader { stroke: var(--wiii-text-tertiary); stroke-width: 0.5; stroke-dasharray: 4 3; fill: none; }

    /* Sprint V5: Color ramp classes for SVG shapes */
    rect.c-red,g.c-red>rect { fill: light-dark(#fef2f2,#3b1111); stroke: light-dark(#fca5a5,#f87171); }
    rect.c-blue,g.c-blue>rect { fill: light-dark(#eff6ff,#1e3a5f); stroke: light-dark(#93c5fd,#60a5fa); }
    rect.c-teal,g.c-teal>rect { fill: light-dark(#f0fdfa,#0d3331); stroke: light-dark(#5eead4,#2dd4bf); }
    rect.c-purple,g.c-purple>rect { fill: light-dark(#f5f3ff,#2d1b69); stroke: light-dark(#c4b5fd,#a78bfa); }
    rect.c-amber,g.c-amber>rect { fill: light-dark(#fffbeb,#3b2e0a); stroke: light-dark(#fcd34d,#fbbf24); }
    rect.c-green,g.c-green>rect { fill: light-dark(#ecfdf5,#0d3320); stroke: light-dark(#6ee7b7,#34d399); }
    body {
      padding: ${bodyPadding};
      overflow: ${frameKind === "app" ? "auto" : "hidden"};
      overscroll-behavior: contain;
      background: transparent;
    }
    body.wiii-host-shell-active {
      padding: ${frameKind === "legacy" ? bodyPadding : "0"};
      background: transparent;
    }
    .wiii-frame-shell {
      border-radius: ${isEditorialLegacy ? "0" : "var(--wiii-radius)"};
      border: ${shellBorder};
      background: ${shellBackground};
      box-shadow: ${shellShadow};
      overflow: ${isEditorialLegacy ? "visible" : "clip"};
    }
    .wiii-frame-intro {
      padding: 14px 16px 8px;
      border-bottom: 1px solid rgba(161,145,127,0.18);
      background:
        linear-gradient(180deg, rgba(255,255,255,0.72), rgba(255,255,255,0.35));
    }
    .wiii-frame-label {
      margin: 0 0 6px;
      font: 700 10px/1.2 var(--wiii-body);
      letter-spacing: 0.24em;
      text-transform: uppercase;
      color: var(--wiii-accent);
    }
    .wiii-frame-title {
      margin: 0;
      font-family: var(--wiii-display);
      font-size: ${frameKind === "app" ? "1.55rem" : "1.35rem"};
      line-height: 1.04;
      letter-spacing: -0.03em;
    }
    .wiii-frame-summary {
      margin: 8px 0 0;
      font-size: 0.92rem;
      line-height: 1.6;
      color: var(--wiii-muted);
    }
    .wiii-frame-content {
      padding: ${contentPadding};
    }
    body[data-wiii-sizing-mode="viewport"] {
      min-height: 100vh;
    }
    body[data-wiii-sizing-mode="viewport"] .wiii-frame-shell {
      min-height: calc(100vh - 8px);
    }
    body[data-wiii-sizing-mode="viewport"] .wiii-frame-content {
      min-height: 0;
    }
    canvas, svg, table, img { max-width: 100%; height: auto; }
    /* Sprint V5: Lighter form defaults — transparent, thin border */
    button, select, input:not([type="range"]), textarea {
      font-family: inherit;
      font-size: 13px;
      border-radius: 6px;
      border: 0.5px solid var(--wiii-border);
      background: transparent;
      color: var(--wiii-text);
      padding: 6px 12px;
    }
    .wiii-host-shell-active[data-wiii-has-intro="true"] .widget-title,
    .wiii-host-shell-active[data-wiii-has-intro="true"] h1.widget-title,
    .wiii-host-shell-active[data-wiii-has-intro="true"] h2.widget-title {
      display: none !important;
    }
    .wiii-host-shell-active .widget-shell,
    .wiii-host-shell-active .widget-card,
    .wiii-host-shell-active .widget-panel,
    .wiii-host-shell-active .simulation-card,
    .wiii-host-shell-active .simulation-shell,
    .wiii-host-shell-active .chart-shell,
    .wiii-host-shell-active .interactive-shell {
      border: 0 !important;
      background: transparent !important;
      box-shadow: none !important;
      padding-inline: 0 !important;
    }
    .wiii-host-shell-active .sim-controls,
    .wiii-host-shell-active .widget-controls,
    .wiii-host-shell-active .sim-btns,
    .wiii-host-shell-active .control-bar {
      background: transparent !important;
      border: 0 !important;
      box-shadow: none !important;
      padding-inline: 0 !important;
    }
    .wiii-host-shell-active canvas,
    .wiii-host-shell-active svg {
      display: block;
      margin-inline: auto;
    }
    .wiii-host-shell-active .widget-caption,
    .wiii-host-shell-active .sim-caption,
    .wiii-host-shell-active .widget-note {
      color: var(--wiii-muted) !important;
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after {
        animation-duration: 0.001ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.001ms !important;
        scroll-behavior: auto !important;
      }
    }
  </style>`;

  const intro = hasIntro
    ? `<div class="wiii-frame-intro"><p class="wiii-frame-label">${escapeHtml(frameLabel(frameKind))}</p>${title ? `<h1 class="wiii-frame-title">${escapeHtml(title)}</h1>` : ""}${summary ? `<p class="wiii-frame-summary">${escapeHtml(summary)}</p>` : ""}</div>`
    : "";

  // Sprint 35e Item 2 — Host theme overrides land AFTER the iframe :root
  // defaults so they win the cascade without breaking standalone preview.
  const themeOverrideBlock = renderHostThemeOverrideBlock(hostThemeOverrides);

  if (/<html/i.test(sanitizedContent)) {
    const headInjected = injectIntoHead(
      sanitizedContent,
      `${FRAME_CSP}\n${STORAGE_SHIM}\n${shellStyle}${themeOverrideBlock}`,
    );
    const shouldWrapBody =
      hostShellMode === "force" &&
      !/wiii-frame-shell|data-wiii-host-shell/i.test(sanitizedContent);

    if (
      shouldWrapBody &&
      /<body[^>]*>/i.test(headInjected) &&
      /<\/body>/i.test(headInjected)
    ) {
      return headInjected.replace(
        /<body([^>]*)>([\s\S]*?)<\/body>/i,
        (_match, attrs: string, bodyContent: string) => {
          const mergedAttrs = mergeBodyClassAttribute(
            attrs,
            "wiii-host-shell-active",
          );
          return `<body${mergedAttrs} data-wiii-host-shell="true" data-wiii-has-intro="${hasIntro ? "true" : "false"}" data-wiii-frame-kind="${escapeHtml(frameKind)}" data-wiii-shell-variant="${escapeHtml(shellVariant)}" data-wiii-sizing-mode="${escapeHtml(sizingMode)}">
  <div class="wiii-frame-shell" data-wiii-frame-kind="${escapeHtml(frameKind)}" data-wiii-shell-variant="${escapeHtml(shellVariant)}">
    ${intro}
    <div class="wiii-frame-content">${bodyContent}</div>
  </div>
  ${bridgeScript}
  ${TWEAKS_INJECT}
</body>`;
        },
      );
    }

    const bodyDecorated = headInjected.replace(
      /<body([^>]*)>/i,
      (_match, attrs: string) => {
        const mergedAttrs = mergeBodyClassAttribute(
          attrs,
          hostShellMode === "force" ? "wiii-host-shell-active" : "",
        );
        const hostAttrs =
          hostShellMode === "force"
            ? ` data-wiii-host-shell="true" data-wiii-has-intro="${hasIntro ? "true" : "false"}"`
            : "";
        return `<body${mergedAttrs}${hostAttrs} data-wiii-frame-kind="${escapeHtml(frameKind)}" data-wiii-shell-variant="${escapeHtml(shellVariant)}" data-wiii-sizing-mode="${escapeHtml(sizingMode)}">`;
      },
    );

    return /<\/body>/i.test(bodyDecorated)
      ? bodyDecorated.replace(
          /<\/body>/i,
          `${bridgeScript}\n${TWEAKS_INJECT}\n</body>`,
        )
      : `${bodyDecorated}\n${bridgeScript}\n${TWEAKS_INJECT}`;
  }

  return `<!DOCTYPE html>
<html lang="vi" data-wiii-frame-kind="${escapeHtml(frameKind)}" data-wiii-shell-variant="${escapeHtml(shellVariant)}" data-wiii-sizing-mode="${escapeHtml(sizingMode)}">
<head>
  <meta charset="utf-8">
  ${FRAME_CSP}
  ${STORAGE_SHIM}
  ${shellStyle}${themeOverrideBlock}
</head>
<body class="${hostShellMode === "force" ? "wiii-host-shell-active" : ""}" data-wiii-host-shell="${hostShellMode === "force" ? "true" : "false"}" data-wiii-has-intro="${hasIntro ? "true" : "false"}" data-wiii-frame-kind="${escapeHtml(frameKind)}" data-wiii-shell-variant="${escapeHtml(shellVariant)}" data-wiii-sizing-mode="${escapeHtml(sizingMode)}">
  <div class="wiii-frame-shell" data-wiii-frame-kind="${escapeHtml(frameKind)}" data-wiii-shell-variant="${escapeHtml(shellVariant)}">
    ${intro}
    <div class="wiii-frame-content">${sanitizedContent}</div>
  </div>
  ${bridgeScript}
  ${TWEAKS_INJECT}
</body>
</html>`;
}
