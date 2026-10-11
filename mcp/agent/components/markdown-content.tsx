"use client";

/**
 * Shared markdown renderer for KB entry bodies + chat assistant
 * messages. Built around `react-markdown` with custom component
 * overrides matching the Ocean Navy + glassmorphism aesthetic.
 * Code blocks (fenced ```lang ... ```) get syntax highlighting via
 * `react-syntax-highlighter` using the Prism light bundle — only the
 * languages we explicitly import get loaded, keeping bundle size in
 * check.
 *
 * Why a shared component:
 *
 * The KB entry drawer and chat assistant messages both present
 * markdown, and must show it the same way (headings, code blocks,
 * lists) rather than two different stories about how the same
 * markdown looks.
 *
 * The light Prism bundle imports only sql, python, bash, json,
 * typescript languages (chat output is ~90% SQL/XQL from the
 * build_xql_query skill, then Python/bash for ad-hoc snippets, then
 * JSON for tool result payloads). Adding new languages = one import
 * + register call below.
 *
 * Theme: vsDark with our color overrides — dark background matches
 * surface-container-lowest, primary-tint border matches the
 * tertiary-tint inline-code style for visual cohesion across the
 * markdown surface.
 */

import ReactMarkdown from "react-markdown";
import { PrismLight as SyntaxHighlighter } from "react-syntax-highlighter";
import sql from "react-syntax-highlighter/dist/esm/languages/prism/sql";
import python from "react-syntax-highlighter/dist/esm/languages/prism/python";
import bash from "react-syntax-highlighter/dist/esm/languages/prism/bash";
import json from "react-syntax-highlighter/dist/esm/languages/prism/json";
import typescript from "react-syntax-highlighter/dist/esm/languages/prism/typescript";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";

// Register once at module load — supported language set.
SyntaxHighlighter.registerLanguage("sql", sql);
SyntaxHighlighter.registerLanguage("xql", sql); // XQL ≈ SQL dialect
SyntaxHighlighter.registerLanguage("python", python);
SyntaxHighlighter.registerLanguage("py", python);
SyntaxHighlighter.registerLanguage("bash", bash);
SyntaxHighlighter.registerLanguage("sh", bash);
SyntaxHighlighter.registerLanguage("shell", bash);
SyntaxHighlighter.registerLanguage("json", json);
SyntaxHighlighter.registerLanguage("typescript", typescript);
SyntaxHighlighter.registerLanguage("ts", typescript);
SyntaxHighlighter.registerLanguage("javascript", typescript);
SyntaxHighlighter.registerLanguage("js", typescript);

const LANG_RE = /language-(\w+)/;

interface MarkdownContentProps {
  children: string;
  /**
   * When true, the renderer assumes the content is sourced from a
   * streaming context (chat assistant) and tightens vertical rhythm
   * to match dense bubble layouts. When false (KB drawer), it uses
   * standard spacing.
   */
  compact?: boolean;
}

export function MarkdownContent({
  children,
  compact = false,
}: MarkdownContentProps) {
  // The spacing tier. KB drawer (`compact: false`) gives
  // each block element generous breathing room because the operator
  // is reading + inspecting individual entries. Chat (`compact: true`)
  // tightens because the bubble itself is the visual frame and we
  // don't want a multi-paragraph answer to feel like a wall of air.
  const space = compact ? "space-y-2" : "space-y-3";
  const headingTop = compact ? "mt-3" : "mt-4";

  return (
    <div className={`${space} text-on-surface leading-relaxed`}>
      <ReactMarkdown
        components={{
          h1: ({ children: c }) => (
            <h1 className="text-base font-headline font-bold text-on-surface mb-2 pb-1 border-b border-white/5">
              {c}
            </h1>
          ),
          h2: ({ children: c }) => (
            <h2
              className={`text-sm font-headline font-semibold text-primary ${headingTop} mb-1.5 uppercase tracking-wider`}
            >
              {c}
            </h2>
          ),
          h3: ({ children: c }) => (
            <h3
              className={`text-sm font-headline font-medium text-secondary ${headingTop} mb-1`}
            >
              {c}
            </h3>
          ),
          p: ({ children: c }) => (
            <p className="text-sm text-on-surface-variant leading-relaxed">
              {c}
            </p>
          ),
          strong: ({ children: c }) => (
            <strong className="font-semibold text-on-surface">{c}</strong>
          ),
          em: ({ children: c }) => (
            <em className="text-on-surface-variant/80">{c}</em>
          ),
          code: ({ children: c, className }) => {
            // react-markdown passes the fenced language as className
            // (e.g. "language-sql"). When className is undefined the
            // node is an inline `code` span — render as a small pill.
            const match = (className || "").match(LANG_RE);
            const inline = !match;
            if (inline) {
              return (
                <code className="font-mono text-[12px] px-1.5 py-0.5 rounded bg-tertiary/15 text-tertiary">
                  {c}
                </code>
              );
            }
            // Block-level — the parent `pre` override handles the
            // wrapper; we render the highlighted body directly.
            // SyntaxHighlighter wants the raw string, not React
            // children — flatten.
            const codeString = String(c).replace(/\n$/, "");
            return (
              <SyntaxHighlighter
                language={match[1]}
                style={vscDarkPlus}
                customStyle={{
                  background: "var(--m3-surface-container-lowest, #0f0a2e)",
                  margin: 0,
                  padding: "12px 14px",
                  borderRadius: "8px",
                  fontSize: "12px",
                  lineHeight: 1.55,
                  border: "0.5px solid rgba(167, 200, 255, 0.2)",
                }}
                codeTagProps={{
                  style: { fontFamily: "var(--font-mono), ui-monospace, monospace" },
                }}
                PreTag="div"
              >
                {codeString}
              </SyntaxHighlighter>
            );
          },
          // Block-level <pre> from react-markdown wraps the highlighted
          // block above. Strip its wrapper so SyntaxHighlighter's
          // styling owns the visual.
          pre: ({ children: c }) => <>{c}</>,
          ul: ({ children: c }) => (
            <ul className="list-disc list-inside text-sm text-on-surface-variant space-y-1 ml-2">
              {c}
            </ul>
          ),
          ol: ({ children: c }) => (
            <ol className="list-decimal list-inside text-sm text-on-surface-variant space-y-1 ml-2">
              {c}
            </ol>
          ),
          li: ({ children: c }) => (
            <li className="text-sm text-on-surface-variant">{c}</li>
          ),
          a: ({ children: c, href }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary hover:underline"
            >
              {c}
            </a>
          ),
          hr: () => <hr className="border-white/5 my-3" />,
          blockquote: ({ children: c }) => (
            <blockquote className="border-l-2 border-primary/40 pl-3 italic text-on-surface-variant/85 text-sm">
              {c}
            </blockquote>
          ),
          table: ({ children: c }) => (
            <div className="overflow-x-auto">
              <table className="text-xs border-collapse w-full my-2">
                {c}
              </table>
            </div>
          ),
          thead: ({ children: c }) => (
            <thead className="border-b border-white/10">{c}</thead>
          ),
          th: ({ children: c }) => (
            <th className="text-left px-2 py-1.5 font-semibold text-on-surface font-headline text-[11px] uppercase tracking-wider">
              {c}
            </th>
          ),
          td: ({ children: c }) => (
            <td className="px-2 py-1.5 text-on-surface-variant border-b border-white/5">
              {c}
            </td>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
