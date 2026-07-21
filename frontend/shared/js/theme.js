/**
 * 主题切换：dark / light
 * 持久化 localStorage key: kb-theme
 */

const STORAGE_KEY = "kb-theme";

export function getTheme() {
  const fromDom = document.documentElement.getAttribute("data-theme");
  if (fromDom === "light" || fromDom === "dark") return fromDom;
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    /* ignore */
  }
  return "dark";
}

export function applyTheme(theme) {
  const next = theme === "light" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch {
    /* ignore */
  }
  document.querySelectorAll("[data-theme-toggle]").forEach((btn) => {
    btn.setAttribute("aria-pressed", next === "light" ? "true" : "false");
    btn.title = next === "light" ? "切换到夜间模式" : "切换到日间模式";
  });
  return next;
}

export function toggleTheme() {
  return applyTheme(getTheme() === "light" ? "dark" : "light");
}

/** 启动时应用已保存主题，并绑定切换按钮 */
export function initTheme() {
  applyTheme(getTheme());
  document.addEventListener("click", (e) => {
    const btn = e.target.closest?.("[data-theme-toggle]");
    if (!btn) return;
    toggleTheme();
  });
}
