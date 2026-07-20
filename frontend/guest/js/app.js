/**
 * 访客端应用入口（手册 5.1.1）
 * - 未登录访客：仅智能问答
 * - 注册用户：问答 + 历史 + 个人中心
 * - 员工：再加文档上传
 * - 管理员：登录后进入管理端
 * 登录页独立；注册内嵌于登录页
 */

import { route, startRouter, navigate, currentPath } from "/assets/js/router.js";
import { api, askStream, clearDemoFlags } from "/assets/js/api.js";
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
} from "/assets/js/auth.js";
import { escapeHtml, formatDateTime, toast, confirmDialog } from "/assets/js/utils.js";
import { initFlowField } from "/assets/js/flow-field.js?v=ui-20260720";

clearDemoFlags();
initFlowField();

/** 当前问答会话 ID（多轮上下文） */
let currentSessionId = null;
/** 流式请求控制器 */
let askAbort = null;
/** 待从历史打开的会话 ID（跳转问答页后由 pageChat 加载） */
let pendingOpenSessionId = null;

/** 登录/退出后清空本地会话上下文，避免沿用上一身份的 session_id */
function resetLocalChatContext() {
  currentSessionId = null;
  pendingOpenSessionId = null;
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
 * 兼容 <think> / <think> / <thinking>，含流式未闭合。
 */
function splitModelReasoning(raw) {
  const text = String(raw || "");
  const openRe = /<(?:redacted_thinking|think|thinking)>/i;
  const closeRe = /<\/(?:redacted_thinking|think|thinking)>/i;
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

/** 渲染助手气泡：推理默认折叠，正文在外 */
function renderAssistantBubbleHtml(rawText, extrasHtml = "") {
  const { reasoning, answer, reasoningOpen } = splitModelReasoning(rawText);
  const answerHtml = escapeHtml((answer || "").trim() || (reasoningOpen ? "（模型推理中…）" : ""));
  let reasoningHtml = "";
  if (reasoning) {
    const label = reasoningOpen ? "推理过程（生成中）" : "推理过程";
    reasoningHtml = `<details class="model-reasoning"${reasoningOpen ? " open" : ""}>
      <summary>${label}</summary>
      <pre class="model-reasoning-body">${escapeHtml(reasoning)}</pre>
    </details>`;
  }
  return `${reasoningHtml}<div class="msg-answer">${answerHtml}</div>${extrasHtml || ""}`;
}

/** 登录成功后按角色跳转 */
function redirectAfterLogin() {
  const target = getPostLoginTarget();
  if (target.type === "admin") {
    location.href = target.href;
    return;
  }
  navigate(target.path || "/");
  dispatchRender();
}

/** 按角色生成顶栏导航项（访客仅问答） */
function buildNavItems(path, role) {
  const items = [];
  items.push({ path: "/", label: "智能问答", show: true });
  // 员工与管理员可上传
  items.push({ path: "/upload", label: "文档上传", show: canUpload() });
  // 已登录才有历史与个人中心（访客不可见）
  items.push({ path: "/history", label: "对话历史", show: role !== "guest" });
  items.push({ path: "/profile", label: "个人中心", show: role !== "guest" });
  return items
    .filter((i) => i.show)
    .map(
      (i) =>
        `<div class="nav-item ${path === i.path ? "active" : ""}" data-go="${i.path}">${i.label}</div>`
    )
    .join("");
}

/** 渲染业务页顶栏壳层（登录页不使用） */
function renderShell(activeTitle, { wide = false } = {}) {
  const logged = isLoggedIn();
  const user = getUser();
  const role = getPrimaryRole();
  const path = currentPath();
  const roleText = logged
    ? `${escapeHtml(user?.nickname || user?.username || "")} · ${getRoleLabel(role)}`
    : "访客 · 仅公开知识库问答";

  document.getElementById("app").innerHTML = `
    <div class="app-shell">
      <header class="topnav">
        <div class="topnav-brand" data-go="/" title="回到问答">
          <i class="logo-dot"></i>
          <span>AI 知识库</span>
        </div>
        <nav class="topnav-links" aria-label="主导航">${buildNavItems(path, role)}</nav>
        <div class="topnav-actions">
          <span class="text-muted">${roleText}</span>
          ${canAccessAdmin() ? `<a class="btn btn-secondary btn-sm" href="/admin/">管理端</a>` : ""}
          ${
            logged
              ? `<button type="button" class="btn btn-text" id="btnLogout">退出</button>`
              : `<button type="button" class="btn btn-sm" data-go="/login">登录</button>`
          }
        </div>
      </header>
      <div class="page-bar">
        <div class="page-bar-title">${escapeHtml(activeTitle)}</div>
      </div>
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
      // 退出后直接回到独立登录页
      navigate("/login");
      dispatchRender();
    });
  }
}

/** 路由分发 */
function dispatchRender() {
  const path = currentPath();
  // 注册并入登录页
  if (path === "/login" || path === "/register") return pageAuth(path === "/register" ? "register" : "login");
  // 访客不可进历史/个人中心/上传：提示登录或权限
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

  document.getElementById("pageRoot").innerHTML = `
    <div class="qa-layout">
      <div class="qa-chat-column">
        <div class="qa-messages" id="msgList">
          <div class="empty-state" id="msgEmpty">
            <div class="qa-welcome-mark">AI</div>
            <h1>有什么可以帮你检索？</h1>
            <p>${tip}</p>
            <div class="qa-welcome-note">回答将展示引用来源、文档名、分段序号与置信提示；无法命中时不会编造来源。</div>
            <div class="qa-suggestions">
              <button type="button" data-question="请介绍当前可访问的知识库内容">了解知识库内容</button>
              <button type="button" data-question="如何上传并管理文档？">如何管理文档</button>
              <button type="button" data-question="请说明平台的权限访问规则">查看权限规则</button>
            </div>
          </div>
        </div>
        <div class="qa-composer">
          <textarea class="form-control" id="questionInput" placeholder="请输入问题，Enter 发送，Shift+Enter 换行"></textarea>
          <button type="button" class="btn" id="btnSend">发送</button>
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

  // 从历史打开会话：渲染完成后加载该会话消息（避免路由二次渲染清空）
  if (pendingOpenSessionId) {
    const sid = pendingOpenSessionId;
    pendingOpenSessionId = null;
    currentSessionId = sid;
    loadSessionMessages(sid);
  }
}

/** 拉取并渲染指定会话的历史消息到问答页 */
async function loadSessionMessages(sessionId) {
  try {
    const detail = await api.get(`/qa/sessions/${sessionId}?page=1&page_size=100`);
    const list = document.getElementById("msgList");
    if (!list) return;
    list.innerHTML = "";
    const messages = detail.items || detail.messages || [];
    if (!messages.length) {
      list.innerHTML = `<div class="empty-state">该会话暂无消息</div>`;
      return;
    }
    messages.forEach((m) => {
      const html =
        m.role === "assistant"
          ? `${renderAssistantBubbleHtml(
              m.content || "",
              m.citations
                ? `<div class="citations"><div class="citation-heading">引用来源（共 ${(m.citations || []).length} 段，点击展开原文）</div>${(m.citations || [])
                    .map(
                      (c) =>
                        `<details class="citation-item"><summary class="citation-meta">${escapeHtml(c.doc_name)} · #${c.chunk_index}</summary><div class="citation-content">${escapeHtml(c.content || "")}</div></details>`
                    )
                    .join("")}</div>`
                : ""
            )}`
          : escapeHtml(m.content);
      appendMessage(m.role === "user" ? "user" : "assistant", html);
    });
  } catch (e) {
    toast(e.message || "加载会话失败", "error");
  }
}

/** 追加一条消息气泡 */
function appendMessage(role, contentHtml) {
  // 隐藏空状态
  const empty = document.getElementById("msgEmpty");
  if (empty) empty.remove();
  const list = document.getElementById("msgList");
  const row = document.createElement("div");
  row.className = `msg-row ${role}`;
  row.innerHTML = `<div class="msg-bubble">${contentHtml}</div>`;
  list.appendChild(row);
  // 滚到底部
  list.scrollTop = list.scrollHeight;
  return row.querySelector(".msg-bubble");
}

/** 推理步骤类型图标映射 */
const reasoningTypeIcons = {
  rewrite: "✍️",
  retrieval: "🔍",
  rerank: "📊",
  generation: "💡",
};

/** 推理步骤类型标题映射 */
const reasoningTypeTitles = {
  rewrite: "查询改写",
  retrieval: "多路检索",
  rerank: "重排与筛选",
  assembly: "上下文组装",
  generation: "生成回答",
};

/** 清空推理面板 */
function clearReasoningPanel() {
  const stepsContainer = document.getElementById("reasoningSteps");
  if (stepsContainer) {
    stepsContainer.innerHTML = "";
  }
}

/** 追加推理步骤卡片 */
function appendReasoningStep(step) {
  const stepsContainer = document.getElementById("reasoningSteps");
  if (!stepsContainer) return;

  const icon = reasoningTypeIcons[step.type] || "📌";
  const title = reasoningTypeTitles[step.type] || step.content || "处理步骤";
  const status = step.status || "processing";
  const isCompleted = status === "completed";
  const isActive = status === "processing";

  const stepEl = document.createElement("div");
  stepEl.className = `reasoning-step ${isCompleted ? "completed" : isActive ? "active" : ""}`;
  stepEl.dataset.step = step.step;

  const statusIcon = isCompleted ? "✅" : isActive ? "◯" : "○";

  stepEl.innerHTML = `
    <div class="reasoning-step-icon ${isActive ? "loading" : ""}">${statusIcon}</div>
    <div class="reasoning-step-content">
      <div class="reasoning-step-title">${icon} ${escapeHtml(title)}</div>
      <div class="reasoning-step-detail">${escapeHtml(step.detail || "")}</div>
      ${step.elapsed_ms !== undefined ? `<div class="reasoning-step-time">耗时 ${step.elapsed_ms}ms</div>` : ""}
    </div>
  `;

  stepsContainer.appendChild(stepEl);
  stepsContainer.scrollTop = stepsContainer.scrollHeight;

  return stepEl;
}

/** 更新推理步骤状态 */
function updateReasoningStep(stepNum, status, elapsedMs) {
  const stepsContainer = document.getElementById("reasoningSteps");
  if (!stepsContainer) return;

  const stepEl = stepsContainer.querySelector(`.reasoning-step[data-step="${stepNum}"]`);
  if (!stepEl) return;

  stepEl.classList.remove("active", "completed");
  stepEl.classList.add(status);

  const iconEl = stepEl.querySelector(".reasoning-step-icon");
  if (iconEl) {
    iconEl.classList.remove("loading");
    iconEl.textContent = status === "completed" ? "✅" : "◯";
  }

  if (elapsedMs !== undefined) {
    const timeEl = stepEl.querySelector(".reasoning-step-time");
    if (timeEl) {
      timeEl.textContent = `耗时 ${elapsedMs}ms`;
    } else {
      const contentEl = stepEl.querySelector(".reasoning-step-content");
      if (contentEl) {
        contentEl.innerHTML += `<div class="reasoning-step-time">耗时 ${elapsedMs}ms</div>`;
      }
    }
  }
}

/** 发送问题并 SSE 流式展示（手册交互流程） */
async function sendQuestion() {
  const input = document.getElementById("questionInput");
  const question = (input.value || "").trim();
  // 空问题拦截
  if (!question) {
    toast("请输入问题", "error");
    return;
  }
  // 展示用户气泡
  appendMessage("user", escapeHtml(question));
  // 清空输入框
  input.value = "";
  // 创建助手气泡（打字机写入）
  const bubble = appendMessage("assistant", "");
  // 清空推理面板
  clearReasoningPanel();
  // 取消上一次未完成请求
  if (askAbort) askAbort.abort();
  askAbort = new AbortController();

  let citationsHtml = "";
  let confidenceTip = "";
  let hasTraces = false;
  let rawAssistantText = "";

  const handleTrace = (trace) => {
    hasTraces = true;
    const existing = document.querySelector(`.reasoning-step[data-step="${trace.step}"]`);
    if (existing) {
      updateReasoningStep(trace.step, trace.status, trace.elapsed_ms);
    } else {
      appendReasoningStep(trace);
    }
  };

  const runAsk = async (sessionId) => {
    citationsHtml = "";
    confidenceTip = "";
    hasTraces = false;
    rawAssistantText = "";
    bubble.innerHTML = "";
    clearReasoningPanel();
    await askStream(
      {
        question,
        session_id: sessionId || undefined,
        // 不传 kb_ids：由后端按访客/登录身份过滤范围
      },
      {
        signal: askAbort.signal,
        onEvent: (event, data) => {
          // 推理步骤追踪（后端新事件类型）
          if (event === "reasoning") {
            handleTrace(data);
            return;
          }
          // 推理步骤追踪（兼容旧事件类型）
          if (event === "trace") {
            handleTrace(data);
            return;
          }
          // 推理步骤列表（批量，兼容旧事件类型）
          if (event === "traces") {
            const traces = data.items || data || [];
            traces.forEach((t) => handleTrace(t));
            return;
          }
          // 增量文本：拆分模型推理标签，正文展示，推理默认折叠
          if (event === "chunk") {
            bubble.classList.add("streaming-cursor");
            rawAssistantText += data.content || data || "";
            bubble.innerHTML = renderAssistantBubbleHtml(rawAssistantText);
            document.getElementById("msgList").scrollTop = document.getElementById("msgList").scrollHeight;
          }
          // 引用来源
          if (event === "citations") {
            const items = data.items || data || [];
            if (!items.length) {
              citationsHtml = `<div class="citations text-muted">未命中可引用分段，不会编造来源。</div>`;
            } else {
              citationsHtml = `<div class="citations"><div class="citation-heading">引用来源（共 ${items.length} 段，点击展开原文）</div>${items
                .map(
                  (c) => `<details class="citation-item">
                    <summary class="citation-meta">${escapeHtml(c.doc_name || "未知文档")} · 分段 #${escapeHtml(c.chunk_index)} · 置信 ${(Number(c.score || 0) * 100).toFixed(0)}%</summary>
                    <div class="citation-content">${escapeHtml(c.content || "")}</div>
                  </details>`
                )
                .join("")}</div>`;
            }
          }
          // 结束
          if (event === "done") {
            bubble.classList.remove("streaming-cursor");
            currentSessionId = data.session_id || currentSessionId;
            const conf = data.confidence || "medium";
            const map = { high: "高", medium: "中", low: "低" };
            confidenceTip = `<div class="confidence">置信提示：${map[conf] || conf}（仅供参考，请结合引文核对）</div>`;
            bubble.innerHTML = renderAssistantBubbleHtml(rawAssistantText, `${citationsHtml}${confidenceTip}`);
          }
          // 错误
          if (event === "error") {
            const msg = data.message || data || "问答失败";
            // 身份切换后沿用旧会话时后端返回无权访问：清会话并新建一次
            if (typeof msg === "string" && msg.includes("无权访问") && sessionId) {
              throw Object.assign(new Error(msg), { code: "SESSION_FORBIDDEN" });
            }
            bubble.innerHTML = `<span class="text-danger">${escapeHtml(msg)}</span>`;
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
        bubble.innerHTML = `<span class="text-danger">${escapeHtml(retryErr.message || "问答失败")}</span>`;
        return;
      }
    }
    bubble.innerHTML = `<span class="text-danger">${escapeHtml(err.message || "问答失败")}</span>`;
  }
}

/* ========================= 独立登录页（内嵌注册） ========================= */
function pageAuth(initialTab = "login") {
  // 已登录则按角色回首页 / 管理端
  if (isLoggedIn()) {
    redirectAfterLogin();
    return;
  }

  // 独立全屏，不走业务顶栏
  document.getElementById("app").innerHTML = `
    <div class="auth-page">
      <div class="auth-page-brand" data-go="/">
        <i class="logo-dot"></i>
        <span>AI 知识库</span>
      </div>
      <div class="card auth-card">
        <div class="auth-tabs" role="tablist">
          <button type="button" class="auth-tab ${initialTab === "login" ? "active" : ""}" data-tab="login">登录</button>
          <button type="button" class="auth-tab ${initialTab === "register" ? "active" : ""}" data-tab="register">注册</button>
        </div>
        <div id="authPanel"></div>
      </div>
      <button type="button" class="btn btn-text" data-go="/">以访客身份继续问答（仅公开库）</button>
    </div>
  `;

  const panel = document.getElementById("authPanel");
  const showTab = (tab) => {
    document.querySelectorAll(".auth-tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
    // 仅同步 hash，避免再次触发整页重渲染
    const next = tab === "register" ? "#/register" : "#/login";
    if (location.hash !== next) history.replaceState(null, "", next);
    if (tab === "register") renderRegisterForm(panel);
    else renderLoginForm(panel);
  };

  document.querySelectorAll(".auth-tab").forEach((btn) => {
    btn.addEventListener("click", () => showTab(btn.dataset.tab));
  });
  document.querySelectorAll("[data-go]").forEach((el) => {
    el.addEventListener("click", () => navigate(el.getAttribute("data-go")));
  });

  showTab(initialTab === "register" ? "register" : "login");
}

/** 登录表单 */
function renderLoginForm(panel) {
  panel.innerHTML = `
    <p class="text-muted auth-lead">不同角色登录后看到的入口不同：访客仅问答，员工可上传，管理员进控制台。</p>
    <div class="form-group"><label>用户名</label><input class="form-control" id="loginUser" type="text" autocomplete="username" placeholder="用户名" /></div>
    <div class="form-group"><label>密码</label><input class="form-control" id="loginPass" type="password" autocomplete="current-password" placeholder="密码" /></div>
    <button class="btn" id="btnDoLogin" style="width:100%">登录</button>
  `;
  document.getElementById("btnDoLogin").addEventListener("click", doLogin);
  document.getElementById("loginPass").addEventListener("keydown", (e) => {
    if (e.key === "Enter") doLogin();
  });
}

/** 注册表单（默认注册用户，无上传） */
function renderRegisterForm(panel) {
  panel.innerHTML = `
    <p class="text-muted auth-lead">注册后默认「注册用户」角色，可问答与查看本人历史；上传需管理员分配员工权限。</p>
    <div class="form-group"><label>用户名（3-50）</label><input class="form-control" id="regUser" /></div>
    <div class="form-group"><label>邮箱</label><input class="form-control" id="regEmail" type="email" /></div>
    <div class="form-group"><label>昵称（可选）</label><input class="form-control" id="regNick" /></div>
    <div class="form-group"><label>密码（至少 8 位）</label><input class="form-control" id="regPass" type="password" /></div>
    <button class="btn" id="btnDoReg" style="width:100%">注册并前往登录</button>
  `;
  document.getElementById("btnDoReg").addEventListener("click", doRegister);
}

async function doLogin() {
  const username = document.getElementById("loginUser").value.trim();
  const password = document.getElementById("loginPass").value;
  if (!username || !password) return toast("请填写用户名和密码", "error");
  try {
    const data = await api.post("/auth/login", { username, password });
    if (!data?.access_token) throw new Error("登录失败：未返回令牌");
    replaceAuthSession({
      access_token: data.access_token,
      refresh_token: data.refresh_token,
      user: { username },
    });
    const me = await api.get("/auth/me");
    replaceAuthSession({
      access_token: data.access_token,
      refresh_token: data.refresh_token,
      user: me,
    });
    // 登录后身份变化：丢弃访客期会话，避免「无权访问该会话」
    resetLocalChatContext();
    const role = getPrimaryRole();
    toast(`登录成功（${getRoleLabel(role)}）`, "success");
    redirectAfterLogin();
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
    // 切回登录页并预填用户名
    pageAuth("login");
    setTimeout(() => {
      const el = document.getElementById("loginUser");
      if (el) el.value = username;
    }, 0);
  } catch (e) {
    toast(e.message || "注册失败", "error");
  }
}

/* ========================= 对话历史 /history ========================= */
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
      document.getElementById("pageRoot").innerHTML = `<div class="card empty-state">暂无历史会话</div>`;
      return;
    }
    document.getElementById("pageRoot").innerHTML = `
      <div class="card">
        <h2 class="card-title">我的会话</h2>
        <div id="historyList">
          ${items
            .map(
              (s) => `<div class="history-item" data-id="${escapeHtml(s.id)}">
                <div><strong>${escapeHtml(s.title || "未命名会话")}</strong><div class="text-muted">${formatDateTime(s.updated_at)} · ${escapeHtml(s.message_count || 0)} 条消息</div></div>
                <button class="btn btn-secondary btn-sm" data-open="${escapeHtml(s.id)}">打开</button>
              </div>`
            )
            .join("")}
        </div>
      </div>`;
    // 打开会话：写入 sessionId 并跳转问答页
    document.querySelectorAll("[data-open]").forEach((btn) => {
      btn.addEventListener("click", () => {
        // 记录待打开会话，跳转问答页后由 pageChat 统一加载消息
        pendingOpenSessionId = btn.getAttribute("data-open");
        navigate("/");
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
      <div class="card" style="max-width:560px">
        <h2 class="card-title">个人资料</h2>
        <div class="form-group"><label>用户名</label><input class="form-control" id="pfUser" value="${escapeHtml(me.username || "")}" disabled /></div>
        <div class="form-group"><label>昵称</label><input class="form-control" id="pfNick" value="${escapeHtml(me.nickname || "")}" /></div>
        <div class="form-group"><label>邮箱</label><input class="form-control" id="pfEmail" value="${escapeHtml(me.email || "")}" /></div>
        <div class="form-group"><label>角色</label><div>${escapeHtml((me.roles || [me.role]).filter(Boolean).join(", ") || "-")}</div></div>
        <div class="form-group"><label>最近登录</label><div class="text-muted">${formatDateTime(me.last_login_at)}</div></div>
        <button class="btn" id="btnSaveProfile">保存资料</button>
        <hr style="border:none;border-top:1px solid var(--color-border);margin:20px 0" />
        <h3 class="card-title">我的上传记录</h3>
        <p class="text-muted">上传记录请在管理端知识库文档列表中查看。</p>
      </div>`;
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
    <div class="card upload-panel">
      <h2 class="card-title">上传文档到知识库</h2>
      <p class="text-muted">当前身份：${getRoleLabel()}${getDepartment() ? ` · 部门 ${getDepartment()}` : ""}。管理员/超管可上传至任意库；员工仅本部门或授权知识库。类型与大小由服务端最终校验。</p>
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
      <div class="upload-drop" id="dropZone">点击或拖拽文件到此处</div>
      <input type="file" id="fileInput" class="hidden" accept=".pdf,.doc,.docx,.txt,.md,text/markdown,application/pdf" />
      <div class="form-group" style="margin-top:12px">
        <label>处理进度</label>
        <div class="card" style="padding:10px">
          <div id="uploadProgress" class="text-muted">尚未开始</div>
          <div style="height:8px;background:#E8F0FE;border-radius:4px;margin-top:8px;overflow:hidden">
            <div id="uploadBar" style="height:100%;width:0;background:var(--color-primary);transition:width .2s"></div>
          </div>
        </div>
      </div>
    </div>`;

  const drop = document.getElementById("dropZone");
  const fileInput = document.getElementById("fileInput");
  drop.onclick = () => fileInput.click();
  drop.addEventListener("dragover", (e) => {
    e.preventDefault();
    drop.classList.add("dragover");
  });
  drop.addEventListener("dragleave", () => drop.classList.remove("dragover"));
  drop.addEventListener("drop", (e) => {
    e.preventDefault();
    drop.classList.remove("dragover");
    if (e.dataTransfer.files[0]) handleUpload(e.dataTransfer.files[0]);
  });
  fileInput.onchange = () => {
    if (fileInput.files[0]) handleUpload(fileInput.files[0]);
  };
}

/** 执行上传并模拟/展示进度 */
async function handleUpload(file) {
  const kbId = document.getElementById("kbSelect").value;
  if (!kbId) return toast("请选择知识库", "error");
  const prog = document.getElementById("uploadProgress");
  const bar = document.getElementById("uploadBar");
  prog.textContent = `正在上传 ${file.name}…`;
  bar.style.width = "20%";

  const fd = new FormData();
  fd.append("file", file);

  try {
    // 契约路径：POST /knowledge-bases/{id}/documents/upload
    await api.upload(`/knowledge-bases/${kbId}/documents/upload`, fd);
    bar.style.width = "100%";
    prog.innerHTML = `<span class="text-success">上传成功，已进入预处理/向量化队列</span>`;
    toast("上传成功", "success");
  } catch (e) {
    bar.style.width = "0%";
    prog.innerHTML = `<span class="text-danger">上传失败：${escapeHtml(e.message || "未知错误")}</span>`;
    toast(e.message || "上传失败", "error");
  }
}

/* ========================= 启动 ========================= */
["/", "/login", "/register", "/history", "/profile", "/upload", "*"].forEach((p) => {
  route(p, () => dispatchRender());
});

startRouter();
