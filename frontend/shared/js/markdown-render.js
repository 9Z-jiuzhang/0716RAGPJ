/**
 * 安全 Markdown 渲染（问答答案区）。
 * 流式阶段用纯文本，done 后再渲染 MD，避免 ** 闪烁。
 */

import { escapeHtml } from "/assets/js/utils.js?v=gap-opt-0721i";

const SAFE_URL = /^(https?:|mailto:|#)/i;

function safeUrl(raw) {
  const url = String(raw || "").trim();
  if (!url || !SAFE_URL.test(url)) return null;
  return escapeHtml(url);
}

/** 行内：code / bold / italic / link / [N] 引用 */
function renderInline(text, { inlineCitations = false } = {}) {
  const src = String(text || "");
  if (!src) return "";

  const parts = [];
  const re = inlineCitations
    ? /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\([^)]+\)|\[\d{1,2}\])/g
    : /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\([^)]+\))/g;
  let last = 0;
  let m;
  while ((m = re.exec(src)) !== null) {
    if (m.index > last) {
      parts.push(escapeHtml(src.slice(last, m.index)));
    }
    const token = m[0];
    if (token.startsWith("`") && token.endsWith("`")) {
      parts.push(`<code>${escapeHtml(token.slice(1, -1))}</code>`);
    } else if (token.startsWith("**") && token.endsWith("**")) {
      parts.push(`<strong>${escapeHtml(token.slice(2, -2))}</strong>`);
    } else if (token.startsWith("*") && token.endsWith("*")) {
      parts.push(`<em>${escapeHtml(token.slice(1, -1))}</em>`);
    } else if (inlineCitations && /^\[\d{1,2}\]$/.test(token)) {
      const idx = token.slice(1, -1);
      parts.push(
        `<button type="button" class="inline-citation" data-cite-index="${escapeHtml(idx)}" aria-label="引用 ${escapeHtml(idx)}">${escapeHtml(token)}</button>`
      );
    } else if (token.startsWith("[")) {
      const lm = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      if (lm) {
        const href = safeUrl(lm[2]);
        const label = escapeHtml(lm[1]);
        parts.push(href ? `<a href="${href}" rel="noopener noreferrer" target="_blank">${label}</a>` : label);
      } else {
        parts.push(escapeHtml(token));
      }
    } else {
      parts.push(escapeHtml(token));
    }
    last = m.index + token.length;
  }
  if (last < src.length) {
    parts.push(escapeHtml(src.slice(last)));
  }
  return parts.join("");
}

/** 纯文本答案中的 [N] → 可点击按钮（Markdown 关闭时） */
export function renderPlainWithInlineCitations(text) {
  const src = String(text || "");
  if (!src) return "";
  const re = /(\[\d{1,2}\])/g;
  const parts = [];
  let last = 0;
  let m;
  while ((m = re.exec(src)) !== null) {
    if (m.index > last) {
      parts.push(escapeHtml(src.slice(last, m.index)));
    }
    const token = m[1];
    const idx = token.slice(1, -1);
    parts.push(
      `<button type="button" class="inline-citation" data-cite-index="${escapeHtml(idx)}" aria-label="引用 ${escapeHtml(idx)}">${escapeHtml(token)}</button>`
    );
    last = m.index + token.length;
  }
  if (last < src.length) {
    parts.push(escapeHtml(src.slice(last)));
  }
  return parts.join("");
}

function isTableDivider(line) {
  const t = String(line || "").trim();
  if (!t.includes("|")) return false;
  return /^[\s|:-]+$/.test(t.replace(/\|/g, ""));
}

function parseTableRow(line) {
  const trimmed = String(line || "").trim().replace(/^\|/, "").replace(/\|$/, "");
  return trimmed.split("|").map((c) => c.trim());
}

/**
 * @param {string} text
 * @param {{ streaming?: boolean, inlineCitations?: boolean }} opts
 */
export function renderMarkdownSafe(text, { streaming = false, inlineCitations = false } = {}) {
  const raw = String(text || "");
  if (!raw) return "";
  if (streaming) return escapeHtml(raw);

  const lines = raw.replace(/\r\n/g, "\n").split("\n");
  const out = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (line.trim().startsWith("```")) {
      const buf = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        buf.push(lines[i]);
        i += 1;
      }
      if (i < lines.length) i += 1;
      out.push(`<pre><code>${escapeHtml(buf.join("\n"))}</code></pre>`);
      continue;
    }

    if (line.includes("|") && i + 1 < lines.length && isTableDivider(lines[i + 1])) {
      const headerCells = parseTableRow(line);
      i += 2;
      const bodyRows = [];
      while (i < lines.length && lines[i].includes("|") && !isTableDivider(lines[i])) {
        if (lines[i].trim()) bodyRows.push(parseTableRow(lines[i]));
        i += 1;
      }
      const head = headerCells.map((h) => `<th>${renderInline(h, { inlineCitations })}</th>`).join("");
      const body = bodyRows
        .map((row) => `<tr>${row.map((c) => `<td>${renderInline(c, { inlineCitations })}</td>`).join("")}</tr>`)
        .join("");
      out.push(`<div class="md-table-wrap"><table class="md-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`);
      continue;
    }

    const hm = line.match(/^(#{1,4})\s+(.*)$/);
    if (hm) {
      const level = hm[1].length;
      out.push(`<h${level}>${renderInline(hm[2], { inlineCitations })}</h${level}>`);
      i += 1;
      continue;
    }

    if (/^[\s]*[-*]\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^[\s]*[-*]\s+/.test(lines[i])) {
        items.push(`<li>${renderInline(lines[i].replace(/^[\s]*[-*]\s+/, ""), { inlineCitations })}</li>`);
        i += 1;
      }
      out.push(`<ul>${items.join("")}</ul>`);
      continue;
    }

    if (/^[\s]*\d+\.\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^[\s]*\d+\.\s+/.test(lines[i])) {
        items.push(`<li>${renderInline(lines[i].replace(/^[\s]*\d+\.\s+/, ""), { inlineCitations })}</li>`);
        i += 1;
      }
      out.push(`<ol>${items.join("")}</ol>`);
      continue;
    }

    if (!line.trim()) {
      i += 1;
      continue;
    }

    out.push(`<p>${renderInline(line, { inlineCitations })}</p>`);
    i += 1;
  }

  return out.join("");
}
