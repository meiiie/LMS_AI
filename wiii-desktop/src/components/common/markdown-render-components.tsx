import { type ReactNode, lazy, Suspense } from "react";

const MermaidDiagram = lazy(() => import("./MermaidDiagram"));
const InlineHtmlWidget = lazy(() => import("./InlineHtmlWidget"));
const LazyCodeBlock = lazy(async () => {
  const mod = await import("./CodeBlock");
  return { default: mod.CodeBlock };
});

function extractText(node: ReactNode): string {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string") return node;
  if (typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(extractText).join("");
  if (typeof node === "object" && "props" in node) {
    return extractText((node as { props: { children?: ReactNode } }).props.children);
  }
  return "";
}

// Phase 35 — citation chip render for inline markdown links to web sources.
// Pattern (Perplexity 2026): each external link rendered as a compact
// rounded chip with favicon + domain. Hover shows full URL via title attr.
function CitationLink({ href, children, title }: { href?: string; children?: ReactNode; title?: string }) {
  if (!href || !/^https?:\/\//i.test(href)) {
    // Internal anchor / non-URL → render as plain link
    return (
      <a href={href} title={title} className="underline decoration-dotted underline-offset-2 hover:text-[var(--accent)]">
        {children}
      </a>
    );
  }
  let domain = "";
  try {
    domain = new URL(href).hostname.replace(/^www\./, "");
  } catch {
    /* malformed URL — fall through */
  }
  const faviconUrl = domain ? `https://www.google.com/s2/favicons?domain=${domain}&sz=32` : "";
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      title={title || href}
      className="citation-chip group/citation"
    >
      {faviconUrl && (
        <img
          src={faviconUrl}
          alt=""
          width={12}
          height={12}
          className="citation-chip__favicon"
          loading="lazy"
          referrerPolicy="no-referrer"
        />
      )}
      <span className="citation-chip__text">{children}</span>
    </a>
  );
}

export const markdownRenderComponents = {
  a: CitationLink,
  code({ className: codeClassName, children, ...props }: {
    className?: string;
    children?: ReactNode;
  }) {
    const match = /language-(\w+)/.exec(codeClassName || "");
    const isInline = !match;

    if (isInline) {
      return (
        <code className={codeClassName} {...props}>
          {children}
        </code>
      );
    }

    const rawCode = extractText(children).replace(/\n$/, "");

    if (match[1] === "mermaid") {
      return (
        <Suspense fallback={<pre className="p-4 bg-gray-100 dark:bg-gray-800 rounded-lg text-sm"><code>{rawCode}</code></pre>}>
          <MermaidDiagram code={rawCode} />
        </Suspense>
      );
    }

    if (match[1] === "widget") {
      return (
        <Suspense fallback={<div className="p-4 bg-gray-100 dark:bg-gray-800 rounded-lg text-sm animate-pulse">Đang tải widget...</div>}>
          <InlineHtmlWidget code={rawCode} />
        </Suspense>
      );
    }

    return (
      <Suspense
        fallback={(
          <pre className="my-2 overflow-x-auto rounded-lg border border-[var(--border)] bg-white/50 p-4">
            <code className="text-sm font-mono leading-relaxed">{rawCode}</code>
          </pre>
        )}
      >
        <LazyCodeBlock language={match[1] || ""} code={rawCode} />
      </Suspense>
    );
  },
};
