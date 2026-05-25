import { useMemo, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  Clock3,
  ExternalLink,
  FileSearch,
  Globe,
  Globe2,
  Palette,
  Search,
  TerminalSquare,
  Wrench,
} from "lucide-react";
import type { ToolExecutionBlockData } from "@/api/types";
import { TOOL_LABELS } from "@/lib/reasoning-labels";
import { VisualArtifactCard } from "./VisualArtifactCard";
import { CodeStudioCard } from "./CodeStudioCard";
import {
  resolveCodeStudioSessionIdForVisualSession,
  useCodeStudioStore,
} from "@/stores/code-studio-store";

interface ToolExecutionStripProps {
  block: ToolExecutionBlockData;
}

// Strip filesystem absolute paths from inline text. Tightened to avoid
// false positives on URL paths (`https://example.com/x`) and slash-formatted
// dates (`04/05/2026`). Match only:
//   - Windows drive paths: `C:\Users\...` or `C:/Users/...`
//   - Linux conventional roots: `/home/`, `/var/`, `/usr/`, `/etc/`, `/tmp/`,
//     `/opt/`, `/root/`, `/mnt/`, `/srv/`, `/Users/`, `/app/`
//   - Relative path prefixes: `./` and `../`
// Things this should NOT match: `04/05/2026` (date), `https://x.com/y` (URL),
// `M/F` ratio, `4/5` rating.
const ABSOLUTE_PATH_PATTERN =
  /(?:[A-Za-z]:[\\/](?:[^\\/\s"'`]+[\\/]?)+)|(?:\/(?:home|var|usr|tmp|etc|opt|root|mnt|srv|Users|app|bin|sbin|lib|proc)(?:\/[^\\/\s"'`]+)+)|(?:\.\.?\/[^\\/\s"'`]+(?:\/[^\\/\s"'`]+)*)/g;
const MARKDOWN_FENCE_PATTERN = /```[\s\S]*?```/g;

const VISUAL_TOOL_NAMES = new Set(["tool_create_visual_code"]);

const SEARCH_TOOL_NAMES = new Set([
  "tool_web_search",
  "tool_search_news",
  "tool_search_legal",
  "tool_search_maritime",
  "tool_search_products",
  "tool_search_shopping",
]);

export function resolveToolExecutionIcon(name: string) {
  if (name === "tool_create_visual_code") return Palette;
  if (name.includes("browser") || name.includes("web")) return Globe2;
  if (name.includes("search")) return Search;
  if (name.includes("python") || name.includes("exec") || name.includes("code"))
    return TerminalSquare;
  if (name.includes("generate") || name.includes("file")) return FileSearch;
  return Wrench;
}

function normalizeWhitespace(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function extractFilename(value: string): string {
  const trimmed = value.trim().replace(/[)"'`,]+$/g, "");
  const segments = trimmed.split(/[\\/]/).filter(Boolean);
  return segments[segments.length - 1] || trimmed;
}

function extractVisualSessionIdFromResult(result: unknown): string {
  if (typeof result !== "string" || !result.trim()) return "";
  try {
    const parsed = JSON.parse(result);
    if (
      parsed &&
      typeof parsed === "object" &&
      typeof parsed.visual_session_id === "string"
    ) {
      return parsed.visual_session_id.trim();
    }
  } catch {
    // Ignore non-JSON tool results.
  }
  return "";
}

function sanitizeInlineText(value: string): string {
  return normalizeWhitespace(
    value.replace(ABSOLUTE_PATH_PATTERN, (match) => extractFilename(match)),
  );
}

function sanitizeTechnicalDetail(value: string): string {
  return value
    .replace(/\r\n/g, "\n")
    .replace(ABSOLUTE_PATH_PATTERN, (match) => extractFilename(match))
    .replace(MARKDOWN_FENCE_PATTERN, (match) =>
      match.replace(/```/g, "").trim(),
    )
    .trim();
}

function clampNaturalText(value: string, maxLength = 180): string {
  if (value.length <= maxLength) return value;
  const sliced = value.slice(0, maxLength);
  const lastSpace = sliced.lastIndexOf(" ");
  return `${(lastSpace > 80 ? sliced.slice(0, lastSpace) : sliced).trim()}...`;
}

function inferPythonArtifactName(code: string): string | undefined {
  const savefigMatch = code.match(/savefig\(\s*['"`]([^'"`]+)['"`]/i);
  if (savefigMatch) return extractFilename(savefigMatch[1]);

  const fileMatch = code.match(
    /['"`]([^'"`]+\.(?:png|jpg|jpeg|webp|svg|pdf|html|xlsx|docx|csv|json|txt))['"`]/i,
  );
  if (fileMatch) return extractFilename(fileMatch[1]);

  return undefined;
}

function describePythonIntent(code: string): string {
  const lowered = code.toLowerCase();
  if (
    lowered.includes("savefig") ||
    lowered.includes("matplotlib") ||
    lowered.includes("plot(")
  ) {
    const artifactName = inferPythonArtifactName(code);
    return artifactName
      ? `Script Python để tạo biểu đồ ${artifactName}`
      : "Script Python để tạo biểu đồ";
  }
  if (/\.(xlsx|xlsm|csv)\b/i.test(code) || lowered.includes("dataframe")) {
    return "Script Python để xử lý bảng dữ liệu";
  }
  if (/\.(docx|doc)\b/i.test(code)) {
    return "Script Python để tạo tài liệu";
  }
  if (/\.(html|htm)\b/i.test(code)) {
    return "Script Python để tạo giao diện HTML";
  }
  return "Script Python để tạo đầu ra kỹ thuật";
}

function summarizeArgs(
  toolName: string,
  args?: Record<string, unknown>,
): string {
  if (!args) return "";
  if (toolName === "tool_think") {
    const thought =
      typeof args.thought === "string" ? sanitizeInlineText(args.thought) : "";
    return thought ? clampNaturalText(thought, 180) : "";
  }
  if (toolName === "tool_report_progress") {
    const message =
      typeof args.message === "string" ? sanitizeInlineText(args.message) : "";
    return message ? clampNaturalText(message, 180) : "";
  }
  if (
    toolName === "tool_generate_visual" ||
    toolName === "tool_generate_rich_visual" ||
    toolName === "tool_create_visual_code"
  ) {
    const title =
      typeof args.title === "string" ? sanitizeInlineText(args.title) : "";
    return title
      ? `Đang phác thảo minh họa cho: ${clampNaturalText(title, 90)}`
      : "Đang phác thảo một minh họa để giải thích rõ hơn";
  }
  if (toolName === "tool_execute_python") {
    const code =
      typeof args.code === "string"
        ? args.code
        : typeof args.script === "string"
          ? args.script
          : "";
    if (code.trim()) {
      return describePythonIntent(code);
    }
    return "Script Python đang được chuẩn bị";
  }

  const preferredKeys = [
    "query",
    "q",
    "url",
    "title",
    "filename",
    "file_name",
    "prompt",
  ];
  for (const key of preferredKeys) {
    const value = args[key];
    if (typeof value === "string" && value.trim())
      return clampNaturalText(sanitizeInlineText(value.trim()), 120);
  }

  const firstEntry = Object.entries(args).find(
    ([, value]) => typeof value === "string" && value.trim(),
  );
  if (firstEntry && typeof firstEntry[1] === "string") {
    return clampNaturalText(sanitizeInlineText(firstEntry[1].trim()), 120);
  }

  return "";
}

function extractArtifactNames(result: string): string[] {
  const names = new Set<string>();
  const bulletMatches = result.matchAll(
    /-\s*([^\s]+?\.(?:png|jpg|jpeg|webp|svg|pdf|html|xlsx|docx|csv|json|txt))/gi,
  );
  for (const match of bulletMatches) {
    names.add(extractFilename(match[1]));
  }
  return [...names];
}

function extractOutputSummary(result: string): string | undefined {
  const outputMatch = result.match(/Output:\s*([\s\S]+?)(?:Artifacts?:|$)/i);
  if (!outputMatch) return undefined;
  const cleaned = sanitizeInlineText(outputMatch[1]);
  return cleaned ? clampNaturalText(cleaned, 120) : undefined;
}

function buildPythonTechnicalDetail(
  args?: Record<string, unknown>,
  result?: string,
): string {
  const parts: string[] = [];
  const code =
    typeof args?.code === "string"
      ? args.code.trim()
      : typeof args?.script === "string"
        ? args.script.trim()
        : "";
  if (code) {
    parts.push(`Script Python\n${code}`);
  }
  if (result?.trim()) {
    parts.push(`Kết quả\n${sanitizeTechnicalDetail(result)}`);
  }
  return parts.join("\n\n").trim();
}

function summarizeResult(
  toolName: string,
  result?: string,
  args?: Record<string, unknown>,
): { line: string; technicalDetail?: string; detailLabel?: string } {
  if (!result) return { line: "" };

  if (
    toolName === "tool_generate_visual" ||
    toolName === "tool_generate_rich_visual" ||
    toolName === "tool_create_visual_code"
  ) {
    return {
      line: "Đã chèn minh họa ngay trong câu trả lời",
      technicalDetail: sanitizeTechnicalDetail(result) || undefined,
      detailLabel: "Chi tiết tạo minh họa",
    };
  }

  if (toolName === "tool_execute_python") {
    const artifactNames = extractArtifactNames(result);
    const outputSummary = extractOutputSummary(result);
    const line =
      artifactNames.length > 0
        ? `Đã tạo ${artifactNames.length} tệp: ${artifactNames.join(", ")}`
        : outputSummary || "Script Python đã chạy xong";
    const technicalDetail = buildPythonTechnicalDetail(args, result);
    return {
      line: clampNaturalText(line, 160),
      technicalDetail: technicalDetail || undefined,
      detailLabel: "Chi tiết script",
    };
  }

  const normalized = clampNaturalText(
    sanitizeInlineText(result).replace(/[{}[\]"]/g, ""),
    180,
  );
  return {
    line: normalized,
    technicalDetail: sanitizeTechnicalDetail(result) || undefined,
    detailLabel: "Chi tiết công cụ",
  };
}

function normalizeForCompare(value: string): string {
  return value.toLowerCase().replace(/\s+/g, " ").trim();
}

/* ---------- Search result parsing ---------- */

interface SearchResultItem {
  title: string;
  url: string;
  domain: string;
  snippet?: string;
}

function extractDomain(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url.slice(0, 40);
  }
}

function parseSearchResults(result?: string): SearchResultItem[] {
  if (!result) return [];
  const items: SearchResultItem[] = [];

  // Try JSON parse first
  try {
    const parsed = JSON.parse(result);
    const arr = Array.isArray(parsed)
      ? parsed
      : parsed?.results || parsed?.items || [];
    for (const item of arr) {
      if (typeof item?.title === "string" && typeof item?.url === "string") {
        items.push({
          title: item.title,
          url: item.url,
          domain: extractDomain(item.url),
          snippet: typeof item.snippet === "string" ? item.snippet : undefined,
        });
      }
      if (items.length >= 5) break;
    }
    if (items.length > 0) return items;
  } catch {
    /* not JSON, try text parsing */
  }

  // Text pattern: "- [Title](URL)" or "Title: URL" or "Title — domain.com"
  const linkPattern = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g;
  for (const match of result.matchAll(linkPattern)) {
    items.push({
      title: match[1],
      url: match[2],
      domain: extractDomain(match[2]),
    });
    if (items.length >= 5) break;
  }
  if (items.length > 0) return items;

  // Pattern: "Title\nURL" on consecutive lines
  const lines = result
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
  for (let i = 0; i < lines.length - 1 && items.length < 5; i++) {
    const line = lines[i];
    const nextLine = lines[i + 1];
    if (
      nextLine &&
      /^https?:\/\//.test(nextLine) &&
      !/^https?:\/\//.test(line)
    ) {
      items.push({
        title: line.replace(/^\d+\.\s*/, "").replace(/^[-*]\s*/, ""),
        url: nextLine,
        domain: extractDomain(nextLine),
      });
      i += 1;
    }
  }

  return items;
}

function SearchResultWidget({ items }: { items: SearchResultItem[] }) {
  if (items.length === 0) return null;
  return (
    <div className="search-result-widget">
      {items.map((item, index) => {
        // Use Google's favicon service — free, no auth, works for any public site.
        // Pattern follows Perplexity / Tavily citation cards (4/5/2026).
        const faviconUrl = item.domain
          ? `https://www.google.com/s2/favicons?domain=${item.domain}&sz=32`
          : "";
        return (
          <a
            key={`${item.url}-${index}`}
            href={item.url}
            target="_blank"
            rel="noreferrer noopener"
            className="search-result-widget__item group/search-item"
            title={item.url}
          >
            <span className="search-result-widget__index" aria-hidden="true">
              {index + 1}
            </span>
            {faviconUrl ? (
              <img
                src={faviconUrl}
                alt=""
                width={14}
                height={14}
                className="search-result-widget__favicon shrink-0 rounded-sm"
                loading="lazy"
                referrerPolicy="no-referrer"
                onError={(e) => {
                  // Fallback to globe icon if favicon fails to load.
                  (e.currentTarget as HTMLImageElement).style.display = "none";
                  const sib = e.currentTarget
                    .nextElementSibling as HTMLElement | null;
                  if (sib) sib.style.display = "inline-block";
                }}
              />
            ) : null}
            <Globe
              size={14}
              className="search-result-widget__favicon shrink-0"
              style={{ display: faviconUrl ? "none" : "inline-block" }}
            />
            <div className="search-result-widget__content">
              <span className="search-result-widget__title">
                {clampNaturalText(item.title, 80)}
              </span>
              <span className="search-result-widget__domain">
                {item.domain}
              </span>
            </div>
            <ExternalLink
              size={10}
              className="search-result-widget__link-icon shrink-0 opacity-0 group-hover/search-item:opacity-50"
            />
          </a>
        );
      })}
    </div>
  );
}

/* ---------- Main component ---------- */

export function ToolExecutionStrip({ block }: ToolExecutionStripProps) {
  const toolName = block.tool.name;

  if (VISUAL_TOOL_NAMES.has(toolName)) {
    return <VisualToolStrip block={block} />;
  }

  return <GenericToolStrip block={block} />;
}

/** Visual tool strip — renders CodeStudioCard if session exists, otherwise VisualArtifactCard. */
function VisualToolStrip({ block }: ToolExecutionStripProps) {
  const csSessionId =
    typeof block.tool.args?._code_studio_session_id === "string"
      ? block.tool.args._code_studio_session_id.trim()
      : "";
  const visual_session_id =
    typeof block.tool.args?.visual_session_id === "string" &&
    block.tool.args.visual_session_id.trim()
      ? block.tool.args.visual_session_id.trim()
      : extractVisualSessionIdFromResult(block.tool.result);
  const codeStudioSessionId = useCodeStudioStore((s) =>
    resolveCodeStudioSessionIdForVisualSession(s.sessions, visual_session_id)
    || (csSessionId && s.sessions[csSessionId] ? csSessionId : null),
  );

  if (codeStudioSessionId) {
    return <CodeStudioCard sessionId={codeStudioSessionId} />;
  }
  return <VisualArtifactCard block={block} />;
}

/** Generic tool strip — separated to avoid hooks-after-return violation. */
function GenericToolStrip({ block }: ToolExecutionStripProps) {
  // Phase 35 — SOTA collapse pattern (Claude.ai / Perplexity 2026):
  // - Always show: label + state + args line  (1-2 visual rows)
  // - Hide by default: result line + search cards + technical detail
  // - User clicks the strip header / "Xem nguồn" link to expand
  // This cuts vertical footprint ~70% for multi-tool turns.
  const [expanded, setExpanded] = useState(false);
  const toolName = block.tool.name;
  const Icon = resolveToolExecutionIcon(toolName);
  const label =
    TOOL_LABELS[toolName] || toolName.replace(/^tool_/, "").replace(/_/g, " ");
  const isPending = block.status === "pending";
  const argsLine = useMemo(
    () => summarizeArgs(toolName, block.tool.args),
    [toolName, block.tool.args],
  );
  const {
    line: rawResultLine,
    technicalDetail,
    detailLabel,
  } = useMemo(
    () => summarizeResult(toolName, block.tool.result, block.tool.args),
    [toolName, block.tool.result, block.tool.args],
  );
  const resultLine =
    normalizeForCompare(rawResultLine) === normalizeForCompare(argsLine)
      ? ""
      : rawResultLine;
  const showDetailsToggle = Boolean(technicalDetail && !isPending);

  // Search result widget — rich rendering for search tools
  const isSearchTool =
    SEARCH_TOOL_NAMES.has(toolName) || toolName.includes("search");
  const searchItems = useMemo(
    () => (isSearchTool ? parseSearchResults(block.tool.result) : []),
    [isSearchTool, block.tool.result],
  );

  // Show body content (result/cards) only when user expands. The summary
  // line in the header already conveys what happened (e.g. "Tìm được 4
  // nguồn: cnbc.com, ..."), so the cards/details are progressive disclosure.
  const hasBodyContent = searchItems.length > 0 || Boolean(resultLine);
  const canExpand = hasBodyContent || showDetailsToggle;

  return (
    <div
      className={`tool-strip ${isPending ? "tool-strip--pending" : "tool-strip--complete"}`}
    >
      <div className="tool-strip__rail" aria-hidden="true">
        <span className="tool-strip__dot">
          <Icon size={12} />
        </span>
      </div>

      <div className="tool-strip__body">
        <button
          type="button"
          className="tool-strip__header tool-strip__header--clickable"
          onClick={() => canExpand && setExpanded((v) => !v)}
          aria-expanded={canExpand ? expanded : undefined}
          aria-disabled={!canExpand}
          disabled={!canExpand}
        >
          <span className="tool-strip__label">{label}</span>
          <span className="tool-strip__state">
            {isPending ? <Clock3 size={12} /> : <CheckCircle2 size={12} />}
            {isPending ? "Đang chạy" : "Đã xong"}
          </span>
          {canExpand && !isPending && (
            <ChevronDown
              size={11}
              className={`tool-strip__expand-chevron ${expanded ? "tool-strip__expand-chevron--open" : ""}`}
            />
          )}
        </button>

        {argsLine && <div className="tool-strip__query">{argsLine}</div>}

        {/* Rich search results when available — only when expanded */}
        {expanded && searchItems.length > 0 ? (
          <SearchResultWidget items={searchItems} />
        ) : null}
        {expanded && searchItems.length === 0 && resultLine ? (
          <div className="tool-strip__result">{resultLine}</div>
        ) : null}

        {/* Phase 35 — inner toggle button removed; header itself toggles
            `expanded` (clickable). technicalDetail renders inline when
            expanded for tools that have raw output (e.g. python script). */}
        {expanded && technicalDetail && (
          <div
            className="tool-strip__detail"
            role="region"
            aria-label={detailLabel || "Chi tiết kỹ thuật"}
          >
            <pre className="tool-strip__detail-pre">
              <code>{technicalDetail}</code>
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}

export function summarizeToolExecutionBlock(block: ToolExecutionBlockData) {
  const toolName = block.tool.name;
  const label =
    TOOL_LABELS[toolName] || toolName.replace(/^tool_/, "").replace(/_/g, " ");
  const argsLine = summarizeArgs(toolName, block.tool.args);
  const summary = summarizeResult(toolName, block.tool.result, block.tool.args);
  const resultLine =
    normalizeForCompare(summary.line) === normalizeForCompare(argsLine)
      ? ""
      : summary.line;
  return {
    label,
    argsLine,
    resultLine,
    technicalDetail: summary.technicalDetail,
    detailLabel: summary.detailLabel,
    isPending: block.status === "pending",
    Icon: resolveToolExecutionIcon(toolName),
  };
}
