/**
 * Tiny, safe Markdown renderer for assistant answers.
 * Supports: paragraphs, #-headings, bullet / numbered lists (one nesting level), **bold**,
 * *italic*, `inline code`, fenced code blocks, > quotes, pipe tables, [text](link) and
 * auto-links for run / trace / test-run / alert ids.
 * Everything is emitted as React elements - text is never injected as HTML.
 */
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

const TRACE_RE = /^[0-9a-f]{32}$/;
const RUN_RE = /^R-[0-9a-f]{6}-\d{3,}$/;
const TR_RE = /^TR-\d{8}-[0-9a-f]{6}$/;
const ALERT_RE = /^A-[0-9a-f]{16}$/;

/** Internal route for a known id, or null. */
export function idHref(id: string): string | null {
  if (TRACE_RE.test(id) || RUN_RE.test(id)) return `/runs/${id}`;
  if (TR_RE.test(id)) return `/testing?run=${encodeURIComponent(id)}`;
  if (ALERT_RE.test(id)) return `/anomalies?alert=${encodeURIComponent(id)}`;
  return null;
}

function safeHref(url: string): { internal: boolean; href: string } | null {
  const u = url.trim();
  if (u.startsWith("/") && !u.startsWith("//")) return { internal: true, href: u };
  if (/^https?:\/\//i.test(u)) return { internal: false, href: u };
  return null; // javascript:, data:, etc. are dropped
}

// Inline tokens: code, bold, italic, link, ids.
const INLINE =
  /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(__[^_\n]+__)|(\*[^*\s][^*\n]*\*)|(\[[^\]\n]+\]\([^)\s]+\))|(\b[0-9a-f]{32}\b)|(\bR-[0-9a-f]{6}-\d{3,}\b)|(\bTR-\d{8}-[0-9a-f]{6}\b)|(\bA-[0-9a-f]{16}\b)/g;

export function renderInline(text: string, keyPrefix = "i"): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  let k = 0;
  const re = new RegExp(INLINE.source, "g"); // fresh regex: renderInline recurses for bold/italic
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    const key = `${keyPrefix}-${k++}`;
    if (m[1]) {
      const inner = tok.slice(1, -1);
      const href = idHref(inner);
      const code = <code className="mono rounded bg-surface-2 px-1 py-px text-ink">{inner}</code>;
      out.push(
        href ? (
          <Link key={key} to={href} className="link">
            {code}
          </Link>
        ) : (
          <span key={key}>{code}</span>
        ),
      );
    } else if (m[2] || m[3]) {
      out.push(
        <strong key={key} className="font-semibold text-ink">
          {renderInline(tok.slice(2, -2), key)}
        </strong>,
      );
    } else if (m[4]) {
      out.push(<em key={key}>{renderInline(tok.slice(1, -1), key)}</em>);
    } else if (m[5]) {
      const lm = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(tok);
      const target = lm ? safeHref(lm[2]) : null;
      if (lm && target) {
        out.push(
          target.internal ? (
            <Link key={key} to={target.href} className="link">
              {lm[1]}
            </Link>
          ) : (
            <a key={key} href={target.href} className="link" target="_blank" rel="noopener noreferrer">
              {lm[1]}
            </a>
          ),
        );
      } else out.push(lm ? lm[1] : tok);
    } else {
      const href = idHref(tok);
      out.push(
        href ? (
          <Link key={key} to={href} className="link mono">
            {tok}
          </Link>
        ) : (
          tok
        ),
      );
    }
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

type Block =
  | { t: "p"; text: string }
  | { t: "h"; level: number; text: string }
  | { t: "ul" | "ol"; items: { text: string; sub: string[] }[] }
  | { t: "code"; text: string }
  | { t: "quote"; text: string }
  | { t: "table"; head: string[]; rows: string[][] }
  | { t: "hr" };

const splitRow = (line: string) =>
  line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((c) => c.trim());

export function parseMarkdown(src: string): Block[] {
  const lines = src.replace(/\r\n?/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;
  const isBullet = (l: string) => /^\s*[-*+]\s+/.test(l);
  const isNum = (l: string) => /^\s*\d+[.)]\s+/.test(l);
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    if (/^\s*```/.test(line)) {
      const buf: string[] = [];
      i++;
      while (i < lines.length && !/^\s*```/.test(lines[i])) buf.push(lines[i++]);
      i++;
      blocks.push({ t: "code", text: buf.join("\n") });
      continue;
    }
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) {
      blocks.push({ t: "h", level: h[1].length, text: h[2] });
      i++;
      continue;
    }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) {
      blocks.push({ t: "hr" });
      i++;
      continue;
    }
    if (/^\s*\|/.test(line) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
      const head = splitRow(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(splitRow(lines[i++]));
      blocks.push({ t: "table", head, rows });
      continue;
    }
    if (/^\s*>/.test(line)) {
      const buf: string[] = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) buf.push(lines[i++].replace(/^\s*>\s?/, ""));
      blocks.push({ t: "quote", text: buf.join(" ") });
      continue;
    }
    if (isBullet(line) || isNum(line)) {
      const ordered = isNum(line);
      const items: { text: string; sub: string[] }[] = [];
      const baseIndent = line.match(/^\s*/)![0].length;
      while (i < lines.length && lines[i].trim() && (isBullet(lines[i]) || isNum(lines[i]) || /^\s{2,}\S/.test(lines[i]))) {
        const l = lines[i];
        const indent = l.match(/^\s*/)![0].length;
        // a top-level item of the other list type starts a new list
        if (indent <= baseIndent && (ordered ? isBullet(l) : isNum(l))) break;
        const content = l.replace(/^\s*([-*+]|\d+[.)])\s+/, "");
        if (indent > baseIndent && items.length && (isBullet(l) || isNum(l))) items[items.length - 1].sub.push(content);
        else if (isBullet(l) || isNum(l)) items.push({ text: content, sub: [] });
        else if (items.length) items[items.length - 1].text += " " + l.trim();
        i++;
      }
      blocks.push({ t: ordered ? "ol" : "ul", items });
      continue;
    }
    const buf: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^\s*```/.test(lines[i]) &&
      !/^#{1,4}\s/.test(lines[i]) &&
      !isBullet(lines[i]) &&
      !isNum(lines[i]) &&
      !/^\s*\|/.test(lines[i]) &&
      !/^\s*>/.test(lines[i])
    )
      buf.push(lines[i++].trim());
    blocks.push({ t: "p", text: buf.join(" ") });
  }
  return blocks;
}

export function Markdown({ text }: { text: string }) {
  const blocks = parseMarkdown(text ?? "");
  return (
    <div className="flex flex-col gap-2 text-sm leading-relaxed text-ink">
      {blocks.map((b, bi) => {
        const k = `b${bi}`;
        switch (b.t) {
          case "h": {
            const cls = b.level <= 2 ? "text-base font-semibold" : "text-sm font-semibold";
            return (
              <div key={k} role="heading" aria-level={Math.min(6, b.level + 2)} className={`${cls} mt-1 text-ink`}>
                {renderInline(b.text, k)}
              </div>
            );
          }
          case "p":
            return <p key={k}>{renderInline(b.text, k)}</p>;
          case "hr":
            return <hr key={k} className="border-line" />;
          case "code":
            return (
              <pre key={k} className="mono overflow-auto rounded-md border border-line bg-surface-2 p-2 text-ink">
                {b.text}
              </pre>
            );
          case "quote":
            return (
              <blockquote key={k} className="border-l-2 border-line-strong pl-3 text-ink-2">
                {renderInline(b.text, k)}
              </blockquote>
            );
          case "ul":
          case "ol": {
            const Tag = b.t;
            return (
              <Tag key={k} className={`${b.t === "ul" ? "list-disc" : "list-decimal"} flex flex-col gap-0.5 pl-5`}>
                {b.items.map((it, ii) => (
                  <li key={ii}>
                    {renderInline(it.text, `${k}-${ii}`)}
                    {it.sub.length > 0 && (
                      <ul className="list-[circle] pl-5">
                        {it.sub.map((s, si) => (
                          <li key={si}>{renderInline(s, `${k}-${ii}-${si}`)}</li>
                        ))}
                      </ul>
                    )}
                  </li>
                ))}
              </Tag>
            );
          }
          case "table":
            return (
              <div key={k} className="overflow-auto rounded-md border border-line">
                <table className="w-full border-collapse text-left text-xs">
                  <thead className="bg-surface-2">
                    <tr>
                      {b.head.map((h, hi) => (
                        <th key={hi} scope="col" className="border-b border-line px-2 py-1 font-medium text-ink-2">
                          {renderInline(h, `${k}-h${hi}`)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {b.rows.map((r, ri) => (
                      <tr key={ri} className="border-b border-line/60 last:border-b-0">
                        {r.map((c, ci) => (
                          <td key={ci} className={`px-2 py-1 ${/^[-+$]?[\d,.]+%?$/.test(c) ? "num text-right" : ""}`}>
                            {renderInline(c, `${k}-${ri}-${ci}`)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
        }
      })}
    </div>
  );
}
