/**
 * API 客户端：统一请求包装、Token、刷新（仅真实后端）
 * 经统一入口 Nginx 同源反代访问：/api/v1
 */

import { getAccessToken, getRefreshToken, saveAuth, clearAuth, getGuestId, getUser, mergeUserProfiles } from "/assets/js/auth.js?v=gap-opt-0721h";
import { toast, uuid } from "/assets/js/utils.js?v=gap-opt-0721h";

/** API 根路径（相对当前站点） */
const API_BASE = "/api/v1";

/** 刷新单飞，避免并发 401 互相覆盖会话 */
let refreshPromise = null;

/** 清除历史演示模式标记（兼容旧会话） */
export function clearDemoFlags() {
  try {
    localStorage.removeItem("rag_force_demo");
    sessionStorage.removeItem("rag_demo_mode");
  } catch {
    /* ignore */
  }
}

clearDemoFlags();

/** 从响应中提取可读错误信息 */
async function readErrorMessage(res) {
  try {
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) {
      const payload = await res.json();
      if (payload?.message) return payload.message;
      if (typeof payload?.detail === "string") return payload.detail;
      if (Array.isArray(payload?.detail)) {
        return payload.detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
      }
      if (payload?.detail) return String(payload.detail);
    }
    const text = await res.text();
    if (text) return text.slice(0, 200);
  } catch {
    /* ignore */
  }
  return `请求失败（HTTP ${res.status}）`;
}

/**
 * 通用 JSON 请求
 * @param {string} path 相对 /api/v1 的路径
 * @param {object} options fetch 选项 + json body
 */
export async function apiRequest(path, options = {}) {
  const headers = Object.assign(
    {
      "Content-Type": "application/json",
      "X-Request-Id": uuid(),
      "X-Guest-Id": getGuestId(),
    },
    options.headers || {}
  );

  const token = getAccessToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const init = {
    method: options.method || "GET",
    headers,
  };

  if (options.body !== undefined) {
    init.body = typeof options.body === "string" ? options.body : JSON.stringify(options.body);
  }

  if (options.formData) {
    delete headers["Content-Type"];
    init.body = options.formData;
  }

  let res;
  try {
    res = await fetch(`${API_BASE}${path}`, init);
  } catch {
    throw new Error("无法连接后端，请确认统一入口（Nginx）与 API 服务已启动");
  }

  if (res.status === 401 && !options._retried) {
    const ok = await tryRefresh();
    if (ok) return apiRequest(path, { ...options, _retried: true });
    clearAuth();
    toast("登录已失效，请重新登录", "error");
    throw new Error("UNAUTHORIZED");
  }

  if (!res.ok) {
    throw new Error(await readErrorMessage(res));
  }

  const ct = res.headers.get("content-type") || "";
  if (!ct.includes("application/json")) {
    throw new Error("后端返回了非 JSON 响应，请确认经统一入口反代访问 /api/v1");
  }

  const payload = await res.json();
  if (payload && typeof payload.code === "number" && payload.code !== 0) {
    throw new Error(payload.message || "业务失败");
  }

  const data = payload?.data !== undefined ? payload.data : payload;
  if (String(path).includes("/auth/login") && (!data || !data.access_token)) {
    throw new Error("登录响应缺少 access_token");
  }
  return data;
}

/** 使用 refresh_token 换取新 access_token */
async function tryRefresh() {
  if (refreshPromise) return refreshPromise;
  refreshPromise = (async () => {
    const rt = getRefreshToken();
    if (!rt) return false;
    try {
      const res = await fetch(`${API_BASE}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: rt }),
      });
      if (!res.ok) return false;
      const payload = await res.json();
      const data = payload.data || payload;
      if (!data.access_token) return false;
      const patch = {
        access_token: data.access_token,
        refresh_token: data.refresh_token || rt,
      };
      if (data.user && (data.user.roles || data.user.role || data.user.permissions)) {
        patch.user = mergeUserProfiles(getUser(), data.user);
      }
      saveAuth(patch);
      return true;
    } catch {
      return false;
    } finally {
      refreshPromise = null;
    }
  })();
  return refreshPromise;
}

/**
 * SSE 流式问答 POST /qa/ask
 * onEvent(eventName, data)
 */
export async function askStream(body, { onEvent, signal } = {}) {
  const headers = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
    "X-Request-Id": uuid(),
    "X-Guest-Id": getGuestId(),
  };
  const token = getAccessToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  let res;
  try {
    res = await fetch(`${API_BASE}/qa/ask`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      signal,
    });
  } catch {
    throw new Error("无法连接后端问答接口");
  }

  if (!res.ok) {
    throw new Error(await readErrorMessage(res));
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";
    for (const part of parts) {
      parseSseBlock(part, onEvent);
    }
  }
  if (buffer.trim()) parseSseBlock(buffer, onEvent);
}

function parseSseBlock(block, onEvent) {
  let eventName = "message";
  const dataLines = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) eventName = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (!dataLines.length) return;
  let data = dataLines.join("\n");
  try {
    data = JSON.parse(data);
  } catch {
    // 保持字符串
  }
  if (typeof onEvent === "function") onEvent(eventName, data);
}

export const api = {
  get: (path, opts) => apiRequest(path, { ...opts, method: "GET" }),
  post: (path, body, opts) => apiRequest(path, { ...opts, method: "POST", body }),
  put: (path, body, opts) => apiRequest(path, { ...opts, method: "PUT", body }),
  patch: (path, body, opts) => apiRequest(path, { ...opts, method: "PATCH", body }),
  delete: (path, opts) => apiRequest(path, { ...opts, method: "DELETE" }),
  upload: (path, formData, opts) => apiRequest(path, { ...opts, method: "POST", formData }),
};
