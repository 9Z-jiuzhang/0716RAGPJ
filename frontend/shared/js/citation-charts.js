/**
 * 引用图表：chart_refs 收集/去重、折叠 HTML、鉴权拉图、交互绑定。
 */

import { getAccessToken, getGuestId } from "/assets/js/auth.js?v=gap-opt-0721i";
import {
  buildChartAssetUrl,
  buildChartPageUrl,
  resolveChartFetchUrl,
} from "/assets/js/citation-urls.js?v=chart-p2b";

function revokeBlobUrl(url) {
  const raw = String(url || "").trim();
  if (!raw.startsWith("blob:")) return;
  try {
    URL.revokeObjectURL(raw);
  } catch {
    /* ignore */
  }
}

function revokeImgBlob(img) {
  if (!img) return;
  const prev = img.dataset.blobUrl || "";
  if (prev) revokeBlobUrl(prev);
  delete img.dataset.blobUrl;
}

export function collectAndDedupeCharts(citations, maxCharts = 8) {
  const coveredPages = new Set();
  const seenKeys = new Set();
  const charts = [];
  const limit = Math.max(1, Number(maxCharts) || 8);

  const markPage = (docId, page) => {
    if (page > 0 && docId) coveredPages.add(`${docId}:${page}`);
  };

  const isPageCovered = (docId, page) => page > 0 && docId && coveredPages.has(`${docId}:${page}`);

  const tryPush = (item) => {
    const key = item?.dedupKey;
    if (!item?.url || !key || seenKeys.has(key)) return true;
    seenKeys.add(key);
    charts.push(item);
    return charts.length < limit;
  };

  for (const c of citations || []) {
    const docId = String(c?.doc_id || "").trim();
    const docName = c?.doc_name || "文档";
    const refs = c?.chart_refs;
    const hasRefs = Array.isArray(refs) && refs.length > 0;

    if (hasRefs) {
      for (const ref of refs) {
        const kind = String(ref?.kind || "").trim();
        if (kind === "asset") {
          const assetId = String(ref?.asset_id || "").trim();
          if (!assetId || !docId) continue;
          const page = Number(ref?.page) || 0;
          const caption = String(ref?.caption || "").trim();
          const url = buildChartAssetUrl(docId, assetId);
          markPage(docId, page);
          if (!tryPush({
            url,
            page,
            docId,
            docName,
            kind: "asset",
            assetId,
            caption,
            dedupKey: `asset:${docId}:${assetId}`,
          })) {
            return charts;
          }
        } else if (kind === "page") {
          const page = Number(ref?.page) || 0;
          if (!page || !docId) continue;
          if (isPageCovered(docId, page)) continue;
          const url = buildChartPageUrl(docId, page);
          markPage(docId, page);
          if (!tryPush({
            url,
            page,
            docId,
            docName,
            kind: "page",
            assetId: "",
            caption: "",
            dedupKey: `page:${docId}:${page}`,
          })) {
            return charts;
          }
        }
      }
    } else {
      for (const img of c?.images || []) {
        const url = resolveChartFetchUrl(img?.url);
        if (!url) continue;
        const page = Number(img?.page) || 0;
        const kind = String(img?.kind || "").trim() || (img?.asset_id ? "asset" : "page");
        const assetId = String(img?.asset_id || "").trim();
        const caption = String(img?.caption || "").trim();
        if (kind === "asset") {
          markPage(docId, page);
          if (
            !tryPush({
              url,
              page,
              docId,
              docName,
              kind: "asset",
              assetId,
              caption,
              dedupKey: `asset:${docId}:${assetId || url}`,
            })
          ) {
            return charts;
          }
        } else {
          if (isPageCovered(docId, page)) continue;
          markPage(docId, page);
          if (
            !tryPush({
              url,
              page,
              docId,
              docName,
              kind: "page",
              assetId: "",
              caption: caption,
              dedupKey: `page:${docId}:${page || url}`,
            })
          ) {
            return charts;
          }
        }
      }
    }
  }
  return charts;
}

export function chartPageLabel(chart) {
  if (chart.kind === "asset") {
    return chart.caption || (chart.assetId ? `内嵌图 ${chart.assetId}` : "内嵌图");
  }
  return chart.page ? `PDF 第 ${chart.page} 页` : "图表";
}

export function buildCitationChartsHtml(citations, maxCharts, escapeHtml) {
  const charts = collectAndDedupeCharts(citations, maxCharts);
  const citationList = citations || [];
  if (!charts.length) {
    if (!citationList.length) return "";
    const anyMedia = citationList.some(
      (c) => (Array.isArray(c?.chart_refs) && c.chart_refs.length) || (Array.isArray(c?.images) && c.images.length)
    );
    if (!anyMedia) {
      return `<div class="citation-charts-fallback">
        <button type="button" class="citation-charts-scroll-btn btn-link">在引用来源中查看原文</button>
      </div>`;
    }
    return "";
  }

  const items = charts
    .map((ch, idx) => {
      const pageLabel = chartPageLabel(ch);
      const alt = escapeHtml(`${ch.docName} · ${pageLabel}`);
      return `<figure class="citation-chart-item">
        <button type="button" class="citation-chart-thumb" data-chart-url="${escapeHtml(ch.url)}" data-chart-idx="${idx}" aria-label="${alt}">
          <img class="citation-chart-img" data-chart-url="${escapeHtml(ch.url)}" alt="${alt}" />
          <span class="citation-chart-placeholder" aria-hidden="true">点击加载</span>
        </button>
        <figcaption class="citation-chart-caption">${escapeHtml(ch.docName)} · ${escapeHtml(pageLabel)}</figcaption>
      </figure>`;
    })
    .join("");

  return `<details class="citation-charts citation-charts-fold" data-chart-fold>
    <summary class="citation-charts-summary">相关图表（${charts.length}）</summary>
    <div class="citation-charts-body">
      <div class="citation-charts-grid">${items}</div>
    </div>
  </details>`;
}

export async function fetchChartImageBlob(path) {
  const url = resolveChartFetchUrl(path);
  if (!url) throw new Error("empty url");
  const headers = {
    "X-Guest-Id": getGuestId(),
    Accept: "image/png,image/*",
  };
  const token = getAccessToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(url, { headers });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return await res.blob();
}

/** 带鉴权拉取图表 PNG（img 无法自动带 Bearer），写入 blob URL。 */
export async function hydrateCitationChartImages(root, { onSuccess, onFailure } = {}) {
  if (!root) return;
  const imgs = root.querySelectorAll("img.citation-chart-img[data-chart-url]");
  if (!imgs.length) return;
  await Promise.all(
    [...imgs].map(async (img) => {
      if (img.dataset.hydrated === "1") return;
      const path = img.getAttribute("data-chart-url") || "";
      if (!path) return;
      const thumb = img.closest(".citation-chart-thumb");
      try {
        revokeImgBlob(img);
        const blob = await fetchChartImageBlob(path);
        const objectUrl = URL.createObjectURL(blob);
        img.src = objectUrl;
        img.dataset.hydrated = "1";
        img.dataset.blobUrl = objectUrl;
        thumb?.classList.add("is-loaded");
        onSuccess?.();
      } catch {
        img.classList.add("citation-chart-img--error");
        img.alt = (img.alt || "图表") + "（加载失败）";
        thumb?.classList.add("is-error");
        onFailure?.();
      }
    })
  );
}

function revokeCitationChartBlobsInNode(node) {
  if (!node || node.nodeType !== Node.ELEMENT_NODE) return;
  if (node.matches?.("img.citation-chart-img[data-blob-url]")) {
    revokeImgBlob(node);
  }
  node.querySelectorAll?.("img.citation-chart-img[data-blob-url]").forEach(revokeImgBlob);
}

let citationChartBlobCleanupStarted = false;

/** 消息行从 DOM 移除时回收 citation 图表 blob（长会话防泄漏）。 */
export function ensureCitationChartBlobCleanup() {
  if (citationChartBlobCleanupStarted || typeof document === "undefined") return;
  citationChartBlobCleanupStarted = true;
  const observer = new MutationObserver((mutations) => {
    for (const m of mutations) {
      for (const node of m.removedNodes) {
        revokeCitationChartBlobsInNode(node);
      }
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });
}

export function wireCitationChartInteractions(root, { lightbox, onHydrate, onHydrateFailed, onLightboxOpen } = {}) {
  ensureCitationChartBlobCleanup();
  if (!root) return;

  root.querySelectorAll(".citation-charts-scroll-btn").forEach((btn) => {
    if (btn.dataset.chartScrollBound === "1") return;
    btn.dataset.chartScrollBound = "1";
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      const row = root.closest(".msg-row") || root;
      const first = row.querySelector(".citation-item");
      if (!first) return;
      first.scrollIntoView({ behavior: "smooth", block: "center" });
      if (first.tagName === "DETAILS") first.open = true;
      first.classList.add("citation-item--highlight");
      window.setTimeout(() => first.classList.remove("citation-item--highlight"), 2200);
    });
  });

  root.querySelectorAll("details.citation-charts-fold[data-chart-fold]").forEach((details) => {
    if (details.dataset.chartFoldBound === "1") return;
    details.dataset.chartFoldBound = "1";
    details.addEventListener("toggle", () => {
      if (details.open) {
        void hydrateCitationChartImages(details, { onSuccess: onHydrate, onFailure: onHydrateFailed });
      } else {
        details.querySelectorAll("img.citation-chart-img[data-blob-url]").forEach((img) => {
          revokeImgBlob(img);
          img.removeAttribute("src");
          img.dataset.hydrated = "0";
          img.classList.remove("citation-chart-img--error");
          const thumb = img.closest(".citation-chart-thumb");
          thumb?.classList.remove("is-loaded", "is-error");
        });
      }
    });
  });

  root.querySelectorAll(".citation-chart-thumb").forEach((btn) => {
    if (btn.dataset.chartThumbBound === "1") return;
    btn.dataset.chartThumbBound = "1";
    btn.addEventListener("click", async (event) => {
      event.preventDefault();
      const fold = btn.closest("details.citation-charts-fold");
      if (fold && !fold.open) {
        fold.open = true;
        await hydrateCitationChartImages(fold, { onSuccess: onHydrate, onFailure: onHydrateFailed });
      }
      const grid = btn.closest(".citation-charts-grid");
      if (!grid || !lightbox) return;
      const thumbs = [...grid.querySelectorAll(".citation-chart-thumb")];
      const startIdx = Number(btn.dataset.chartIdx) || 0;
      const slides = thumbs.map((thumb) => {
        const img = thumb.querySelector("img.citation-chart-img");
        return {
          path: thumb.getAttribute("data-chart-url") || "",
          alt: img?.alt || "图表",
          blobUrl: img?.dataset.blobUrl || "",
        };
      });
      onLightboxOpen?.();
      lightbox.open(slides, startIdx);
    });
  });
}
