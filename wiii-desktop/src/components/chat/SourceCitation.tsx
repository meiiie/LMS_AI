/**
 * SourceCitation — clickable source badges.
 * Sprint 107: Badges now open SourcesPanel with the selected source.
 * Sprint 211: Badge color overhaul — accent-based, bordered, refined hover.
 * Sprint 233: Compact list layout, 3 visible by default, "+N" expandable.
 */
import { useState } from "react";
import { ChevronDown, ExternalLink, Globe } from "lucide-react";
import type { SourceInfo } from "@/api/types";
import { useUIStore } from "@/stores/ui-store";

const MAX_VISIBLE = 3;
const SAFE_URL_PROTOCOLS = new Set(["http:", "https:", "mailto:", "tel:"]);

interface SourceCitationProps {
  sources: SourceInfo[];
}

export function SourceCitation({ sources }: SourceCitationProps) {
  const { selectSource, sourcesPanelOpen, toggleSourcesPanel } = useUIStore();
  const [showAll, setShowAll] = useState(false);

  if (!sources || sources.length === 0) return null;

  const allWebSources = sources.every(isWebSource);
  if (allWebSources) {
    return <WebSourceCitation sources={sources} />;
  }

  const handleClick = (index: number) => {
    selectSource(index);
    if (!sourcesPanelOpen) {
      toggleSourcesPanel();
    }
  };

  const visibleSources = showAll ? sources : sources.slice(0, MAX_VISIBLE);
  const hiddenCount = sources.length - MAX_VISIBLE;

  return (
    <div className="source-citation">
      <div className="source-citation__header">
        Nguồn tham khảo
      </div>
      <div className="source-citation__list">
        {visibleSources.map((source, i) => {
          const safeUrl = safeSourceUrl(source.url);
          const body = (
            <>
              <span className="source-citation__index">[{i + 1}]</span>
              <span className="source-citation__title">{source.title}</span>
              {source.page_number && (
                <span className="source-citation__page">
                  tr. {source.page_number}
                </span>
              )}
              {safeUrl && <ExternalLink size={12} aria-hidden="true" />}
            </>
          );
          if (safeUrl) {
            return (
              <a
                key={`${safeUrl}-${i}`}
                href={safeUrl}
                target="_blank"
                rel="noreferrer noopener"
                className="source-citation__item"
                title={source.title}
              >
                {body}
              </a>
            );
          }
          return (
            <button
              key={i}
              onClick={() => handleClick(i)}
              className="source-citation__item"
              title={source.title}
            >
              {body}
            </button>
          );
        })}
      </div>
      {!showAll && hiddenCount > 0 && (
        <button
          onClick={() => setShowAll(true)}
          className="source-citation__expand"
          aria-label={`Xem thêm ${hiddenCount} nguồn`}
        >
          +{hiddenCount} thêm...
        </button>
      )}
      {showAll && sources.length > MAX_VISIBLE && (
        <button
          onClick={() => setShowAll(false)}
          className="source-citation__expand"
          aria-label="Thu gọn danh sách nguồn"
        >
          Thu gọn
        </button>
      )}
    </div>
  );
}

function WebSourceCitation({ sources }: SourceCitationProps) {
  const [expanded, setExpanded] = useState(false);
  const visibleSources = expanded ? sources : sources.slice(0, 3);
  const domains = sources
    .map((source) => domainLabel(safeSourceUrl(source.url)))
    .filter(Boolean)
    .slice(0, 3);

  return (
    <div className="web-source-citation" data-testid="web-source-citation">
      <button
        type="button"
        className="web-source-citation__summary"
        data-testid="web-source-citation-summary"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
      >
        <span className="web-source-citation__title">
          <Globe size={14} />
          {sources.length} nguồn web
        </span>
        {domains.length > 0 && (
          <span className="web-source-citation__domains">
            {domains.join(", ")}
          </span>
        )}
        <ChevronDown
          size={14}
          className={`web-source-citation__chevron ${expanded ? "web-source-citation__chevron--open" : ""}`}
        />
      </button>

      {expanded && (
        <div className="web-source-citation__list">
          {visibleSources.map((source, index) => {
            const url = safeSourceUrl(source.url);
            const domain = domainLabel(url);
            const body = (
              <>
                <span className="web-source-citation__index">
                  {index + 1}
                </span>
                <span className="web-source-citation__body">
                  <span className="web-source-citation__item-title">
                    {source.title}
                  </span>
                  <span className="web-source-citation__item-meta">
                    {domain || source.content}
                  </span>
                </span>
                {url && <ExternalLink size={12} />}
              </>
            );
            if (!url) {
              return (
                <div
                  key={`${source.title}-${index}`}
                  className="web-source-citation__item"
                >
                  {body}
                </div>
              );
            }
            return (
              <a
                key={`${url || source.title}-${index}`}
                href={url}
                target="_blank"
                rel="noreferrer noopener"
                className="web-source-citation__item"
              >
                {body}
              </a>
            );
          })}
        </div>
      )}
    </div>
  );
}

function isWebSource(source: SourceInfo): boolean {
  return source.source_type === "web" || Boolean(safeSourceUrl(source.url));
}

function safeSourceUrl(url: string | undefined): string {
  if (!url) return "";
  try {
    const parsed = new URL(url);
    return SAFE_URL_PROTOCOLS.has(parsed.protocol) ? parsed.href : "";
  } catch {
    return "";
  }
}

function domainLabel(url: string): string {
  if (!url) return "";
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}
