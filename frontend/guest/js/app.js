/**
 * 访客端应用入口（手册 5.1.1）
 * - 默认落地页：统一入口（访客 ENTER / 账号 SIGN IN）
 * - 未登录访客：可 ENTER 进入智能问答
 * - 注册用户：问答 + 历史 + 个人中心
 * - 员工：再加文档上传
 * - 管理员：统一登录后进入管理端
 */

import { route, startRouter, navigate, currentPath } from "/assets/js/router.js?v=gap-opt-0721i";
import { api, askStream, clearDemoFlags } from "/assets/js/api.js?v=bug-ui-palette-0721ek";
import {
  isLoggedIn,
  getUser,
  saveAuth,
  clearAuth,
  replaceAuthSession,
  mergeUserProfiles,
  getPrimaryRole,
  getRoleLabel,
  canUpload,
  canAccessAdmin,
  getPostLoginTarget,
  canAccessKb,
  getDepartment,
  setRememberMe,
  getRememberMe,
  isSuperAdmin,
} from "/assets/js/auth.js?v=gap-opt-0721i";
import { escapeHtml, formatDateTime, toast, confirmDialog, pollUntil, openChangePasswordModal } from "/assets/js/utils.js?v=gap-opt-0721i";
import { initMotion } from "/assets/js/motion.js?v=bug-ui-palette-0721bs";
import { initTheme, applyTheme, getTheme } from "/assets/js/theme.js?v=gap-opt-0721i";

clearDemoFlags();
initTheme();
initMotion();

/** 当前问答会话 ID（多轮上下文） */
let currentSessionId = null;
/** 流式请求控制器 */
let askAbort = null;
/** 待从历史打开的会话 ID（跳转问答页后由 pageChat 加载） */
let pendingOpenSessionId = null;
/** 会话消息分页（上拉加载更早历史） */
const sessionHistory = {
  sessionId: null,
  pageSize: 40,
  oldestLoadedPage: 1,
  total: 0,
  loading: false,
  hasMore: false,
};

function resetSessionHistory(sessionId = null) {
  sessionHistory.sessionId = sessionId;
  sessionHistory.oldestLoadedPage = 1;
  sessionHistory.total = 0;
  sessionHistory.loading = false;
  sessionHistory.hasMore = false;
}

/** 登录/退出后清空本地会话上下文，避免沿用上一身份的 session_id */
function resetLocalChatContext() {
  currentSessionId = null;
  pendingOpenSessionId = null;
  resetSessionHistory(null);
  if (askAbort) {
    try {
      askAbort.abort();
    } catch {
      /* ignore */
    }
    askAbort = null;
  }
}

/**
 * 拆分模型推理标签与最终回答。
 *
 * 「推理过程」= 模型 think 正文（要展示）
 * 「处理步骤」= 意图/检索等流水线（不展示，已在 SSE 层忽略）
 *
 * 推理过程与最终答案分开渲染；同时兼容流式输出尚未闭合的标签。
 */
function splitModelReasoning(raw) {
  const text = String(raw || "");
  // 兼容常见推理标签：think / thinking / redacted_thinking / 思考
  const openRe = /<(?:redacted_thinking|think|thinking|思考)>/i;
  const closeRe = /<\/(?:redacted_thinking|think|thinking|思考)>/i;
  const openMatch = openRe.exec(text);
  if (!openMatch) {
    return { reasoning: "", answer: text, reasoningOpen: false };
  }
  const before = text.slice(0, openMatch.index);
  const afterOpen = text.slice(openMatch.index + openMatch[0].length);
  const closeMatch = closeRe.exec(afterOpen);
  if (!closeMatch) {
    return {
      reasoning: afterOpen,
      answer: before,
      reasoningOpen: true,
    };
  }
  const reasoning = afterOpen.slice(0, closeMatch.index);
  const answer = `${before}${afterOpen.slice(closeMatch.index + closeMatch[0].length)}`.trim();
  return { reasoning: reasoning.trim(), answer, reasoningOpen: false };
}

/** 渲染助手气泡：模型「推理过程」；生成中展开，结束后可折叠。 */
function renderAssistantBubbleHtml(rawText, extrasHtml = "", { forceCollapseReasoning = false } = {}) {
  const { reasoning, answer, reasoningOpen } = splitModelReasoning(rawText);
  const answerHtml = escapeHtml((answer || "").trim() || (reasoningOpen && !forceCollapseReasoning ? "（正在生成最终回答…）" : ""));
  let reasoningHtml = "";
  if (reasoning) {
    const expanded = reasoningOpen && !forceCollapseReasoning;
    const label = expanded ? "推理过程（生成中）" : "推理过程";
    reasoningHtml = `<details class="model-reasoning model-reasoning-think"${expanded ? " open" : ""}>
      <summary>${label}</summary>
      <div class="model-reasoning-body">${escapeHtml(reasoning)}</div>
    </details>`;
  }
  return `${reasoningHtml}<div class="msg-answer">${answerHtml}</div>${extrasHtml || ""}`;
}

function formatRetrievalRelevance(value) {
  // 引用分数来自 cosine、全文相似度、RRF 或 Rerank；非法值显示 --
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric < 0) return "--";
  let bounded;
  if (numeric <= 1) {
    bounded = numeric;
  } else if (numeric <= 1.5) {
    // 近满分上溢，不要 /100 变成「1.x%」
    bounded = 1;
  } else if (numeric <= 100) {
    bounded = numeric / 100;
  } else {
    return "--";
  }
  bounded = Math.max(0, Math.min(1, bounded));
  if (!Number.isFinite(bounded)) return "--";
  return `${(bounded * 100).toFixed(1)}%`;
}

function formatConfidenceTip(data) {
  const levelMap = { high: "高", medium: "中", low: "低" };
  const levelRaw = data?.confidence;
  const scoreRaw = data?.confidence_score;
  const scoreNum = Number(scoreRaw);
  const hasScore = Number.isFinite(scoreNum) && scoreNum >= 0 && scoreNum <= 1;
  const level =
    typeof levelRaw === "string" && levelMap[levelRaw]
      ? levelMap[levelRaw]
      : hasScore
        ? scoreNum >= 0.75
          ? "高"
          : scoreNum >= 0.4
            ? "中"
            : "低"
        : null;
  if (!level && !hasScore) {
    return `<div class="confidence">置信提示：--（仅供参考，请结合引文核对）</div>`;
  }
  const scoreText = hasScore ? ` ${ (scoreNum * 100).toFixed(1) }%` : "";
  return `<div class="confidence">置信提示：${level || "--"}${scoreText}（仅供参考，请结合引文核对）</div>`;
}

/** 登录成功后按角色跳转（优先使用后端 landing_href） */
function redirectAfterLogin(landingHref) {
  // 固定超管 / 管理员一律进管理端，避免后端落地字段异常时被送去访客问答
  if (canAccessAdmin()) {
    location.href = "/admin/";
    return;
  }
  if (landingHref && typeof landingHref === "string") {
    if (landingHref.startsWith("/admin")) {
      location.href = landingHref;
      return;
    }
    if (landingHref.includes("#")) {
      location.href = landingHref;
      return;
    }
  }
  const target = getPostLoginTarget();
  if (target.type === "admin") {
    location.href = target.href;
    return;
  }
  navigate(target.path || "/chat");
  dispatchRender();
}

/** 按角色生成顶栏导航项（访客仅问答） */
function buildNavItems(path, role) {
  const items = [];
  items.push({ path: "/chat", label: "智能问答", show: true });
  // 员工与管理员可上传
  items.push({ path: "/upload", label: "文档上传", show: canUpload() });
  // 已登录才有个人中心（访客不可见）；历史会话在问答页侧栏
  items.push({ path: "/profile", label: "个人中心", show: role !== "guest" });
  return items
    .filter((i) => i.show)
    .map(
      (i) =>
        `<div class="nav-item ${path === i.path ? "active" : ""}" data-go="${i.path}">${i.label}</div>`
    )
    .join("");
}

/** 渲染业务页顶栏壳层（落地页不使用） */
function renderShell(activeTitle, { wide = false } = {}) {
  const logged = isLoggedIn();
  const user = getUser();
  const role = getPrimaryRole();
  const path = currentPath();
  const roleText = logged
    ? `${escapeHtml(user?.nickname || user?.username || "")} · ${getRoleLabel(role)}`
    : "访客 · 仅公开知识库问答";

  document.getElementById("app").innerHTML = `
    <div class="ambient-orbs" aria-hidden="true"><i></i><i></i><i></i></div>
    <div class="app-shell">
      <header class="topnav">
        <div class="topnav-brand" data-go="/chat" title="回到问答">
          <i class="logo-dot"></i>
          <span>AI 知识库</span>
        </div>
        <nav class="topnav-links" aria-label="主导航">${buildNavItems(path, role)}</nav>
        <div class="topnav-actions">
          <span class="text-muted">${roleText}</span>
          <button type="button" class="theme-toggle" data-theme-toggle aria-label="切换主题" title="切换主题">
            <span class="icon-sun" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg></span>
            <span class="icon-moon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M21.752 15.002A9.72 9.72 0 0 1 18 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 0 0 3 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 0 0 9.002-5.998Z"/></svg></span>
          </button>
          ${canAccessAdmin() ? `<a class="btn btn-secondary btn-sm" href="/admin/">管理端</a>` : ""}
          ${
            logged
              ? `<button type="button" class="btn btn-text" id="btnLogout">退出</button>`
              : `<button type="button" class="btn btn-sm" data-go="/login">登录</button>`
          }
        </div>
      </header>
      <main class="content ${wide ? "content-wide" : ""}" id="pageRoot"></main>
    </div>
  `;

  document.querySelectorAll("[data-go]").forEach((el) => {
    el.addEventListener("click", () => navigate(el.getAttribute("data-go")));
  });
  const btnLogout = document.getElementById("btnLogout");
  if (btnLogout) {
    btnLogout.addEventListener("click", async () => {
      const ok = await confirmDialog({ title: "退出登录", message: "确定退出当前账号吗？", confirmText: "退出" });
      if (!ok) return;
      clearAuth();
      resetLocalChatContext();
      toast("已退出", "success");
      navigate("/");
      dispatchRender();
    });
  }
  applyTheme(getTheme());
}

/** 路由分发 */
function playPageEnter() {
  const root = document.getElementById("pageRoot");
  if (!root) return;
  root.classList.remove("page-enter");
  void root.offsetWidth;
  root.classList.add("page-enter");
}

function dispatchRender() {
  playPageEnter();
  const path = currentPath();
  // 默认入口即为统一登录（无营销落地页）
  if (path === "/" || path === "/login" || path === "/register") {
    return pageMaterioAuth(path === "/register" ? "register" : "login");
  }
  if (path === "/chat") return pageChat();
  if (path === "/favorites") return pageFavorites();
  if (path === "/history") return pageHistory();
  if (path === "/profile") return pageProfile();
  if (path === "/upload") return pageUpload();
  return pageChat();
}

/* ========================= 问答首页 / ========================= */
function pageChat() {
  // 重新进入问答页时取消未完成流式请求，避免并发堆积变慢
  if (askAbort) {
    try {
      askAbort.abort();
    } catch {
      /* ignore */
    }
    askAbort = null;
  }

  renderShell("智能问答", { wide: true });
  const role = getPrimaryRole();
  const tip =
    role === "guest"
      ? "当前为<strong>访客</strong>：仅检索公开知识库，不能上传；登录后按角色开放更多能力。"
      : role === "staff"
        ? `当前为<strong>${getRoleLabel()}</strong>：可问答并上传至本部门授权知识库（手册 §3.4 隔离）。`
        : role === "admin"
          ? `当前为<strong>${getRoleLabel()}</strong>：可使用问答；完整管理请进入管理端。`
          : "当前为<strong>注册用户</strong>：可问答与查看本人历史；上传需员工权限。";

  // 进入智能对话默认展开历史侧栏
  const sidebarCollapsed = false;
  document.getElementById("pageRoot").innerHTML = `
    <div class="qa-layout ${role === "guest" || !isLoggedIn() ? "qa-layout-guest" : ""}${sidebarCollapsed ? "" : " is-sidebar-open"}" id="qaLayout">
      <aside class="qa-sidebar${sidebarCollapsed ? " is-collapsed" : ""}" id="qaSidebar" aria-label="历史对话">
        <div class="qa-sidebar-head">
          <div class="qa-sidebar-head-row">
            <p class="qa-sidebar-title">历史对话</p>
            <button type="button" class="qa-sidebar-toggle" id="btnSidebarToggle" title="${sidebarCollapsed ? "展开侧栏" : "折叠侧栏"}" aria-label="${sidebarCollapsed ? "展开侧栏" : "折叠侧栏"}" aria-expanded="${sidebarCollapsed ? "false" : "true"}">‹</button>
          </div>
          <button type="button" class="btn btn-secondary btn-sm qa-sidebar-new" id="btnNewChat">新对话</button>
          <button type="button" class="qa-sidebar-favs" id="btnOpenFavorites">已收藏的会话</button>
        </div>
        <div class="qa-sidebar-list" id="qaSidebarList">
          ${
            isLoggedIn()
              ? `<div class="qa-sidebar-empty">加载中…</div>`
              : `<p class="qa-sidebar-hint">登录后可在此查看并继续历史会话。<a href="#/login">去登录</a></p>`
          }
        </div>
      </aside>
      <button type="button" class="qa-sidebar-expand" id="btnSidebarExpand" title="展开历史对话" aria-label="展开历史对话" aria-hidden="${sidebarCollapsed ? "false" : "true"}">›</button>
      <div class="qa-chat-column" id="qaChatColumn">
        <div class="qa-chat-stage" id="qaChatStage">
          <div class="qa-messages" id="msgList">
            <div class="empty-state" id="msgEmpty">
              <div class="qa-welcome-mark">AI</div>
              <h1>有什么我能帮你检索？</h1>
              <p>${tip}</p>
              <div class="qa-welcome-note">回答将展示引用来源、文档名、分段序号与置信提示；无法命中时不会编造来源。</div>
              <div class="qa-suggestions">
                <button type="button" data-question="请介绍当前可访问的知识库内容">了解知识库内容</button>
                <button type="button" data-question="如何上传并管理文档？">如何管理文档</button>
                <button type="button" data-question="请说明平台的权限访问规则">查看权限规则</button>
              </div>
            </div>
          </div>
          <button type="button" class="qa-scroll-bottom" id="btnScrollBottom" title="回到底部" aria-label="回到底部" hidden>↓</button>
          <div class="qa-composer" id="qaComposer">
            <div class="qa-composer-resize" id="qaComposerResize" title="拖拽调整高度" role="separator" aria-orientation="horizontal"></div>
            <textarea class="form-control" id="questionInput" placeholder="请输入问题，Enter 发送，Shift+Enter 换行"></textarea>
            <button type="button" class="btn" id="btnSend">发送</button>
          </div>
        </div>
      </div>
    </div>
  `;

  const input = document.getElementById("questionInput");
  const btn = document.getElementById("btnSend");
  btn.addEventListener("click", () => sendQuestion());
  document.querySelectorAll("[data-question]").forEach((item) => {
    item.addEventListener("click", () => {
      input.value = item.getAttribute("data-question") || "";
      input.focus();
    });
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendQuestion();
    }
  });
  bindComposerResize();
  document.getElementById("btnNewChat")?.addEventListener("click", () => startNewChat());
  document.getElementById("btnOpenFavorites")?.addEventListener("click", () => navigate("/favorites"));
  bindSidebarCollapse();
  // 每次进入问答页强制展开历史侧栏（覆盖 localStorage 折叠记忆）
  applySidebarCollapsed(false);
  bindHistoryScrollLoad();
  bindScrollToBottom();
  loadChatSidebar();

  // 从历史打开会话：渲染完成后加载该会话消息（避免路由二次渲染清空）
  if (pendingOpenSessionId) {
    const sid = pendingOpenSessionId;
    pendingOpenSessionId = null;
    currentSessionId = sid;
    loadSessionMessages(sid).then(() => {
      highlightSidebarSession(sid);
      loadChatSidebar();
    });
  }
}

/** 同步侧栏占用轨与舞台内输入卡留白（消息+输入同属 stage，整体平移居中） */
function syncComposerSpace() {
  const composer = document.getElementById("qaComposer");
  const messages = document.getElementById("msgList");
  const column = document.querySelector(".qa-chat-column");
  const stage = document.getElementById("qaChatStage");
  const sidebar = document.getElementById("qaSidebar");
  const layout = document.getElementById("qaLayout") || document.querySelector(".qa-layout");
  if (!composer || !layout) return;

  const collapsed = !sidebar || sidebar.classList.contains("is-collapsed");
  layout.classList.toggle("is-sidebar-open", !collapsed);

  // 清除旧的 fixed 居中定位，改由 CSS 舞台承载
  composer.style.left = "";
  composer.style.width = "";
  composer.style.maxWidth = "";
  composer.style.transform = "";
  composer.style.bottom = "";
  composer.style.position = "";

  if (sidebar) {
    sidebar.style.position = "";
    sidebar.style.left = "";
    sidebar.style.top = "";
    sidebar.style.bottom = "";
    sidebar.style.height = "";
    sidebar.style.zIndex = "";
  }

  const composerBottom = 8;
  layout.style.setProperty("--qa-composer-bottom", `${composerBottom}px`);

  const space = Math.ceil(composer.getBoundingClientRect().height + composerBottom + 4);
  layout.style.setProperty("--qa-composer-space", `${space}px`);
  if (messages) messages.style.setProperty("--qa-composer-space", `${space}px`);
  if (column) column.style.setProperty("--qa-composer-space", `${space}px`);
  if (stage) stage.style.setProperty("--qa-composer-space", `${space}px`);
}

/** 对话列表滚到最底 */
function scrollMessagesToBottom() {
  const list = document.getElementById("msgList");
  if (!list) return;
  requestAnimationFrame(() => {
    list.scrollTop = list.scrollHeight;
    updateScrollToBottomBtn();
  });
}

/** 上翻超过一页时显示「回到底部」 */
function updateScrollToBottomBtn() {
  const list = document.getElementById("msgList");
  const btn = document.getElementById("btnScrollBottom");
  if (!list || !btn) return;
  const page = list.clientHeight || 0;
  const fromBottom = list.scrollHeight - list.scrollTop - list.clientHeight;
  const show = page > 0 && fromBottom > page;
  btn.hidden = !show;
  btn.setAttribute("aria-hidden", show ? "false" : "true");
}

function bindScrollToBottom() {
  const list = document.getElementById("msgList");
  const btn = document.getElementById("btnScrollBottom");
  if (!list || !btn || btn.dataset.bound === "1") return;
  btn.dataset.bound = "1";
  let ticking = false;
  list.addEventListener(
    "scroll",
    () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(() => {
        ticking = false;
        updateScrollToBottomBtn();
      });
    },
    { passive: true }
  );
  btn.addEventListener("click", (e) => {
    e.preventDefault();
    scrollMessagesToBottom();
  });
  updateScrollToBottomBtn();
}

/** 高亮侧栏当前会话 */
function highlightSidebarSession(sessionId) {
  document.querySelectorAll(".qa-sidebar-item-wrap").forEach((el) => {
    el.classList.toggle("is-active", el.getAttribute("data-id") === String(sessionId || ""));
  });
}

const SIDEBAR_COLLAPSE_KEY = "qa_sidebar_collapsed";
const PINNED_SESSIONS_KEY = "qa_pinned_sessions";

function pinnedSessionsKey() {
  const user = getUser();
  const uid = user?.id || user?.username || "anon";
  return `${PINNED_SESSIONS_KEY}:${uid}`;
}

function getPinnedSessionIds() {
  try {
    const raw = localStorage.getItem(pinnedSessionsKey());
    const ids = raw ? JSON.parse(raw) : [];
    return Array.isArray(ids) ? ids.map(String) : [];
  } catch {
    return [];
  }
}

function setPinnedSessionIds(ids) {
  try {
    localStorage.setItem(pinnedSessionsKey(), JSON.stringify(ids.map(String)));
  } catch {
    /* ignore */
  }
}

function sortSessionsWithPins(items) {
  const pinned = getPinnedSessionIds();
  const pinRank = new Map(pinned.map((id, i) => [String(id), i]));
  return [...items].sort((a, b) => {
    const ai = pinRank.has(String(a.id)) ? pinRank.get(String(a.id)) : Infinity;
    const bi = pinRank.has(String(b.id)) ? pinRank.get(String(b.id)) : Infinity;
    if (ai !== bi) return ai - bi;
    return 0;
  });
}

function isSidebarCollapsed() {
  try {
    const v = localStorage.getItem(SIDEBAR_COLLAPSE_KEY);
    // 未设置时默认展开；仅显式存 "1" 时折叠
    if (v === null || v === "") return false;
    return v === "1";
  } catch {
    return false;
  }
}

const FAVORITED_SESSIONS_KEY = "qa_favorited_sessions";

function favoritedSessionsKey() {
  const user = getUser();
  const uid = user?.id || user?.username || "anon";
  return `${FAVORITED_SESSIONS_KEY}:${uid}`;
}

function getFavoritedSessionIds() {
  try {
    const raw = localStorage.getItem(favoritedSessionsKey());
    const ids = raw ? JSON.parse(raw) : [];
    return Array.isArray(ids) ? ids.map(String) : [];
  } catch {
    return [];
  }
}

function setFavoritedSessionIds(ids) {
  try {
    localStorage.setItem(favoritedSessionsKey(), JSON.stringify(ids.map(String)));
  } catch {
    /* ignore */
  }
}

function isSessionFavorited(sessionId) {
  if (!sessionId) return false;
  return getFavoritedSessionIds().includes(String(sessionId));
}

function toggleFavoriteSession(sessionId) {
  if (!sessionId) {
    toast("请先完成一轮对话后再收藏", "error");
    return false;
  }
  const id = String(sessionId);
  let ids = getFavoritedSessionIds();
  const on = ids.includes(id);
  ids = on ? ids.filter((x) => x !== id) : [id, ...ids.filter((x) => x !== id)];
  setFavoritedSessionIds(ids);
  toast(on ? "已取消收藏" : "已加入收藏", "success");
  return !on;
}

const MSG_ACTION_ICONS = {
  copy: `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2" fill="none" stroke="currentColor" stroke-width="1.75"/><path d="M6 15H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v1" fill="none" stroke="currentColor" stroke-width="1.75"/></svg>`,
  up: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 11v9a1 1 0 0 0 1 1h8.2a2 2 0 0 0 1.95-1.55l1.6-6.4A1.8 1.8 0 0 0 18 10h-5.2l.9-4.1A1.7 1.7 0 0 0 12 3.9L7 11z" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round"/><path d="M7 11H4.5A1.5 1.5 0 0 0 3 12.5v6A1.5 1.5 0 0 0 4.5 20H7" fill="none" stroke="currentColor" stroke-width="1.75"/></svg>`,
  down: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17 13V4a1 1 0 0 0-1-1H7.8a2 2 0 0 0-1.95 1.55l-1.6 6.4A1.8 1.8 0 0 0 6 14h5.2l-.9 4.1A1.7 1.7 0 0 0 12 20.1L17 13z" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round"/><path d="M17 13h2.5A1.5 1.5 0 0 1 21 14.5v6A1.5 1.5 0 0 1 19.5 22H17" fill="none" stroke="currentColor" stroke-width="1.75"/></svg>`,
  star: `<svg viewBox="0 0 24 24" aria-hidden="true"><path class="msg-star-path" d="M12 3.2l2.4 5.4 5.9.6-4.4 3.9 1.3 5.7L12 15.9 6.8 18.8l1.3-5.7-4.4-3.9 5.9-.6L12 3.2z" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round"/></svg>`,
  regen: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12a9 9 0 1 1-2.6-6.3" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"/><path d="M21 4v5h-5" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  more: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="6" cy="12" r="1.6" fill="currentColor"/><circle cx="12" cy="12" r="1.6" fill="currentColor"/><circle cx="18" cy="12" r="1.6" fill="currentColor"/></svg>`,
};

function syncFavoriteActionButtons() {
  const on = isSessionFavorited(currentSessionId);
  document.querySelectorAll('[data-msg-act="favorite"]').forEach((btn) => {
    btn.classList.toggle("is-favorited", on);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
    btn.title = on ? "取消收藏" : "收藏";
    btn.setAttribute("aria-label", on ? "取消收藏" : "收藏");
  });
}

function buildMsgActionsHtml() {
  const favOn = isSessionFavorited(currentSessionId);
  return `<div class="msg-actions" role="toolbar" aria-label="回答操作">
    <button type="button" class="msg-action-btn" data-msg-act="copy" title="复制" aria-label="复制">${MSG_ACTION_ICONS.copy}</button>
    <button type="button" class="msg-action-btn" data-msg-act="up" title="有用" aria-label="有用" aria-pressed="false">${MSG_ACTION_ICONS.up}</button>
    <button type="button" class="msg-action-btn" data-msg-act="down" title="无用" aria-label="无用" aria-pressed="false">${MSG_ACTION_ICONS.down}</button>
    <button type="button" class="msg-action-btn${favOn ? " is-favorited" : ""}" data-msg-act="favorite" title="${favOn ? "取消收藏" : "收藏"}" aria-label="${favOn ? "取消收藏" : "收藏"}" aria-pressed="${favOn ? "true" : "false"}">${MSG_ACTION_ICONS.star}</button>
    <button type="button" class="msg-action-btn" data-msg-act="regen" title="重新生成" aria-label="重新生成">${MSG_ACTION_ICONS.regen}</button>
    <div class="msg-action-more">
      <button type="button" class="msg-action-btn" data-msg-act="more" title="更多" aria-label="更多" aria-expanded="false">${MSG_ACTION_ICONS.more}</button>
      <div class="msg-action-menu" role="menu" hidden>
        <button type="button" role="menuitem" data-msg-menu="feedback">反馈</button>
        <button type="button" role="menuitem" data-msg-menu="delete" class="is-danger">删除</button>
      </div>
    </div>
  </div>`;
}

function getAssistantAnswerText(row) {
  const answer = row?.querySelector(".msg-answer");
  if (answer) return (answer.textContent || "").trim();
  const bubble = row?.querySelector(".msg-bubble");
  return (bubble?.innerText || "").trim();
}

function getPrevUserQuestion(row) {
  let prev = row?.previousElementSibling;
  while (prev) {
    if (prev.classList.contains("msg-row") && prev.classList.contains("user")) {
      return (prev.querySelector(".msg-bubble")?.innerText || "").trim();
    }
    prev = prev.previousElementSibling;
  }
  return "";
}

async function copyTextToClipboard(text) {
  const value = String(text || "").trim();
  if (!value) {
    toast("没有可复制的内容", "error");
    return false;
  }
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
    } else {
      const ta = document.createElement("textarea");
      ta.value = value;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    return true;
  } catch {
    toast("复制失败", "error");
    return false;
  }
}

function closeAllMsgActionMenus(except = null) {
  document.querySelectorAll(".msg-action-menu").forEach((menu) => {
    if (except && menu === except) return;
    menu.hidden = true;
    menu.classList.remove("is-open");
    const btn = menu.parentElement?.querySelector('[data-msg-act="more"]');
    if (btn) btn.setAttribute("aria-expanded", "false");
  });
}

function bindMsgActions(row) {
  if (!row || row.dataset.actionsBound === "1") return;
  const bar = row.querySelector(".msg-actions");
  if (!bar) return;
  row.dataset.actionsBound = "1";

  const setRate = (kind) => {
    const up = bar.querySelector('[data-msg-act="up"]');
    const down = bar.querySelector('[data-msg-act="down"]');
    const target = kind === "up" ? up : down;
    const other = kind === "up" ? down : up;
    const on = target?.classList.contains("is-active");
    up?.classList.remove("is-active");
    down?.classList.remove("is-active");
    up?.setAttribute("aria-pressed", "false");
    down?.setAttribute("aria-pressed", "false");
    if (!on && target) {
      target.classList.add("is-active");
      target.setAttribute("aria-pressed", "true");
    }
    other?.classList.remove("is-active");
  };

  bar.querySelectorAll("[data-msg-act]").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const act = btn.getAttribute("data-msg-act");
      if (act === "copy") {
        if (await copyTextToClipboard(getAssistantAnswerText(row))) toast("已复制", "success");
        return;
      }
      if (act === "favorite") {
        toggleFavoriteSession(currentSessionId);
        syncFavoriteActionButtons();
        return;
      }
      if (act === "up" || act === "down") {
        setRate(act);
        return;
      }
      if (act === "regen") {
        const q = getPrevUserQuestion(row);
        if (!q) return toast("找不到上一问，无法重新生成", "error");
        const input = document.getElementById("questionInput");
        if (input) input.value = q;
        sendQuestion(q);
        return;
      }
      if (act === "more") {
        const menu = bar.querySelector(".msg-action-menu");
        if (!menu) return;
        const open = menu.hidden;
        closeAllMsgActionMenus(open ? menu : null);
        menu.hidden = !open;
        menu.classList.toggle("is-open", open);
        btn.setAttribute("aria-expanded", open ? "true" : "false");
      }
    });
  });

  bar.querySelectorAll("[data-msg-menu]").forEach((item) => {
    item.addEventListener("click", async (e) => {
      e.stopPropagation();
      const act = item.getAttribute("data-msg-menu");
      closeAllMsgActionMenus();
      if (act === "feedback") {
        const note = window.prompt("请输入反馈内容（仅本地记录，暂不上传）", "");
        if (note == null) return;
        if (!String(note).trim()) return toast("未填写反馈", "error");
        toast("感谢反馈", "success");
        return;
      }
      if (act === "delete") {
        const ok = await confirmDialog({
          title: "删除回答",
          message: "将从当前页面移除此条 AI 回答（不影响服务端历史）。确定继续？",
          confirmText: "删除",
          danger: true,
        });
        if (!ok) return;
        row.remove();
        toast("已移除", "success");
      }
    });
  });

  syncFavoriteActionButtons();
}

function attachAssistantActions(row) {
  if (!row || !row.classList.contains("assistant")) return;
  if (row.querySelector(".msg-actions")) {
    bindMsgActions(row);
    return;
  }
  row.insertAdjacentHTML("beforeend", buildMsgActionsHtml());
  bindMsgActions(row);
}

if (!window.__msgActionMenuBound) {
  window.__msgActionMenuBound = true;
  document.addEventListener("click", () => closeAllMsgActionMenus());
}

function applySidebarCollapsed(collapsed) {
  const sidebar = document.getElementById("qaSidebar");
  const layout = document.getElementById("qaLayout") || document.querySelector(".qa-layout");
  const toggle = document.getElementById("btnSidebarToggle");
  const expand = document.getElementById("btnSidebarExpand");
  if (!sidebar) return;
  sidebar.classList.toggle("is-collapsed", collapsed);
  if (layout) layout.classList.toggle("is-sidebar-open", !collapsed);
  if (toggle) {
    toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    toggle.title = collapsed ? "展开侧栏" : "折叠侧栏";
    toggle.setAttribute("aria-label", toggle.title);
  }
  if (expand) {
    expand.setAttribute("aria-hidden", collapsed ? "false" : "true");
    expand.tabIndex = collapsed ? 0 : -1;
  }
  try {
    localStorage.setItem(SIDEBAR_COLLAPSE_KEY, collapsed ? "1" : "0");
  } catch {
    /* ignore */
  }
  syncComposerSpace();
}

function bindSidebarCollapse() {
  applySidebarCollapsed(isSidebarCollapsed());
  document.getElementById("btnSidebarToggle")?.addEventListener("click", (e) => {
    e.stopPropagation();
    applySidebarCollapsed(!document.getElementById("qaSidebar")?.classList.contains("is-collapsed"));
  });
  document.getElementById("btnSidebarExpand")?.addEventListener("click", (e) => {
    e.stopPropagation();
    applySidebarCollapsed(false);
  });
  if (!document.body.dataset.qaSidebarMenuBound) {
    document.body.dataset.qaSidebarMenuBound = "1";
    document.addEventListener("click", (e) => {
      if (e.target.closest(".qa-sidebar-menu") || e.target.closest(".qa-sidebar-item-more")) return;
      closeAllSidebarMenus();
    });
  }
}

/** 简单输入弹窗（重命名） */
function promptDialog({ title = "请输入", message = "", defaultValue = "", confirmText = "确定" } = {}) {
  return new Promise((resolve) => {
    const mask = document.createElement("div");
    mask.className = "modal-mask";
    mask.innerHTML = `
      <div class="modal" role="dialog" aria-modal="true">
        <h3 class="modal-title">${escapeHtml(title)}</h3>
        ${message ? `<p>${escapeHtml(message)}</p>` : ""}
        <input class="form-control" id="promptDialogInput" value="${escapeHtml(defaultValue)}" maxlength="100" />
        <div class="modal-actions">
          <button type="button" class="btn btn-secondary" data-act="cancel">取消</button>
          <button type="button" class="btn" data-act="ok">${escapeHtml(confirmText)}</button>
        </div>
      </div>
    `;
    const finish = (value) => {
      mask.remove();
      resolve(value);
    };
    mask.addEventListener("click", (e) => {
      const act = e.target.getAttribute("data-act");
      if (!act) return;
      if (act === "cancel") return finish(null);
      const input = mask.querySelector("#promptDialogInput");
      finish((input?.value || "").trim());
    });
    mask.querySelector("#promptDialogInput")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        finish((e.target.value || "").trim());
      } else if (e.key === "Escape") {
        finish(null);
      }
    });
    document.body.appendChild(mask);
    const input = mask.querySelector("#promptDialogInput");
    input?.focus();
    input?.select();
  });
}

function closeAllSidebarMenus() {
  document.querySelectorAll(".qa-sidebar-menu.is-open").forEach((menu) => {
    menu.classList.remove("is-open");
  });
}

async function renameSidebarSession(sessionId, currentTitle) {
  const next = await promptDialog({
    title: "重命名会话",
    message: "请输入新的会话名称",
    defaultValue: currentTitle || "",
    confirmText: "保存",
  });
  if (next == null) return;
  if (!next) {
    toast("标题不能为空", "error");
    return;
  }
  try {
    await api.put(`/qa/sessions/${sessionId}`, { title: next });
    toast("已重命名", "success");
    await loadChatSidebar();
  } catch (e) {
    toast(e.message || "重命名失败", "error");
  }
}

async function deleteSidebarSession(sessionId, title) {
  const ok = await confirmDialog({
    title: "删除会话",
    message: `确定删除「${title || "未命名会话"}」吗？删除后不可恢复。`,
    confirmText: "删除",
    danger: true,
  });
  if (!ok) return;
  try {
    await api.delete(`/qa/sessions/${sessionId}`);
    const pins = getPinnedSessionIds().filter((id) => id !== String(sessionId));
    setPinnedSessionIds(pins);
    if (String(currentSessionId) === String(sessionId)) {
      startNewChat();
    }
    toast("会话已删除", "success");
    await loadChatSidebar();
  } catch (e) {
    toast(e.message || "删除失败", "error");
  }
}

function togglePinSidebarSession(sessionId) {
  const id = String(sessionId);
  let pins = getPinnedSessionIds();
  if (pins.includes(id)) {
    pins = pins.filter((x) => x !== id);
    toast("已取消置顶", "success");
  } else {
    pins = [id, ...pins.filter((x) => x !== id)];
    toast("已置顶", "success");
  }
  setPinnedSessionIds(pins);
  loadChatSidebar();
}

function formatSidebarDate(value) {
  if (!value) return "-";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`;
}

/** 渲染侧栏会话列表 */
function renderChatSidebarItems(items) {
  const list = document.getElementById("qaSidebarList");
  if (!list) return;
  if (!items.length) {
    list.innerHTML = `<p class="qa-sidebar-empty">暂无历史会话，发送一条消息后会出现在这里。</p>`;
    return;
  }
  const pinned = new Set(getPinnedSessionIds());
  const sorted = sortSessionsWithPins(items);
  list.innerHTML = sorted
    .map((s) => {
      const id = escapeHtml(s.id);
      const rawTitle = s.title || "未命名会话";
      const title = escapeHtml(rawTitle);
      const meta = `${formatSidebarDate(s.updated_at || s.last_active_at)} · ${escapeHtml(s.message_count || 0)} 条`;
      const active = currentSessionId && String(currentSessionId) === String(s.id) ? " is-active" : "";
      const isPinned = pinned.has(String(s.id));
      const pinClass = isPinned ? " is-pinned" : "";
      return `<div class="qa-sidebar-item-wrap${active}${pinClass}" data-id="${id}">
        <button type="button" class="qa-sidebar-item" data-id="${id}" title="${title}">
          <span class="qa-sidebar-item-title">${title}</span>
          <span class="qa-sidebar-item-meta">${meta}</span>
        </button>
        <button type="button" class="qa-sidebar-item-more" data-id="${id}" aria-label="更多操作" title="更多">
          <span class="qa-sidebar-more-pin" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
              <path d="M7 3.5h10"/>
              <path d="M8.5 3.5V6.2L5.2 12.4a1.35 1.35 0 0 0 1.25 1.95h11.1a1.35 1.35 0 0 0 1.25-1.95L15.5 6.2V3.5"/>
              <path d="M12 14.35V20.5"/>
            </svg>
          </span>
          <span class="qa-sidebar-more-dots" aria-hidden="true">⋯</span>
        </button>
        <div class="qa-sidebar-menu" role="menu">
          <button type="button" role="menuitem" data-act="pin" data-id="${id}">${isPinned ? "取消置顶" : "置顶"}</button>
          <button type="button" role="menuitem" data-act="rename" data-id="${id}" data-title="${title}">重命名</button>
          <button type="button" role="menuitem" data-act="delete" data-id="${id}" data-title="${title}" class="is-danger">删除</button>
        </div>
      </div>`;
    })
    .join("");

  list.querySelectorAll(".qa-sidebar-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      closeAllSidebarMenus();
      const id = btn.getAttribute("data-id");
      if (!id || String(id) === String(currentSessionId || "")) return;
      openChatSession(id);
    });
  });

  list.querySelectorAll(".qa-sidebar-item-more").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const wrap = btn.closest(".qa-sidebar-item-wrap");
      const menu = wrap?.querySelector(".qa-sidebar-menu");
      const open = menu?.classList.contains("is-open");
      closeAllSidebarMenus();
      if (!open && menu) menu.classList.add("is-open");
    });
  });

  list.querySelectorAll(".qa-sidebar-menu [data-act]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const act = btn.getAttribute("data-act");
      const id = btn.getAttribute("data-id");
      const title = btn.getAttribute("data-title") || "";
      closeAllSidebarMenus();
      if (!id) return;
      if (act === "pin") togglePinSidebarSession(id);
      else if (act === "rename") renameSidebarSession(id, title);
      else if (act === "delete") deleteSidebarSession(id, title);
    });
  });
}

/** 拉取侧栏历史 */
async function loadChatSidebar() {
  const list = document.getElementById("qaSidebarList");
  if (!list || !isLoggedIn()) return;
  try {
    const data = await api.get("/qa/sessions?page=1&page_size=50");
    const items = data.items || data || [];
    renderChatSidebarItems(items);
    highlightSidebarSession(currentSessionId);
  } catch (e) {
    list.innerHTML = `<p class="qa-sidebar-empty">${escapeHtml(e.message || "历史加载失败")}</p>`;
  }
}

/** 侧栏打开历史会话 */
async function openChatSession(sessionId) {
  if (askAbort) {
    try {
      askAbort.abort();
    } catch {
      /* ignore */
    }
    askAbort = null;
  }
  currentSessionId = sessionId;
  highlightSidebarSession(sessionId);
  await loadSessionMessages(sessionId);
  syncComposerSpace();
}

/** 开始新对话 */
function startNewChat() {
  if (askAbort) {
    try {
      askAbort.abort();
    } catch {
      /* ignore */
    }
    askAbort = null;
  }
  currentSessionId = null;
  resetSessionHistory(null);
  highlightSidebarSession(null);
  const list = document.getElementById("msgList");
  if (!list) return;
  const role = getPrimaryRole();
  const tip =
    role === "guest"
      ? "当前为<strong>访客</strong>：仅检索公开知识库，不能上传；登录后按角色开放更多能力。"
      : role === "staff"
        ? `当前为<strong>${getRoleLabel()}</strong>：可问答并上传至本部门授权知识库（手册 §3.4 隔离）。`
        : role === "admin"
          ? `当前为<strong>${getRoleLabel()}</strong>：可使用问答；完整管理请进入管理端。`
          : "当前为<strong>注册用户</strong>：可问答与查看本人历史；上传需员工权限。";
  list.classList.remove("has-messages");
  list.innerHTML = `
    <div class="empty-state" id="msgEmpty">
      <div class="qa-welcome-mark">AI</div>
      <h1>有什么我能帮你检索？</h1>
      <p>${tip}</p>
      <div class="qa-welcome-note">回答将展示引用来源、文档名、分段序号与置信提示；无法命中时不会编造来源。</div>
      <div class="qa-suggestions">
        <button type="button" data-question="请介绍当前可访问的知识库内容">了解知识库内容</button>
        <button type="button" data-question="如何上传并管理文档？">如何管理文档</button>
        <button type="button" data-question="请说明平台的权限访问规则">查看权限规则</button>
      </div>
    </div>`;
  const input = document.getElementById("questionInput");
  list.querySelectorAll("[data-question]").forEach((item) => {
    item.addEventListener("click", () => {
      if (!input) return;
      input.value = item.getAttribute("data-question") || "";
      input.focus();
    });
  });
  resetComposerHeight();
  input?.focus();
}

/** 对话发送后：输入框高度恢复默认 */
function resetComposerHeight() {
  const input = document.getElementById("questionInput");
  if (!input) return;
  const base = Number(input.dataset.baseHeight || 84);
  input.style.height = `${base}px`;
  input.style.maxHeight = `${base * 2}px`;
  syncComposerSpace();
}

/** 顶部拖拽条：向上拉高输入框，上限为默认高度 2 倍 */
function bindComposerResize() {
  const composer = document.getElementById("qaComposer");
  const handle = document.getElementById("qaComposerResize");
  const input = document.getElementById("questionInput");
  if (!composer || !handle || !input) return;

  // 以当前渲染高度为基准，上限 = 2 倍
  const baseHeight = Math.max(84, Math.round(input.getBoundingClientRect().height) || 84);
  input.dataset.baseHeight = String(baseHeight);
  input.style.height = `${baseHeight}px`;
  input.style.maxHeight = `${baseHeight * 2}px`;
  syncComposerSpace();

  let dragging = false;
  let startY = 0;
  let startHeight = baseHeight;

  const onPointerMove = (e) => {
    if (!dragging) return;
    const dy = startY - e.clientY; // 向上拖 = 拉高
    const next = Math.min(baseHeight * 2, Math.max(baseHeight, startHeight + dy));
    input.style.height = `${next}px`;
    syncComposerSpace();
  };

  const onPointerUp = () => {
    if (!dragging) return;
    dragging = false;
    composer.classList.remove("is-resizing");
    window.removeEventListener("pointermove", onPointerMove);
    window.removeEventListener("pointerup", onPointerUp);
    syncComposerSpace();
  };

  handle.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    dragging = true;
    startY = e.clientY;
    startHeight = input.getBoundingClientRect().height;
    composer.classList.add("is-resizing");
    handle.setPointerCapture?.(e.pointerId);
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
  });

  window.addEventListener("resize", syncComposerSpace, { passive: true });
}

/** 拉取并渲染指定会话的历史消息到问答页（先最新页，上拉加载更早） */
async function loadSessionMessages(sessionId) {
  const list = document.getElementById("msgList");
  if (!list) return;
  resetSessionHistory(sessionId);
  try {
    list.classList.add("is-history-loading");
    list.innerHTML = "";
    list.classList.add("has-messages");
    const feed = ensureMsgFeed();

    const probe = await api.get(`/qa/sessions/${sessionId}?page=1&page_size=1`);
    const total = Number(probe.total || 0);
    sessionHistory.total = total;
    if (!total) {
      list.classList.remove("has-messages");
      list.innerHTML = `<div class="empty-state">该会话暂无消息</div>`;
      return;
    }

    const lastPage = Math.max(1, Math.ceil(total / sessionHistory.pageSize));
    sessionHistory.oldestLoadedPage = lastPage;
    sessionHistory.hasMore = lastPage > 1;

    const detail = await api.get(
      `/qa/sessions/${sessionId}?page=${lastPage}&page_size=${sessionHistory.pageSize}`
    );
    const messages = detail.items || detail.messages || [];
    const frag = document.createDocumentFragment();
    messages.forEach((m) => {
      frag.appendChild(buildMessageRowFromApi(m));
    });
    feed.appendChild(frag);
    scrollMessagesToBottom();
  } catch (e) {
    toast(e.message || "加载会话失败", "error");
  } finally {
    list.classList.remove("is-history-loading");
  }
}

/** 确保消息共享同一水平轨道（避免滚动条出现时左右错位） */
function ensureMsgFeed() {
  const list = document.getElementById("msgList");
  if (!list) return null;
  let feed = document.getElementById("msgFeed");
  if (!feed) {
    feed = document.createElement("div");
    feed.id = "msgFeed";
    feed.className = "msg-feed";
    list.appendChild(feed);
  }
  return feed;
}

function buildCitationsHtml(citations) {
  const items = citations || [];
  if (!items.length) return "";
  return `<div class="citations"><div class="citation-heading">引用来源（共 ${items.length} 段，点击展开原文）</div>${items
    .map(
      (c) =>
        `<details class="citation-item"><summary class="citation-meta">${escapeHtml(c.doc_name)} · #${c.chunk_index}</summary><div class="citation-content">${escapeHtml(c.content || "")}</div></details>`
    )
    .join("")}</div>`;
}

function buildMessageRowFromApi(m) {
  const role = m.role === "user" ? "user" : "assistant";
  const html =
    role === "assistant"
      ? renderAssistantBubbleHtml(m.content || "", buildCitationsHtml(m.citations))
      : escapeHtml(m.content || "");
  const row = buildMessageRow(role, html);
  if (role === "assistant") attachAssistantActions(row);
  return row;
}

function buildMessageRow(role, contentHtml) {
  const row = document.createElement("div");
  row.className = `msg-row ${role}`;
  row.innerHTML = `<div class="msg-bubble">${contentHtml}</div>`;
  return row;
}

/** 上拉加载更早历史：锚定滚动 + 水平基线不变 + 新消息淡入 */
async function loadOlderSessionMessages() {
  if (!sessionHistory.sessionId || sessionHistory.loading || !sessionHistory.hasMore) return;
  if (sessionHistory.oldestLoadedPage <= 1) {
    sessionHistory.hasMore = false;
    return;
  }

  const list = document.getElementById("msgList");
  const feed = ensureMsgFeed();
  if (!list || !feed) return;

  sessionHistory.loading = true;
  list.classList.add("is-history-loading");
  const nextPage = sessionHistory.oldestLoadedPage - 1;
  const anchor = feed.querySelector(".msg-row");
  const listTop = list.getBoundingClientRect().top;
  const anchorOffset = anchor ? anchor.getBoundingClientRect().top - listTop : 0;

  // FLIP：记录现有消息位置，插入后做同步缓动，避免生硬跳变
  const existing = Array.from(feed.querySelectorAll(".msg-row"));
  const firstTops = new Map(existing.map((el) => [el, el.getBoundingClientRect().top]));

  try {
    const detail = await api.get(
      `/qa/sessions/${sessionHistory.sessionId}?page=${nextPage}&page_size=${sessionHistory.pageSize}`
    );
    const messages = detail.items || detail.messages || [];
    if (!messages.length) {
      sessionHistory.hasMore = false;
      return;
    }

    const frag = document.createDocumentFragment();
    const entered = [];
    messages.forEach((m) => {
      const row = buildMessageRowFromApi(m);
      row.classList.add("msg-row-enter");
      frag.appendChild(row);
      entered.push(row);
    });
    feed.insertBefore(frag, feed.firstChild);

    sessionHistory.oldestLoadedPage = nextPage;
    sessionHistory.hasMore = nextPage > 1;

    // 保持锚点消息视觉位置，整列水平位置不变
    if (anchor) {
      const newOffset = anchor.getBoundingClientRect().top - list.getBoundingClientRect().top;
      list.scrollTop += newOffset - anchorOffset;
    }

    // 现有消息：若仍有残余位移，用 transform 缓动归位（水平 translateX 同步为 0）
    existing.forEach((el) => {
      const prevTop = firstTops.get(el);
      if (prevTop == null) return;
      const dy = prevTop - el.getBoundingClientRect().top;
      if (Math.abs(dy) < 0.5) return;
      el.classList.add("msg-row-reflow");
      el.style.transform = `translate3d(0, ${dy}px, 0)`;
      requestAnimationFrame(() => {
        el.style.transform = "translate3d(0, 0, 0)";
      });
      const clear = () => {
        el.classList.remove("msg-row-reflow");
        el.style.transform = "";
        el.removeEventListener("transitionend", clear);
      };
      el.addEventListener("transitionend", clear);
    });

    requestAnimationFrame(() => {
      entered.forEach((el) => el.classList.add("is-visible"));
    });
  } catch (e) {
    toast(e.message || "加载更早消息失败", "error");
  } finally {
    sessionHistory.loading = false;
    list.classList.remove("is-history-loading");
  }
}

function bindHistoryScrollLoad() {
  const list = document.getElementById("msgList");
  if (!list || list.dataset.historyScrollBound === "1") return;
  list.dataset.historyScrollBound = "1";
  let ticking = false;
  list.addEventListener(
    "scroll",
    () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(() => {
        ticking = false;
        if (list.scrollTop <= 96) loadOlderSessionMessages();
      });
    },
    { passive: true }
  );
}

/** 追加一条消息气泡 */
function appendMessage(role, contentHtml, { scroll = true } = {}) {
  // 隐藏空状态
  const empty = document.getElementById("msgEmpty");
  if (empty) empty.remove();
  const list = document.getElementById("msgList");
  list.classList.add("has-messages");
  const feed = ensureMsgFeed();
  const row = buildMessageRow(role, contentHtml);
  feed.appendChild(row);
  if (scroll) scrollMessagesToBottom();
  return row.querySelector(".msg-bubble");
}

/** 助手气泡「正在思考中」占位（单行，避免 pre-wrap 把换行变成留白） */
function thinkingPlaceholderHtml() {
  return `<span class="msg-thinking" aria-live="polite"><span class="msg-thinking-text">正在思考中</span><span class="msg-thinking-dots" aria-hidden="true"><i></i><i></i><i></i></span></span>`;
}

/** 助手气泡外壳：仅流式正文区（不展示处理步骤） */
function initAssistantBubbleShell(bubble) {
  if (!bubble) return;
  if (bubble.querySelector(".msg-stream-body")) return;
  bubble.innerHTML = `<div class="msg-stream-body"></div>`;
}

function getStreamBody(bubble) {
  initAssistantBubbleShell(bubble);
  return bubble.querySelector(".msg-stream-body");
}

function showThinkingPlaceholder(bubble) {
  if (!bubble) return;
  initAssistantBubbleShell(bubble);
  bubble.classList.add("is-thinking");
  bubble.classList.remove("streaming-cursor");
  const body = getStreamBody(bubble);
  if (body) body.innerHTML = thinkingPlaceholderHtml();
}

function setAssistantStreamHtml(bubble, html) {
  if (!bubble) return;
  initAssistantBubbleShell(bubble);
  bubble.classList.remove("is-thinking");
  const body = getStreamBody(bubble);
  if (body) body.innerHTML = html;
}

function clearThinkingState(bubble) {
  bubble?.classList.remove("is-thinking");
}

/** 发送问题并 SSE 流式展示（手册交互流程） */
async function sendQuestion(presetQuestion) {
  const input = document.getElementById("questionInput");
  const question = String(presetQuestion ?? input?.value ?? "").trim();
  // 空问题拦截
  if (!question) {
    toast("请输入问题", "error");
    return;
  }
  // 展示用户气泡
  appendMessage("user", escapeHtml(question));
  // 清空输入框并恢复默认高度
  if (input) input.value = "";
  resetComposerHeight();
  // 创建助手气泡（思考中占位，再流式写入）
  const bubble = appendMessage("assistant", "");
  initAssistantBubbleShell(bubble);
  showThinkingPlaceholder(bubble);
  // 取消上一次未完成请求
  if (askAbort) askAbort.abort();
  askAbort = new AbortController();

  let citationsHtml = "";
  let confidenceTip = "";
  let rawAssistantText = "";

  const runAsk = async (sessionId) => {
    citationsHtml = "";
    confidenceTip = "";
    rawAssistantText = "";
    initAssistantBubbleShell(bubble);
    showThinkingPlaceholder(bubble);
    await askStream(
      {
        question,
        session_id: sessionId || undefined,
        // 不传 kb_ids：由后端按访客/登录身份过滤范围
      },
      {
        signal: askAbort.signal,
        onEvent: (event, data) => {
          // LLM Guard 拒绝：显示固定安全提示，不继续等待回答或引用。
          if (event === "guard_blocked") {
            clearThinkingState(bubble);
            bubble.classList.remove("streaming-cursor");
            rawAssistantText = data.message || "该请求未通过安全检查，系统已拒绝处理。";
            setAssistantStreamHtml(bubble, `<span class="text-danger">${escapeHtml(rawAssistantText)}</span>`);
            return;
          }
          // 流水线事件（intent / query_processing / reasoning / trace 等）不再展示在回答气泡中
          if (
            event === "reasoning" ||
            event === "trace" ||
            event === "traces" ||
            event === "intent" ||
            event === "cache_hit" ||
            event === "query_processing"
          ) {
            return;
          }
          // 增量文本：推理标签由前端分开展示，正文中仅显示最终回答。
          if (event === "chunk") {
            clearThinkingState(bubble);
            bubble.classList.add("streaming-cursor");
            rawAssistantText += data.content || data || "";
            setAssistantStreamHtml(bubble, renderAssistantBubbleHtml(rawAssistantText));
            scrollMessagesToBottom();
          }
          // 引用来源
          if (event === "citations") {
            const items = data.items || data.citations || data || [];
            const list = Array.isArray(items) ? items : [];
            if (!list.length) {
              citationsHtml = `<div class="citations text-muted">未命中可引用分段，不会编造来源。</div>`;
            } else {
              citationsHtml = `<div class="citations"><div class="citation-heading">引用来源（共 ${list.length} 段，点击展开原文）</div>${list
                .map(
                  (c) => `<details class="citation-item">
                    <summary class="citation-meta">${escapeHtml(c.doc_name || "未知文档")} · 分段 #${escapeHtml(c.chunk_index)} · 检索相关度 ${formatRetrievalRelevance(c.score)}</summary>
                    <div class="citation-content">${escapeHtml(c.content || "")}</div>
                  </details>`
                )
                .join("")}</div>`;
            }
          }
          // 结束
          if (event === "done") {
            clearThinkingState(bubble);
            bubble.classList.remove("streaming-cursor");
            currentSessionId = data.session_id || currentSessionId;
            confidenceTip = formatConfidenceTip(data);
            setAssistantStreamHtml(
              bubble,
              renderAssistantBubbleHtml(rawAssistantText, `${citationsHtml}${confidenceTip}`, {
                forceCollapseReasoning: true,
              })
            );
            attachAssistantActions(bubble.closest(".msg-row"));
            highlightSidebarSession(currentSessionId);
            loadChatSidebar();
          }
          // 错误
          if (event === "error") {
            clearThinkingState(bubble);
            const msg = data.message || data || "问答失败";
            // 身份切换后沿用旧会话时后端返回无权访问：清会话并新建一次
            if (typeof msg === "string" && msg.includes("无权访问") && sessionId) {
              throw Object.assign(new Error(msg), { code: "SESSION_FORBIDDEN" });
            }
            setAssistantStreamHtml(bubble, `<span class="text-danger">${escapeHtml(msg)}</span>`);
          }
        },
      }
    );
  };

  try {
    await runAsk(currentSessionId);
  } catch (err) {
    if (err.name === "AbortError") return;
    if (err.code === "SESSION_FORBIDDEN" || (typeof err.message === "string" && err.message.includes("无权访问"))) {
      currentSessionId = null;
      try {
        await runAsk(null);
        return;
      } catch (retryErr) {
        if (retryErr.name === "AbortError") return;
        clearThinkingState(bubble);
        setAssistantStreamHtml(bubble, `<span class="text-danger">${escapeHtml(retryErr.message || "问答失败")}</span>`);
        return;
      }
    }
    clearThinkingState(bubble);
    setAssistantStreamHtml(bubble, `<span class="text-danger">${escapeHtml(err.message || "问答失败")}</span>`);
  }
}

/* ========================= 统一登录入口（沉浸一体布局） ========================= */
/** 全页动效舞台 + 大标题 + 嵌入式登录卡（无左右分割） */
function pageMaterioAuth(mode = "login") {
  if (isLoggedIn()) {
    redirectAfterLogin();
    return;
  }

  document.getElementById("app").innerHTML = `
    <div class="auth-materio">
      <button type="button" class="theme-toggle auth-theme-toggle" data-theme-toggle aria-label="切换主题" title="切换主题">
        <span class="icon-sun" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg></span>
        <span class="icon-moon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M21.752 15.002A9.72 9.72 0 0 1 18 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 0 0 3 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 0 0 9.002-5.998Z"/></svg></span>
      </button>
      <div class="auth-materio-canvas" aria-hidden="true">
        <span class="auth-blob auth-blob-a"></span>
        <span class="auth-blob auth-blob-b"></span>
        <span class="auth-blob auth-blob-c"></span>
        <span class="auth-blob auth-blob-d"></span>
        <div class="auth-materio-mesh"></div>
        <div class="auth-stars"></div>
      </div>
      <div class="auth-materio-shell">
        <aside class="auth-materio-visual">
          <header class="auth-materio-brand">
            <i class="landing-logo"></i>
            <strong>AI 知识库</strong>
          </header>
          <div class="auth-materio-hero">
            <p class="auth-materio-kicker">Enterprise Knowledge OS</p>
            <h1>企业知识，<span>即问即答</span></h1>
            <p class="auth-materio-lead">统一入口连接问答、知识库与管理控制台。<br/>安全、可审计、可扩展。</p>
            <ul class="auth-materio-points">
              <li>混合检索 · 流式问答</li>
              <li>RBAC · 部门隔离</li>
              <li>命中评测 · 全链路观测</li>
            </ul>
          </div>
          <div class="auth-materio-stage-art" aria-hidden="true">
            <div class="auth-figure">
              <span class="auth-figure-ring auth-figure-ring-a"></span>
              <span class="auth-figure-ring auth-figure-ring-b"></span>
              <span class="auth-figure-core"><em></em></span>
              <span class="auth-figure-orbit">
                <i></i><i></i><i></i><i></i>
              </span>
              <span class="auth-figure-beam"></span>
            </div>
            <div class="auth-materio-geo">
              <span class="auth-geo auth-geo-a"></span>
              <span class="auth-geo auth-geo-b"></span>
              <span class="auth-geo auth-geo-c"></span>
              <span class="auth-geo auth-geo-d"></span>
              <span class="auth-geo auth-geo-e"></span>
              <span class="auth-geo auth-geo-f"></span>
              <span class="auth-geo auth-geo-g"></span>
              <span class="auth-geo auth-geo-h"></span>
              <span class="auth-geo auth-geo-i"></span>
              <span class="auth-geo auth-geo-j"></span>
              <span class="auth-geo auth-geo-k"></span>
              <span class="auth-geo auth-geo-l"></span>
            </div>
          </div>
        </aside>
        <section class="auth-materio-panel">
          <div class="auth-materio-card">
            <div class="auth-materio-head">
              <h2 id="authTitle">欢迎回来</h2>
              <p id="authLead">登录账号后开始使用知识平台</p>
            </div>
            <div class="auth-tabs" role="tablist">
              <button type="button" class="auth-tab ${mode !== "register" ? "active" : ""}" data-tab="login">登录</button>
              <button type="button" class="auth-tab ${mode === "register" ? "active" : ""}" data-tab="register">注册</button>
            </div>
            <div id="authPanel"></div>
            <p class="auth-materio-guest">
              无需账号？<button type="button" class="btn-text" id="btnGuestEnter">以访客进入问答</button>
            </p>
          </div>
        </section>
      </div>
    </div>
  `;

  const panel = document.getElementById("authPanel");
  const showTab = (tab) => {
    const next = tab === "register" ? "#/register" : "#/";
    if (location.hash !== next) history.replaceState(null, "", next);
    document.querySelectorAll(".auth-tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
    const title = document.getElementById("authTitle");
    const lead = document.getElementById("authLead");
    if (tab === "register") {
      title.textContent = "创建账号";
      lead.textContent = "注册后默认可问答；权限由管理员分配";
      renderRegisterForm(panel);
    } else {
      title.textContent = "欢迎回来";
      lead.textContent = "访客 / 员工 / 管理员同一入口，登录后自动分流";
      renderLoginForm(panel);
    }
  };

  document.querySelectorAll(".auth-tab").forEach((btn) => {
    btn.addEventListener("click", () => showTab(btn.dataset.tab));
  });
  document.getElementById("btnGuestEnter").onclick = () => {
    navigate("/chat");
    dispatchRender();
  };
  showTab(mode === "register" ? "register" : "login");
  applyTheme(getTheme());
}

/** 登录表单 */
function renderLoginForm(panel) {
  panel.innerHTML = `
    <div class="form-group">
      <label for="loginUser">用户名</label>
      <input class="form-control auth-input" id="loginUser" type="text" autocomplete="username" placeholder="请输入用户名" />
    </div>
    <div class="form-group">
      <label for="loginPass">密码</label>
      <div class="auth-pass-field">
        <input class="form-control auth-input" id="loginPass" type="password" autocomplete="current-password" placeholder="请输入密码" />
        <button type="button" class="auth-pass-toggle" id="loginPassToggle" aria-label="显示密码" title="显示密码" aria-pressed="false">
          <svg class="auth-pass-icon auth-pass-icon-show" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 5c-5 0-9.3 3.1-11 7.5C2.7 16.9 7 20 12 20s9.3-3.1 11-7.5C21.3 8.1 17 5 12 5zm0 12.5A5 5 0 1 1 12 7.5a5 5 0 0 1 0 10zm0-2.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z"/></svg>
          <svg class="auth-pass-icon auth-pass-icon-hide" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M3.3 2.2 2.2 3.3l3.1 3.1C3.4 7.7 1.7 9.5 1 12.5 2.7 16.9 7 20 12 20c2.1 0 4-.5 5.7-1.4l3 3 1.1-1.1L3.3 2.2zM12 17.5c-2.8 0-5-2.2-5-5 0-.8.2-1.5.5-2.1l1.6 1.6c0 .2 0 .3 0 .5a2.5 2.5 0 0 0 2.5 2.5c.2 0 .3 0 .5-.1l1.6 1.6c-.6.3-1.3.5-2.1.5zm8.1-1.9-1.7-1.7c.4-.7.6-1.5.6-2.4a5 5 0 0 0-6.4-4.8L10.8 5C11.2 5 11.6 5 12 5c5 0 9.3 3.1 11 7.5-.5 1.3-1.3 2.5-2.3 3.5l-.6.6z"/></svg>
        </button>
      </div>
    </div>
    <div class="auth-materio-row">
      <label class="auth-check"><input type="checkbox" id="loginRemember" /> 记住我</label>
    </div>
    <button class="btn auth-materio-submit" id="btnDoLogin">登录</button>
  `;
  const rem = document.getElementById("loginRemember");
  if (rem) rem.checked = getRememberMe();
  document.getElementById("btnDoLogin").addEventListener("click", doLogin);
  document.getElementById("loginPass").addEventListener("keydown", (e) => {
    if (e.key === "Enter") doLogin();
  });
  bindAuthPassToggle("loginPass", "loginPassToggle");
}

/** 注册表单 */
function renderRegisterForm(panel) {
  panel.innerHTML = `
    <div class="form-group"><label>用户名（3-50）</label><input class="form-control auth-input" id="regUser" placeholder="用户名" /></div>
    <div class="form-group"><label>邮箱</label><input class="form-control auth-input" id="regEmail" type="email" placeholder="name@company.com" /></div>
    <div class="form-group"><label>昵称（可选）</label><input class="form-control auth-input" id="regNick" placeholder="显示名称" /></div>
    <div class="form-group">
      <label for="regPass">密码（至少 8 位）</label>
      <div class="auth-pass-field">
        <input class="form-control auth-input" id="regPass" type="password" autocomplete="new-password" placeholder="设置密码" />
        <button type="button" class="auth-pass-toggle" id="regPassToggle" aria-label="显示密码" title="显示密码" aria-pressed="false">
          <svg class="auth-pass-icon auth-pass-icon-show" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 5c-5 0-9.3 3.1-11 7.5C2.7 16.9 7 20 12 20s9.3-3.1 11-7.5C21.3 8.1 17 5 12 5zm0 12.5A5 5 0 1 1 12 7.5a5 5 0 0 1 0 10zm0-2.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z"/></svg>
          <svg class="auth-pass-icon auth-pass-icon-hide" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M3.3 2.2 2.2 3.3l3.1 3.1C3.4 7.7 1.7 9.5 1 12.5 2.7 16.9 7 20 12 20c2.1 0 4-.5 5.7-1.4l3 3 1.1-1.1L3.3 2.2zM12 17.5c-2.8 0-5-2.2-5-5 0-.8.2-1.5.5-2.1l1.6 1.6c0 .2 0 .3 0 .5a2.5 2.5 0 0 0 2.5 2.5c.2 0 .3 0 .5-.1l1.6 1.6c-.6.3-1.3.5-2.1.5zm8.1-1.9-1.7-1.7c.4-.7.6-1.5.6-2.4a5 5 0 0 0-6.4-4.8L10.8 5C11.2 5 11.6 5 12 5c5 0 9.3 3.1 11 7.5-.5 1.3-1.3 2.5-2.3 3.5l-.6.6z"/></svg>
        </button>
      </div>
    </div>
    <button class="btn auth-materio-submit" id="btnDoReg">注册并前往登录</button>
  `;
  document.getElementById("btnDoReg").addEventListener("click", doRegister);
  bindAuthPassToggle("regPass", "regPassToggle");
}

/** 登录/注册密码框：小眼睛常驻，点击切换显隐 */
function bindAuthPassToggle(inputId, toggleId) {
  const input = document.getElementById(inputId);
  const toggle = document.getElementById(toggleId);
  if (!input || !toggle) return;
  const syncIcon = () => {
    const revealed = input.type === "text";
    toggle.classList.toggle("is-revealed", revealed);
    toggle.setAttribute("aria-pressed", revealed ? "true" : "false");
    toggle.setAttribute("aria-label", revealed ? "隐藏密码" : "显示密码");
    toggle.setAttribute("title", revealed ? "隐藏密码" : "显示密码");
  };
  toggle.addEventListener("click", () => {
    input.type = input.type === "password" ? "text" : "password";
    syncIcon();
  });
  syncIcon();
}

async function doLogin() {
  const username = document.getElementById("loginUser").value.trim();
  const password = document.getElementById("loginPass").value;
  const remember = Boolean(document.getElementById("loginRemember")?.checked);
  if (!username || !password) return toast("请填写用户名和密码", "error");
  try {
    const data = await api.post("/auth/login", { username, password });
    if (!data?.access_token) throw new Error("登录失败：未返回令牌");
    const user = data.user || { username };
    setRememberMe(remember);
    replaceAuthSession({
      access_token: data.access_token,
      refresh_token: data.refresh_token,
      user,
    });
    // 若后端已带 user 则不必再拉；否则补齐资料
    if (!data.user) {
      const me = await api.get("/auth/me");
      replaceAuthSession({
        access_token: data.access_token,
        refresh_token: data.refresh_token,
        user: me,
      });
    }
    resetLocalChatContext();
    const role = getPrimaryRole();
    toast(`登录成功（${getRoleLabel(role)}）`, "success");
    redirectAfterLogin(data.landing_href);
  } catch (e) {
    clearAuth();
    toast(e.message || "登录失败", "error");
  }
}

async function doRegister() {
  const username = document.getElementById("regUser").value.trim();
  const email = document.getElementById("regEmail").value.trim();
  const nickname = document.getElementById("regNick").value.trim();
  const password = document.getElementById("regPass").value;
  if (username.length < 3 || username.length > 50) return toast("用户名长度需 3-50", "error");
  if (!email.includes("@")) return toast("邮箱格式不正确", "error");
  if (password.length < 8) return toast("密码至少 8 位", "error");
  try {
    await api.post("/auth/register", { username, email, password, nickname: nickname || undefined });
    toast("注册成功，请登录", "success");
    pageMaterioAuth("login");
    setTimeout(() => {
      const el = document.getElementById("loginUser");
      if (el) el.value = username;
    }, 0);
  } catch (e) {
    toast(e.message || "注册失败", "error");
  }
}

/* ========================= 对话历史 /history ========================= */
async function pageFavorites() {
  renderShell("已收藏的会话");
  if (!isLoggedIn()) {
    document.getElementById("pageRoot").innerHTML = `<div class="card empty-state">登录后可查看已收藏会话。<a href="#/login">去登录</a></div>`;
    return;
  }
  const favIds = getFavoritedSessionIds();
  document.getElementById("pageRoot").innerHTML = `<div class="card"><div class="loading">加载中…</div></div>`;
  try {
    const data = await api.get("/qa/sessions?page=1&page_size=100");
    const all = data.items || data || [];
    const byId = new Map(all.map((s) => [String(s.id), s]));
    const items = favIds.map((id) => byId.get(String(id)) || { id, title: "（会话不可用或已删除）", missing: true });
    if (!favIds.length) {
      document.getElementById("pageRoot").innerHTML = `
        <header class="page-head"><div class="page-head-text"><p class="page-desc">收藏的会话会出现在这里。</p></div>
          <div class="page-head-actions"><button type="button" class="btn btn-secondary btn-sm" data-go-chat>返回问答</button></div>
        </header>
        <div class="card empty-state">暂无收藏会话。可在 AI 回答的「⋯ → 收藏」加入。</div>`;
      document.querySelector("[data-go-chat]")?.addEventListener("click", () => navigate("/chat"));
      return;
    }
    document.getElementById("pageRoot").innerHTML = `
      <header class="page-head">
        <div class="page-head-text"><p class="page-desc">共 ${favIds.length} 个已收藏会话</p></div>
        <div class="page-head-actions"><button type="button" class="btn btn-secondary btn-sm" id="btnFavBackChat">返回问答</button></div>
      </header>
      <div class="card panel-fill">
        <div class="card-header"><div class="card-header-text"><h3 class="card-title">已收藏的会话</h3></div></div>
        <div id="favList">
          ${items
            .map(
              (s) => `<div class="history-item" data-id="${escapeHtml(s.id)}">
                <div class="history-item-main">
                  <strong>${escapeHtml(s.title || "未命名会话")}</strong>
                  <div class="text-muted">${s.missing ? "本地收藏记录" : `${formatDateTime(s.updated_at)} · ${escapeHtml(s.message_count || 0)} 条消息`}</div>
                </div>
                <div class="history-item-actions" style="display:flex;gap:6px;flex-wrap:wrap">
                  ${s.missing ? "" : `<button class="btn btn-secondary btn-sm" data-open-fav="${escapeHtml(s.id)}">打开</button>`}
                  <button class="btn btn-danger btn-sm" data-unfav="${escapeHtml(s.id)}">取消收藏</button>
                </div>
              </div>`
            )
            .join("")}
        </div>
      </div>`;
    document.getElementById("btnFavBackChat")?.addEventListener("click", () => navigate("/chat"));
    document.querySelectorAll("[data-open-fav]").forEach((btn) => {
      btn.onclick = () => {
        pendingOpenSessionId = btn.getAttribute("data-open-fav");
        navigate("/chat");
      };
    });
    document.querySelectorAll("[data-unfav]").forEach((btn) => {
      btn.onclick = () => {
        const id = btn.getAttribute("data-unfav");
        setFavoritedSessionIds(getFavoritedSessionIds().filter((x) => x !== String(id)));
        toast("已取消收藏", "success");
        pageFavorites();
      };
    });
  } catch (e) {
    document.getElementById("pageRoot").innerHTML = `<div class="card text-danger">${escapeHtml(e.message || "加载失败")}</div>`;
  }
}

async function pageHistory() {
  renderShell("对话历史");
  // 访客无历史入口；深链也拦截
  if (!isLoggedIn()) {
    document.getElementById("pageRoot").innerHTML = `<div class="card empty-state">访客不能查看对话历史，请先<a href="#/login">登录</a>。</div>`;
    return;
  }
  document.getElementById("pageRoot").innerHTML = `<div class="card"><div class="loading">加载中…</div></div>`;
  try {
    const data = await api.get("/qa/sessions?page=1&page_size=50");
    const items = data.items || data || [];
    if (!items.length) {
      document.getElementById("pageRoot").innerHTML = `
        <header class="page-head"><div class="page-head-text"><p class="page-desc">查看并继续你的问答会话。</p></div></header>
        <div class="card empty-state">暂无历史会话</div>`;
      return;
    }
    document.getElementById("pageRoot").innerHTML = `
      <header class="page-head">
        <div class="page-head-text"><p class="page-desc">共 ${items.length} 个会话</p></div>
      </header>
      <div class="card panel-fill">
        <div class="card-header">
          <div class="card-header-text"><h3 class="card-title">我的会话</h3></div>
        </div>
        <div id="historyList">
          ${items
            .map(
              (s) => `<div class="history-item" data-id="${escapeHtml(s.id)}">
                <div class="history-item-main">
                  <strong class="history-title" data-title-for="${escapeHtml(s.id)}">${escapeHtml(s.title || "未命名会话")}</strong>
                  <div class="text-muted">${formatDateTime(s.updated_at)} · ${escapeHtml(s.message_count || 0)} 条消息</div>
                </div>
                <div class="history-item-actions" style="display:flex;gap:6px;flex-wrap:wrap">
                  <button class="btn btn-secondary btn-sm" data-open="${escapeHtml(s.id)}">打开</button>
                  <button class="btn btn-secondary btn-sm" data-rename="${escapeHtml(s.id)}">重命名</button>
                  <button class="btn btn-danger btn-sm" data-del-session="${escapeHtml(s.id)}">删除</button>
                </div>
              </div>`
            )
            .join("")}
        </div>
      </div>`;
    document.querySelectorAll("[data-open]").forEach((btn) => {
      btn.addEventListener("click", () => {
        pendingOpenSessionId = btn.getAttribute("data-open");
        navigate("/chat");
      });
    });
    document.querySelectorAll("[data-rename]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const sid = btn.getAttribute("data-rename");
        const titleEl = document.querySelector(`[data-title-for="${sid}"]`);
        const cur = titleEl?.textContent || "未命名会话";
        const next = window.prompt("新会话标题", cur);
        if (next == null) return;
        const title = String(next).trim();
        if (!title) return toast("标题不能为空", "error");
        if (title.length > 100) return toast("标题最多 100 字", "error");
        try {
          await api.put(`/qa/sessions/${sid}`, { title });
          if (titleEl) titleEl.textContent = title;
          toast("已重命名", "success");
        } catch (e) {
          toast(e.message || "重命名失败", "error");
        }
      });
    });
    document.querySelectorAll("[data-del-session]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const sid = btn.getAttribute("data-del-session");
        const ok = await confirmDialog({ title: "删除会话", message: "删除后可从服务端软删除，确定？", confirmText: "删除" });
        if (!ok) return;
        try {
          await api.delete(`/qa/sessions/${sid}`);
          if (currentSessionId && String(currentSessionId) === String(sid)) {
            currentSessionId = null;
            resetLocalChatContext?.();
          }
          toast("会话已删除", "success");
          pageHistory();
        } catch (e) {
          toast(e.message || "删除失败", "error");
        }
      });
    });
  } catch (e) {
    document.getElementById("pageRoot").innerHTML = `<div class="card text-danger">${escapeHtml(e.message)}</div>`;
  }
}

/* ========================= 个人中心 /profile ========================= */
async function pageProfile() {
  renderShell("个人中心");
  if (!isLoggedIn()) {
    document.getElementById("pageRoot").innerHTML = `<div class="card empty-state">请先登录后查看个人中心。<br/><button class="btn" id="goLogin">去登录</button></div>`;
    document.getElementById("goLogin").onclick = () => navigate("/login");
    return;
  }
  document.getElementById("pageRoot").innerHTML = `<div class="card"><div class="loading">加载资料…</div></div>`;
  try {
    // 拉 /auth/me 后用 mergeUserProfiles，角色权限取更强一侧
    let me = getUser();
    try {
      const remote = await api.get("/auth/me");
      if (remote && remote.username && remote.username !== "anonymous") {
        me = mergeUserProfiles(getUser(), remote);
        saveAuth({ user: me });
      }
    } catch {
      /* 使用本地 */
    }
    document.getElementById("pageRoot").innerHTML = `
      <header class="page-head">
        <div class="page-head-text"><p class="page-desc">维护账号资料与上传说明。</p></div>
      </header>
      <div class="page-grid">
        <div class="card span-6">
          <div class="card-header">
            <div class="card-header-text"><h3 class="card-title">个人资料</h3></div>
            ${
              isSuperAdmin()
                ? ""
                : `<div class="card-header-actions"><button type="button" class="btn btn-secondary btn-sm" id="btnChangePassword">修改密码</button></div>`
            }
          </div>
          <div class="form-group"><label>用户名</label><input class="form-control" id="pfUser" value="${escapeHtml(me.username || "")}" disabled /></div>
          <div class="form-group"><label>昵称</label><input class="form-control" id="pfNick" value="${escapeHtml(me.nickname || "")}" /></div>
          <div class="form-group"><label>邮箱</label><input class="form-control" id="pfEmail" value="${escapeHtml(me.email || "")}" /></div>
          <div class="form-group"><label>角色</label><div>${escapeHtml((me.roles || [me.role]).filter(Boolean).join(", ") || "-")}</div></div>
          <div class="form-group"><label>最近登录</label><div class="text-muted">${formatDateTime(me.last_login_at)}</div></div>
          ${
            isSuperAdmin()
              ? `<p class="text-muted" style="font-size:12px;margin:0 0 12px">超级管理员密码仅可通过服务器 <code>.env</code> 中的 <code>SUPER_ADMIN_PASSWORD</code> 配置，修改后需重启 API。</p>`
              : ""
          }
          <button class="btn" id="btnSaveProfile">保存资料</button>
        </div>
        <div class="card span-6">
          <div class="card-header"><div class="card-header-text"><h3 class="card-title">我的上传记录</h3></div></div>
          <div class="meta-list">
            <div class="meta-row"><span class="meta-label">查看入口</span><span class="meta-value">管理端 · 知识库文档列表</span></div>
            <div class="meta-row"><span class="meta-label">上传权限</span><span class="meta-value">${canUpload() ? "已开通" : "未开通"}</span></div>
            <div class="meta-row"><span class="meta-label">当前角色</span><span class="meta-value">${escapeHtml(getRoleLabel())}</span></div>
          </div>
          <p class="page-desc" style="margin-top:16px">上传记录请在管理端知识库文档列表中查看；员工仅可上传至本部门或授权知识库。</p>
          ${canUpload() ? `<button class="btn btn-secondary btn-sm" data-go="/upload" style="margin-top:12px">去上传文档</button>` : ""}
        </div>
      </div>`;
    document.querySelectorAll("[data-go]").forEach((el) => {
      el.addEventListener("click", () => navigate(el.getAttribute("data-go")));
    });
    document.getElementById("btnSaveProfile").onclick = async () => {
      const nickname = document.getElementById("pfNick").value.trim();
      const email = document.getElementById("pfEmail").value.trim();
      try {
        const updated = await api.put("/auth/me", { nickname, email });
        saveAuth({ user: updated || { ...me, nickname, email } });
        toast("资料已保存", "success");
        dispatchRender();
      } catch (e) {
        toast(e.message || "保存失败", "error");
      }
    };
    const btnChangePassword = document.getElementById("btnChangePassword");
    if (btnChangePassword) {
      btnChangePassword.onclick = async () => {
        const changed = await openChangePasswordModal({
          submit: async (payload) => {
            await api.post("/auth/change-password", payload);
          },
        });
        if (changed) toast("密码已更新", "success");
      };
    }
  } catch (e) {
    document.getElementById("pageRoot").innerHTML = `<div class="card text-danger">${escapeHtml(e.message)}</div>`;
  }
}

/* ========================= 文档上传 /upload ========================= */
async function pageUpload() {
  renderShell("文档上传");
  // 仅员工 / 管理员（或具备 kb:upload）
  if (!isLoggedIn()) {
    document.getElementById("pageRoot").innerHTML = `<div class="card empty-state">上传仅限登录员工。请先<a href="#/login">登录</a>。</div>`;
    return;
  }
  if (!canUpload()) {
    document.getElementById("pageRoot").innerHTML = `<div class="card empty-state">当前为「${getRoleLabel()}」，无文档上传权限。请使用 <code>staff_a</code> / <code>staff_b</code> 或联系管理员授权。</div>`;
    return;
  }

  // 加载可选知识库（再按本部门授权过滤，手册 3.4）
  let kbs = [];
  try {
    const data = await api.get("/knowledge-bases?page=1&page_size=100");
    kbs = (data.items || []).filter((k) => canAccessKb(k));
  } catch {
    kbs = [];
  }

  if (!kbs.length) {
    document.getElementById("pageRoot").innerHTML = `<div class="card empty-state">当前账号没有可上传的目标知识库（部门隔离）。</div>`;
    return;
  }

  document.getElementById("pageRoot").innerHTML = `
    <header class="page-head">
      <div class="page-head-text">
        <p class="page-desc">当前身份：${getRoleLabel()}${getDepartment() ? ` · 部门 ${getDepartment()}` : ""}。支持 PDF、Word、TXT、Markdown。</p>
      </div>
    </header>
    <div class="page-grid upload-page-grid">
    <div class="card upload-panel span-8">
      <div class="card-header"><div class="card-header-text"><h3 class="card-title">上传到知识库</h3></div></div>
      <div class="form-group">
        <label>目标知识库</label>
        <select class="form-control" id="kbSelect">
          ${kbs
            .map((k) => {
              const dept = k.department ? ` · ${k.department}部门` : "";
              return `<option value="${escapeHtml(k.id)}">${escapeHtml(k.name)}（${escapeHtml(k.visibility)}${escapeHtml(dept)}）</option>`;
            })
            .join("")}
        </select>
      </div>
      <div class="upload-drop" id="dropZone">
        <span class="upload-drop-copy-idle">点击或拖拽 PDF、Word（DOC/DOCX）、TXT、Markdown（MD）文件到此处（支持多选）</span>
        <span class="upload-drop-copy-active">松手即可上传</span>
      </div>
      <input type="file" id="fileInput" class="hidden" multiple accept=".pdf,.doc,.docx,.txt,.md,text/markdown,application/pdf" />
    </div>
    <div class="card upload-progress-panel span-4">
      <div class="card-header"><div class="card-header-text"><h3 class="card-title">处理进度</h3></div></div>
      <div class="upload-progress-body">
      <div id="uploadProgress" class="text-muted">尚未开始</div>
      <div style="height:8px;background:var(--color-bg);border:1px solid var(--color-border);border-radius:4px;margin-top:12px;overflow:hidden">
        <div id="uploadBar" style="height:100%;width:0;background:var(--color-primary);transition:width .2s"></div>
      </div>
      <div class="meta-list" style="margin-top:16px">
        <div class="meta-row"><span class="meta-label">文件类型</span><span class="meta-value">PDF / Word / TXT / MD</span></div>
        <div class="meta-row"><span class="meta-label">权限说明</span><span class="meta-value">员工限本部门或授权库</span></div>
        <div class="meta-row"><span class="meta-label">批量上传</span><span class="meta-value">支持一次选择多个文件</span></div>
      </div>
      </div>
    </div>
  </div>`;

  const drop = document.getElementById("dropZone");
  const fileInput = document.getElementById("fileInput");
  let dragDepth = 0;
  const setDragActive = (on) => drop.classList.toggle("dragover", on);
  drop.onclick = () => fileInput.click();
  drop.addEventListener("dragenter", (e) => {
    e.preventDefault();
    dragDepth += 1;
    setDragActive(true);
  });
  drop.addEventListener("dragover", (e) => {
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
    setDragActive(true);
  });
  drop.addEventListener("dragleave", () => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) setDragActive(false);
  });
  drop.addEventListener("drop", (e) => {
    e.preventDefault();
    dragDepth = 0;
    setDragActive(false);
    if (e.dataTransfer.files?.length) handleUploadFiles(e.dataTransfer.files);
  });
  fileInput.onchange = () => {
    if (fileInput.files?.length) {
      handleUploadFiles(fileInput.files);
      fileInput.value = "";
    }
  };
}

/** 批量上传：逐个调用既有单文件接口，并汇总进度 */
async function handleUploadFiles(fileList) {
  const files = Array.from(fileList || []).filter(Boolean);
  if (!files.length) return toast("请选择文件", "error");

  const prog = document.getElementById("uploadProgress");
  const bar = document.getElementById("uploadBar");
  let ok = 0;
  const failures = [];

  for (let i = 0; i < files.length; i++) {
    const file = files[i];
    try {
      await handleUpload(file, { index: i + 1, total: files.length, quietToast: files.length > 1 });
      ok += 1;
    } catch (e) {
      failures.push(`${file.name}: ${e.message || "上传失败"}`);
      if (prog) {
        prog.innerHTML = `<span class="text-danger">第 ${i + 1}/${files.length} 个失败：${escapeHtml(e.message || "未知错误")}</span>`;
      }
    }
  }

  if (files.length === 1) return;

  if (bar) bar.style.width = "100%";
  if (ok && !failures.length) {
    if (prog) prog.innerHTML = `<span class="text-success">批量上传完成：${ok}/${files.length}</span>`;
    toast(`已成功上传 ${ok} 个文件`, "success");
  } else if (ok) {
    if (prog) {
      prog.innerHTML = `<span class="text-muted">完成 ${ok}/${files.length}，失败 ${failures.length}：${escapeHtml(failures[0])}</span>`;
    }
    toast(`成功 ${ok} 个，失败 ${failures.length} 个`, "error");
  } else {
    if (prog) prog.innerHTML = `<span class="text-danger">批量上传失败：${escapeHtml(failures[0] || "未知错误")}</span>`;
    toast(failures[0] || "上传失败", "error");
  }
}

/** 执行上传并轮询文档管道状态（诚实进度） */
async function handleUpload(file, opts = {}) {
  const kbId = document.getElementById("kbSelect").value;
  if (!kbId) {
    toast("请选择知识库", "error");
    throw new Error("请选择知识库");
  }
  const prog = document.getElementById("uploadProgress");
  const bar = document.getElementById("uploadBar");
  const index = opts.index || 1;
  const total = opts.total || 1;
  const prefix = total > 1 ? `[${index}/${total}] ` : "";
  prog.textContent = `${prefix}正在上传 ${file.name}…`;
  bar.style.width = total > 1 ? `${Math.max(8, Math.round(((index - 1) / total) * 100))}%` : "15%";

  const fd = new FormData();
  fd.append("file", file);

  const busy = new Set(["parsing", "normalizing", "segmenting", "vectorizing", "pending_segment", "uploaded", "pending"]);
  try {
    const doc = await api.upload(`/knowledge-bases/${kbId}/documents/upload`, fd);
    const docId = doc?.id;
    if (!opts.quietToast) toast("上传成功，正在处理…", "success");
    if (!docId) {
      bar.style.width = total > 1 ? `${Math.round((index / total) * 100)}%` : "100%";
      prog.innerHTML = `<span class="text-success">${prefix}上传成功，已进入预处理/向量化队列</span>`;
      return;
    }
    bar.style.width = total > 1 ? `${Math.round(((index - 0.5) / total) * 100)}%` : "35%";
    prog.textContent = `${prefix}已入库，管道处理中（${doc.status || "…"}）…`;
    try {
      const finalDoc = await pollUntil(
        async () => {
          const d = await api.get(`/knowledge-bases/${kbId}/documents/${docId}`);
          const st = String(d.status || "");
          const base = total > 1 ? ((index - 1) / total) * 100 : 0;
          const span = total > 1 ? 100 / total : 100;
          const pct =
            st === "ready" || st === "error"
              ? base + span
              : busy.has(st)
                ? base + span * 0.55
                : base + span * 0.7;
          bar.style.width = `${Math.min(100, Math.round(pct))}%`;
          prog.textContent = `${prefix}处理状态：${st}`;
          return d;
        },
        {
          intervalMs: 2500,
          timeoutMs: 180000,
          shouldStop: (d) => ["ready", "error"].includes(String(d?.status || "")),
        }
      );
      bar.style.width = total > 1 ? `${Math.round((index / total) * 100)}%` : "100%";
      if (finalDoc.status === "ready") {
        prog.innerHTML = `<span class="text-success">${prefix}处理完成（ready）· 分段 ${escapeHtml(finalDoc.chunk_count ?? 0)}</span>`;
      } else {
        prog.innerHTML = `<span class="text-danger">${prefix}处理失败：${escapeHtml(finalDoc.error_message || finalDoc.status || "error")}</span>`;
      }
    } catch (pollErr) {
      prog.innerHTML = `<span class="text-muted">${prefix}已上传；状态轮询结束：${escapeHtml(pollErr.message || "")}。请稍后在知识库文档列表查看。</span>`;
    }
  } catch (e) {
    if (!opts.quietToast) {
      bar.style.width = "0%";
      prog.innerHTML = `<span class="text-danger">上传失败：${escapeHtml(e.message || "未知错误")}</span>`;
      toast(e.message || "上传失败", "error");
    }
    throw e;
  }
}

/* ========================= 启动 ========================= */
["/", "/login", "/register", "/chat", "/favorites", "/history", "/profile", "/upload", "*"].forEach((p) => {
  route(p, () => dispatchRender());
});

startRouter();
