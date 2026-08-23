/** chart_refs / images 对应的 QA 代理 URL（不含 MinIO presigned）。 */

export function buildChartAssetUrl(docId, assetId) {
  const id = String(docId || "").trim();
  const asset = String(assetId || "").trim();
  if (!id || !asset) return "";
  return `/api/v1/qa/documents/${id}/assets/${asset}`;
}

export function buildChartPageUrl(docId, page) {
  const id = String(docId || "").trim();
  const p = Number(page);
  if (!id || !Number.isFinite(p) || p <= 0) return "";
  return `/api/v1/qa/documents/${id}/charts/page-${String(Math.floor(p)).padStart(2, "0")}.png`;
}

/** 兼容旧 citations 里已拼好的 path 或相对 path。 */
export function resolveChartFetchUrl(path) {
  const raw = String(path || "").trim();
  if (!raw) return "";
  if (/^https?:\/\//i.test(raw)) return raw;
  if (raw.startsWith("/api/")) return raw;
  if (raw.startsWith("/")) return `/api/v1${raw}`;
  return `/api/v1/${raw}`;
}
