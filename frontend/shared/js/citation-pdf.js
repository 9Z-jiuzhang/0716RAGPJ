/**
 * 内联引用 [N]：hover 卡片 + 有页码时新标签打开 PDF。
 * PDF 经 /qa/documents/{id}/file 鉴权拉取（与图表同源），再 blob + #page=N。
 */

import { getAccessToken, getGuestId } from "/assets/js/auth.js?v=gap-opt-0721i";
import { buildQaDocumentFileUrl } from "/assets/js/citation-urls.js?v=cite-pdf-4c";

const HOVER_CARD_ID = "cite-hover-card";

export function citationPrimaryPage(citation) {
  const direct = Number(citation?.page);
  if (Number.isFinite(direct) && direct > 0) return Math.floor(direct);
  for (const ref of citation?.chart_refs || []) {
    const p = Number(ref?.page);
    if (Number.isFinite(p) && p > 0) return Math.floor(p);
  }
  for (const img of citation?.images || []) {
    const p = Number(img?.page);
    if (Number.isFinite(p) && p > 0) return Math.floor(p);
  }
  return 0;
}

export function citationSnippet(citation, maxLen = 140) {
  const text = String(citation?.content || "")
    .replace(/\s+/g, " ")
    .trim();
  if (!text) return "";
  if (text.length <= maxLen) return text;
  return `${text.slice(0, maxLen)}…`;
}

export function indexCitationsByCiteIndex(citations) {
  const map = new Map();
  for (const c of citations || []) {
    const idx = Number(c?.cite_index);
    if (Number.isFinite(idx) && idx > 0) map.set(String(idx), c);
  }
  return map;
}

export function findCitationForIndex(root, citeIndex, citations) {
  const idx = String(citeIndex || "").trim();
  if (!idx) return null;
  if (citations instanceof Map) {
    const hit = citations.get(idx);
    if (hit) return hit;
  } else if (Array.isArray(citations)) {
    const hit = citations.find((c) => String(c?.cite_index) === idx);
    if (hit) return hit;
  }
  const row = root?.closest?.(".msg-row") || root;
  const item = row?.querySelector?.(`#citation-${idx}, .citation-item[data-citation-index="${idx}"]`);
  if (!item) return null;
  return {
    cite_index: Number(idx),
    doc_id: item.dataset.docId || "",
    doc_name: item.dataset.docName || "",
    page: Number(item.dataset.page) || 0,
    content: item.dataset.snippet || item.querySelector(".citation-content")?.textContent || "",
  };
}

function ensureHoverCard() {
  let el = document.getElementById(HOVER_CARD_ID);
  if (el) return el;
  el = document.createElement("div");
  el.id = HOVER_CARD_ID;
  el.className = "cite-hover-card";
  el.hidden = true;
  el.setAttribute("role", "tooltip");
  document.body.appendChild(el);
  return el;
}

export function hideCitationHoverCard() {
  const el = document.getElementById(HOVER_CARD_ID);
  if (el) el.hidden = true;
}

export function showCitationHoverCard(anchor, citation) {
  if (!anchor || !citation) return;
  const card = ensureHoverCard();
  const docName = String(citation.doc_name || "未知文档").trim() || "未知文档";
  const page = citationPrimaryPage(citation);
  const snippet = citationSnippet(citation);
  const pageLine = page > 0 ? `第 ${page} 页` : "页码未知";
  card.innerHTML = `
    <div class="cite-hover-card-title"></div>
    <div class="cite-hover-card-meta"></div>
    <div class="cite-hover-card-snippet"></div>
  `;
  card.querySelector(".cite-hover-card-title").textContent = docName;
  card.querySelector(".cite-hover-card-meta").textContent = pageLine;
  const sn = card.querySelector(".cite-hover-card-snippet");
  if (snippet) sn.textContent = snippet;
  else sn.remove();

  card.hidden = false;
  const rect = anchor.getBoundingClientRect();
  const pad = 8;
  const cw = card.offsetWidth || 280;
  const ch = card.offsetHeight || 80;
  let left = rect.left + rect.width / 2 - cw / 2;
  left = Math.max(pad, Math.min(left, window.innerWidth - cw - pad));
  let top = rect.bottom + 8;
  if (top + ch > window.innerHeight - pad) {
    top = Math.max(pad, rect.top - ch - 8);
  }
  card.style.left = `${Math.round(left)}px`;
  card.style.top = `${Math.round(top)}px`;
}

async function fetchPdfBlob(docId) {
  const url = buildQaDocumentFileUrl(docId);
  if (!url) throw new Error("缺少文档 ID");
  const headers = {
    "X-Guest-Id": getGuestId(),
    Accept: "application/pdf",
  };
  const token = getAccessToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(url, { headers });
  if (res.status === 415) {
    const err = new Error("NOT_PDF");
    err.code = "NOT_PDF";
    throw err;
  }
  if (!res.ok) {
    const err = new Error(`HTTP ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return await res.blob();
}

/** 鉴权拉取 PDF 并新标签打开；有页码时追加 #page=N。 */
export async function openCitationPdfInNewTab(citation, { page } = {}) {
  const docId = String(citation?.doc_id || "").trim();
  if (!docId) {
    const err = new Error("NO_DOC");
    err.code = "NO_DOC";
    throw err;
  }
  const targetPage = page != null ? Number(page) : citationPrimaryPage(citation);
  const blob = await fetchPdfBlob(docId);
  const objectUrl = URL.createObjectURL(blob);
  const hash = Number.isFinite(targetPage) && targetPage > 0 ? `#page=${Math.floor(targetPage)}` : "";
  const opened = window.open(`${objectUrl}${hash}`, "_blank", "noopener,noreferrer");
  window.setTimeout(() => {
    try {
      URL.revokeObjectURL(objectUrl);
    } catch {
      /* ignore */
    }
  }, 120_000);
  if (!opened) {
    const err = new Error("POPUP_BLOCKED");
    err.code = "POPUP_BLOCKED";
    throw err;
  }
  return true;
}

function scrollToCitationBlock(root, citeIndex) {
  const idx = String(citeIndex || "").trim();
  if (!idx) return false;
  const row = root?.closest?.(".msg-row") || root;
  const target = row?.querySelector?.(`#citation-${idx}, .citation-item[data-citation-index="${idx}"]`);
  if (!target) return false;
  target.scrollIntoView({ behavior: "smooth", block: "center" });
  if (target.tagName === "DETAILS") target.open = true;
  target.classList.add("citation-item--highlight");
  window.setTimeout(() => target.classList.remove("citation-item--highlight"), 2200);
  return true;
}

/**
 * 绑定内联 [N]：hover 浮层；有页码则新标签 PDF，否则滚到引用块。
 * @param {ParentNode} root
 * @param {object} opts
 * @param {Array|Map} [opts.citations]
 * @param {(msg:string, type?:string)=>void} [opts.toast]
 */
export function attachInlineCitationUx(root, { citations = null, toast = null } = {}) {
  if (!root) return;
  const map =
    citations instanceof Map ? citations : Array.isArray(citations) ? indexCitationsByCiteIndex(citations) : null;

  root.querySelectorAll(".inline-citation").forEach((btn) => {
    if (btn.dataset.inlineBound === "1") return;
    btn.dataset.inlineBound = "1";

    btn.addEventListener("mouseenter", () => {
      const idx = String(btn.dataset.citeIndex || "").trim();
      const citation = findCitationForIndex(root, idx, map);
      if (citation) showCitationHoverCard(btn, citation);
    });
    btn.addEventListener("mouseleave", () => hideCitationHoverCard());
    btn.addEventListener("focus", () => {
      const idx = String(btn.dataset.citeIndex || "").trim();
      const citation = findCitationForIndex(root, idx, map);
      if (citation) showCitationHoverCard(btn, citation);
    });
    btn.addEventListener("blur", () => hideCitationHoverCard());

    btn.addEventListener("click", async (event) => {
      event.preventDefault();
      hideCitationHoverCard();
      const idx = String(btn.dataset.citeIndex || "").trim();
      if (!idx) return;
      const citation = findCitationForIndex(root, idx, map);
      const page = citation ? citationPrimaryPage(citation) : 0;
      const canPdf = citation && String(citation.doc_id || "").trim() && page > 0;

      if (canPdf) {
        btn.classList.add("is-opening");
        try {
          await openCitationPdfInNewTab(citation, { page });
          return;
        } catch (err) {
          if (err?.code === "POPUP_BLOCKED") {
            toast?.("请允许浏览器弹窗以打开 PDF", "info");
          } else if (err?.code !== "NOT_PDF" && err?.status !== 415) {
            toast?.("无法打开 PDF，已定位到引用来源", "info");
          }
        } finally {
          btn.classList.remove("is-opening");
        }
      }
      if (!scrollToCitationBlock(root, idx)) {
        toast?.("未找到对应引用来源", "error");
      }
    });
  });
}

/** 引用条目上的「打开 PDF」按钮 */
export function attachCitationPdfOpenButtons(root, { toast = null } = {}) {
  if (!root) return;
  root.querySelectorAll("[data-open-pdf]").forEach((btn) => {
    if (btn.dataset.pdfBound === "1") return;
    btn.dataset.pdfBound = "1";
    btn.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      const citation = {
        doc_id: btn.dataset.docId || "",
        doc_name: btn.dataset.docName || "",
        page: Number(btn.dataset.page) || 0,
      };
      if (!citation.doc_id || !(citation.page > 0)) {
        toast?.("该引用无 PDF 页码", "info");
        return;
      }
      try {
        await openCitationPdfInNewTab(citation);
      } catch (err) {
        if (err?.code === "POPUP_BLOCKED") toast?.("请允许浏览器弹窗以打开 PDF", "info");
        else if (err?.code === "NOT_PDF" || err?.status === 415) toast?.("该文档不是 PDF", "info");
        else toast?.("打开 PDF 失败", "error");
      }
    });
  });
}
