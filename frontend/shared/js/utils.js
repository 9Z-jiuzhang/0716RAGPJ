/**
 * 通用工具函数（中文注释逐行说明）
 */

/** 简易 HTML 转义，防止 XSS */
export function escapeHtml(str) {
  // 空值直接返回空串
  if (str === null || str === undefined) return "";
  // 转成字符串后替换特殊字符
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** 格式化日期时间显示 */
export function formatDateTime(value) {
  // 无值时显示占位
  if (!value) return "-";
  // 构造成 Date 对象
  const d = new Date(value);
  // 非法日期保护
  if (Number.isNaN(d.getTime())) return String(value);
  // 本地化短格式
  return d.toLocaleString("zh-CN", { hour12: false });
}

/** 生成 UUID（会话/请求兜底用） */
export function uuid() {
  // 优先使用浏览器原生随机 UUID
  if (crypto && crypto.randomUUID) return crypto.randomUUID();
  // 降级：时间戳 + 随机数
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/** Toast 轻提示 */
export function toast(message, type = "info") {
  // 确保容器存在
  let box = document.querySelector(".toast-container");
  if (!box) {
    box = document.createElement("div");
    box.className = "toast-container";
    document.body.appendChild(box);
  }
  // 创建一条 toast
  const el = document.createElement("div");
  el.className = `toast toast-${type === "error" ? "error" : type === "success" ? "success" : "info"}`;
  el.textContent = message;
  box.appendChild(el);
  // 3 秒后自动移除
  setTimeout(() => el.remove(), 3000);
}

/**
 * 危险操作确认弹窗（手册要求：危险操作使用明确确认弹窗）
 * @returns {Promise<boolean>}
 */
export function confirmDialog({ title = "确认操作", message = "确定继续吗？", confirmText = "确认", danger = true } = {}) {
  return new Promise((resolve) => {
    // 创建遮罩
    const mask = document.createElement("div");
    mask.className = "modal-mask";
    // 弹窗 HTML
    mask.innerHTML = `
      <div class="modal" role="dialog" aria-modal="true">
        <h3 class="modal-title">${escapeHtml(title)}</h3>
        <p>${escapeHtml(message)}</p>
        <div class="modal-actions">
          <button type="button" class="btn btn-secondary" data-act="cancel">取消</button>
          <button type="button" class="btn ${danger ? "btn-danger" : ""}" data-act="ok">${escapeHtml(confirmText)}</button>
        </div>
      </div>
    `;
    // 点击按钮回调
    mask.addEventListener("click", (e) => {
      const act = e.target.getAttribute("data-act");
      if (!act) return;
      mask.remove();
      resolve(act === "ok");
    });
    document.body.appendChild(mask);
  });
}

/** 防抖 */
export function debounce(fn, wait = 300) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}

/** 解析 query string */
export function parseQuery(search = location.search) {
  const q = {};
  const sp = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  sp.forEach((v, k) => {
    q[k] = v;
  });
  return q;
}
