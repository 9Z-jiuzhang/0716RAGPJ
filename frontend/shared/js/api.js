/**
 * API 客户端：统一请求包装、Token、刷新、演示降级
 * Base URL：http://localhost:8080/api/v1（经 Nginx 反代）
 */

import { getAccessToken, getRefreshToken, saveAuth, clearAuth, getGuestId, getUser, mergeUserProfiles } from "./auth.js";
import { toast, uuid } from "./utils.js";
import * as mock from "./mock.js";

/** API 根路径（相对当前站点，便于 Docker 统一入口） */
const API_BASE = "/api/v1";

/** 演示模式开关（后端 501/网络失败时自动开启） */
let demoMode = false;

/** 刷新单飞，避免并发 401 互相覆盖会话 */
let refreshPromise = null;

/** 查询是否处于演示模式 */
export function isDemoMode() {
  return demoMode || localStorage.getItem("rag_force_demo") === "1" || sessionStorage.getItem("rag_demo_mode") === "1";
}

/** 手动开关演示模式（开发联调用） */
export function setForceDemo(on) {
  localStorage.setItem("rag_force_demo", on ? "1" : "0");
  demoMode = !!on;
}

/**
 * 通用 JSON 请求
 * @param {string} path 相对 /api/v1 的路径
 * @param {object} options fetch 选项 + json body
 */
export async function apiRequest(path, options = {}) {
  // 强制演示模式直接走 mock
  if (isDemoMode()) {
    return mock.handle(path, options);
  }

  const headers = Object.assign(
    {
      "Content-Type": "application/json",
      "X-Request-Id": uuid(),
      "X-Guest-Id": getGuestId(),
    },
    options.headers || {}
  );

  // 附带 Bearer Token
  const token = getAccessToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  // 组装 fetch 参数
  const init = {
    method: options.method || "GET",
    headers,
  };

  // JSON 请求体
  if (options.body !== undefined) {
    init.body = typeof options.body === "string" ? options.body : JSON.stringify(options.body);
  }

  // FormData 上传时去掉 Content-Type，交给浏览器设置 boundary
  if (options.formData) {
    delete headers["Content-Type"];
    init.body = options.formData;
  }

  let res;
  try {
    res = await fetch(`${API_BASE}${path}`, init);
  } catch (err) {
    // 网络失败：切换演示模式并走 mock，保证页面可落地演示
    return enterDemoAndMock(path, options, "后端不可用，已进入演示模式");
  }

  // 401：尝试 refresh，失败则清登录态
  if (res.status === 401 && !options._retried) {
    const ok = await tryRefresh();
    if (ok) return apiRequest(path, { ...options, _retried: true });
    clearAuth();
    toast("登录已失效，请重新登录", "error");
    throw new Error("UNAUTHORIZED");
  }

  // 后端未就绪常见：501；纯静态网关对 POST 会 405；无反代时 404
  if ([404, 405, 500, 501, 502, 503].includes(res.status)) {
    return enterDemoAndMock(path, options);
  }

  // 非 JSON：静态站常对 /api 误返回 HTML；登录接口必须降级 Mock，禁止当作成功
  const ct = res.headers.get("content-type") || "";
  if (!ct.includes("application/json")) {
    return enterDemoAndMock(path, options);
  }

  const payload = await res.json();
  // 业务码非 0：登录等写操作勿吞掉；框架 501 包装则降级演示
  if (payload && typeof payload.code === "number" && payload.code !== 0) {
    if ([404, 405, 500, 501, 502, 503].includes(payload.code)) {
      return enterDemoAndMock(path, options);
    }
    throw new Error(payload.message || "业务失败");
  }
  // 兼容直接返回 data 或整包
  const data = payload?.data !== undefined ? payload.data : payload;
  // 登录：有 token 即可；缺 user 时由前端 doLogin 用角色表补全，勿因此强制进 Mock 丢掉真 token
  if (String(path).includes("/auth/login") && (!data || !data.access_token)) {
    return enterDemoAndMock(path, options);
  }
  return data;
}

/** 进入演示模式并走本地 Mock */
function enterDemoAndMock(path, options, toastMsg) {
  demoMode = true;
  try {
    sessionStorage.setItem("rag_demo_mode", "1");
  } catch {
    /* ignore */
  }
  if (toastMsg) toast(toastMsg, "error");
  document.dispatchEvent(new CustomEvent("rag:demo-mode"));
  return mock.handle(path, options);
}

/** 使用 refresh_token 换取新 access_token（单飞 + 不降级覆盖 user） */
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
      // 仅当远端带完整角色时才更新 user，防止 {} / 无 roles 冲掉管理员
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
  if (isDemoMode()) {
    return mock.askStreamMock(body, { onEvent, signal });
  }

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
  } catch (e) {
    demoMode = true;
    document.dispatchEvent(new CustomEvent("rag:demo-mode"));
    return mock.askStreamMock(body, { onEvent, signal });
  }

  if (res.status === 501 || res.status === 405 || res.status === 404 || !res.ok) {
    demoMode = true;
    document.dispatchEvent(new CustomEvent("rag:demo-mode"));
    return mock.askStreamMock(body, { onEvent, signal });
  }

  // 逐块读取 SSE
  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // 按空行拆分事件
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";
    for (const part of parts) {
      parseSseBlock(part, onEvent);
    }
  }
  if (buffer.trim()) parseSseBlock(buffer, onEvent);
}

/** 解析单个 SSE 块：event + data */
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

/** 便捷方法 */
export const api = {
  get: (path, opts) => apiRequest(path, { ...opts, method: "GET" }),
  post: (path, body, opts) => apiRequest(path, { ...opts, method: "POST", body }),
  put: (path, body, opts) => apiRequest(path, { ...opts, method: "PUT", body }),
  patch: (path, body, opts) => apiRequest(path, { ...opts, method: "PATCH", body }),
  delete: (path, opts) => apiRequest(path, { ...opts, method: "DELETE" }),
  upload: (path, formData, opts) => apiRequest(path, { ...opts, method: "POST", formData }),
};
