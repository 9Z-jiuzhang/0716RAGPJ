/**
 * 品牌矢量标：落地页与管理端侧栏共用，经 localStorage 同步当前构图。
 */

const STORAGE_KEY = "kb-brand-mark-index";

const BRAND_MARK_VARIANTS = [
  `<svg viewBox="0 0 48 48" fill="none" aria-hidden="true">
    <rect x="6" y="6" width="16" height="16" rx="3" fill="currentColor" opacity="0.92"/>
    <rect x="26" y="6" width="16" height="16" rx="3" fill="currentColor" opacity="0.55"/>
    <rect x="6" y="26" width="16" height="16" rx="3" fill="currentColor" opacity="0.55"/>
    <circle cx="34" cy="34" r="8" fill="currentColor" opacity="0.85"/>
  </svg>`,
  `<svg viewBox="0 0 48 48" fill="none" aria-hidden="true">
    <path d="M24 5L42 15.5V32.5L24 43L6 32.5V15.5L24 5Z" stroke="currentColor" stroke-width="2.4" opacity="0.9"/>
    <circle cx="24" cy="24" r="7" fill="currentColor"/>
    <path d="M24 5V17M42 15.5L31 21M42 32.5L31 27M24 43V31M6 32.5L15 27M6 15.5L15 21" stroke="currentColor" stroke-width="1.6" opacity="0.45"/>
  </svg>`,
  `<svg viewBox="0 0 48 48" fill="none" aria-hidden="true">
    <path d="M8 34L24 8L40 34H8Z" fill="currentColor" opacity="0.88"/>
    <rect x="18" y="28" width="12" height="12" rx="2.5" fill="currentColor" opacity="0.45"/>
    <circle cx="24" cy="22" r="4" fill="var(--brand-mark-hole, currentColor)" opacity="0.35"/>
  </svg>`,
  `<svg viewBox="0 0 48 48" fill="none" aria-hidden="true">
    <rect x="8" y="10" width="32" height="28" rx="6" stroke="currentColor" stroke-width="2.4" opacity="0.9"/>
    <path d="M14 28C17 22 21 19 24 19C27 19 31 22 34 28" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>
    <circle cx="18.5" cy="20" r="2.2" fill="currentColor"/>
    <circle cx="29.5" cy="20" r="2.2" fill="currentColor"/>
  </svg>`,
];

function clampIndex(n) {
  const max = BRAND_MARK_VARIANTS.length;
  if (!Number.isFinite(n) || n < 0) return 0;
  return Math.floor(n) % max;
}

function readStoredIndex() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw == null || raw === "") return null;
    return clampIndex(Number(raw));
  } catch {
    return null;
  }
}

function writeStoredIndex(index) {
  try {
    localStorage.setItem(STORAGE_KEY, String(clampIndex(index)));
  } catch {
    /* ignore quota / private mode */
  }
}

/** 当前已同步的品牌标 SVG（无记录则随机并写入） */
export function getBrandMarkSvg() {
  let index = readStoredIndex();
  if (index == null) {
    index = Math.floor(Math.random() * BRAND_MARK_VARIANTS.length);
    writeStoredIndex(index);
  }
  return BRAND_MARK_VARIANTS[index];
}

/**
 * 落地页用：可选重新随机并同步到 localStorage，管理端随后读到同一构图。
 * @param {{ reshuffle?: boolean }} [opts]
 */
export function resolveBrandMarkSvg({ reshuffle = false } = {}) {
  if (reshuffle) {
    const index = Math.floor(Math.random() * BRAND_MARK_VARIANTS.length);
    writeStoredIndex(index);
    return BRAND_MARK_VARIANTS[index];
  }
  return getBrandMarkSvg();
}

export function getBrandMarkIndex() {
  const index = readStoredIndex();
  return index == null ? 0 : index;
}
