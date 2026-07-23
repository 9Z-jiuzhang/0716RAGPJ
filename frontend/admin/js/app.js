/**
 * 管理端应用（手册 5.1.2）
 * 路由：/admin 仪表盘、users、roles、models、knowledge-bases、
 * documents、snapshots、hit-test、audit、monitor
 * 顶栏提供「智能对话」与「退出」（手册 4.3）
 */

import { route, startRouter, navigate, currentPath } from "/assets/js/router.js?v=gap-opt-0721s";
import { api, clearDemoFlags } from "/assets/js/api.js?v=bug-ui-palette-0721ek";
import { isLoggedIn, getUser, clearAuth, hasPermission, canAccessAdmin, getRoleLabel, isSuperAdmin, isAdminUser } from "/assets/js/auth.js?v=gap-opt-0721s";
import { escapeHtml, formatDateTime, formatDateTimeHtml, toast, confirmDialog, pollUntil, openChangePasswordModal } from "/assets/js/utils.js?v=bug-ui-palette-0721ea";
import { initMotion, runCountUps } from "/assets/js/motion.js?v=bug-ui-palette-0721ea";
import { initTheme, applyTheme, getTheme } from "/assets/js/theme.js?v=gap-opt-0721s";

clearDemoFlags();
initTheme();
initMotion();

/** 将 0~1 置信度安全格式化为百分比文案；非法则 -- */
function formatPercentCell(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n < 0) return "--";
  let bounded;
  if (n <= 1) bounded = n;
  else if (n <= 1.5) bounded = 1;
  else if (n <= 100) bounded = n / 100;
  else return "--";
  bounded = Math.max(0, Math.min(1, bounded));
  return `${Math.round(bounded * 100)}%`;
}

function formatPercentSafe(value, suffix) {
  const cell = formatPercentCell(value);
  if (cell === "--") return "";
  return `（${cell}${suffix ? `，${suffix}` : ""}）`;
}

/**
 * 方案 B：首页 + 当前±siblings + 末页；缺口用可点击省略号（跳转 ±jumpStep）。
 * 相邻仅差 1 页时补全，避免「1 … 3」。
 * @returns {({type:"page",page:number}|{type:"ellipsis",dir:"prev"|"next"})[]}
 */
function compactPageItems(totalPages, { current = 1, siblings = 1 } = {}) {
  const total = Math.max(1, Number(totalPages) || 1);
  const cur = Math.max(1, Math.min(total, Math.trunc(Number(current)) || 1));
  const sib = Math.max(0, Math.trunc(Number(siblings)) || 0);

  // 页数不多时全部展示（首+窗+尾+两侧省略的理论上限）
  if (total <= sib * 2 + 5) {
    return Array.from({ length: total }, (_, i) => ({ type: "page", page: i + 1 }));
  }

  const pages = new Set([1, total]);
  for (let i = cur - sib; i <= cur + sib; i += 1) {
    if (i >= 1 && i <= total) pages.add(i);
  }

  const sorted = [...pages].sort((a, b) => a - b);
  /** 缺口只差 1 页则补上，少造省略号 */
  for (let i = 1; i < sorted.length; i += 1) {
    if (sorted[i] - sorted[i - 1] === 2) pages.add(sorted[i - 1] + 1);
  }
  const finalPages = [...pages].sort((a, b) => a - b);
  const items = [];
  finalPages.forEach((p, idx) => {
    if (idx > 0 && p - finalPages[idx - 1] > 1) {
      // 省略号在当前页左侧 → 向前跳；右侧 → 向后跳
      const dir = p <= cur ? "prev" : "next";
      items.push({ type: "ellipsis", dir });
    }
    items.push({ type: "page", page: p });
  });
  return items;
}

/** @returns {{ buttons: string, jump: string }} */
function renderCompactPagerParts(currentPage, totalPages) {
  const current = Math.max(1, Number(currentPage) || 1);
  const total = Math.max(1, Number(totalPages) || 1);
  const jumpStep = 5;
  const buttons = compactPageItems(total, { current, siblings: 1 })
    .map((item) => {
      if (item.type === "ellipsis") {
        const label = item.dir === "prev" ? `向前 ${jumpStep} 页` : `向后 ${jumpStep} 页`;
        return `<button type="button" class="btn btn-secondary btn-sm pager-ellipsis" data-ellipsis-dir="${item.dir}" data-ellipsis-step="${jumpStep}" title="${label}" aria-label="${label}">…</button>`;
      }
      const active = item.page === current;
      return `<button type="button" class="btn btn-sm ${active ? "" : "btn-secondary"}" data-goto-page="${item.page}" ${active ? 'aria-current="page"' : ""}>${item.page}</button>`;
    })
    .join("");
  const jump = `<label class="pager-jump">
      <span>前往</span>
      <input type="number" class="form-control pager-jump-input" data-page-jump min="1" max="${total}" value="${current}" aria-label="跳转页码" />
      <span>/ ${total} 页</span>
      <button type="button" class="btn btn-secondary btn-sm" data-page-jump-go>跳转</button>
    </label>`;
  return { buttons, jump };
}

/** 兼容旧调用 */
function renderCompactPagerButtons(currentPage, totalPages) {
  const { buttons, jump } = renderCompactPagerParts(currentPage, totalPages);
  return `${buttons}${jump}`;
}

/**
 * 绑定上一页/下一页/页码/省略号跳段/跳转
 * @param {{ page: number, totalPages: number, onGo: (p:number)=>void }} opts
 */
function bindCompactPager(pager, { page, totalPages, onGo }) {
  if (!pager || typeof onGo !== "function") return;
  const total = Math.max(1, Number(totalPages) || 1);
  const go = (p) => {
    const next = Math.trunc(Number(p));
    if (!Number.isFinite(next) || next < 1 || next > total || next === page) return;
    onGo(next);
  };
  pager.querySelector("[data-page-prev]")?.addEventListener("click", () => go(page - 1));
  pager.querySelector("[data-page-next]")?.addEventListener("click", () => go(page + 1));
  pager.querySelectorAll("[data-goto-page]").forEach((btn) => {
    btn.addEventListener("click", () => go(btn.getAttribute("data-goto-page")));
  });
  pager.querySelectorAll("[data-ellipsis-dir]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const dir = btn.getAttribute("data-ellipsis-dir");
      const step = Math.max(1, Math.trunc(Number(btn.getAttribute("data-ellipsis-step"))) || 5);
      go(dir === "prev" ? Math.max(1, page - step) : Math.min(total, page + step));
    });
  });
  const input = pager.querySelector("[data-page-jump]");
  const jumpGo = () => go(input?.value);
  pager.querySelector("[data-page-jump-go]")?.addEventListener("click", jumpGo);
  input?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      jumpGo();
    }
  });
}

/** LLM Guard 意图码 → 中文展示 */
const GUARD_INTENT_LABELS = {
  knowledge_query: "知识查询",
  document_lookup: "文档查找",
  admin_operation: "管理操作",
  greeting: "问候交流",
  security_education: "安全教育",
  prompt_injection: "提示注入",
  secret_exfiltration: "密钥窃取",
  authorization_bypass: "越权绕过",
  destructive_operation: "破坏性操作",
  command_execution: "命令执行",
  unknown: "未知",
};

function guardIntentLabel(intent) {
  const key = String(intent || "").trim().toLowerCase();
  if (!key) return "-";
  return GUARD_INTENT_LABELS[key] || key;
}

/** 管理端置顶菜单（无分组标题） */
const MENU_TOP = [{ path: "/admin", label: "首页", perm: "system:read" }];

/** 管理端菜单（分组可折叠；按权限码裁剪；前端隐藏不能替代后端鉴权） */
const MENU_GROUPS = [
  {
    id: "org",
    title: "组织与权限",
    items: [
      { path: "/admin/users", label: "用户管理", perm: "user:read" },
      { path: "/admin/roles", label: "角色管理", perm: "role:read" },
      { path: "/admin/departments", label: "部门管理", perm: "department:read" },
    ],
  },
  {
    id: "knowledge",
    title: "知识资产",
    items: [
      { path: "/admin/models", label: "大模型管理", perm: "model:read" },
      { path: "/admin/knowledge-bases", label: "知识库管理", perm: "kb:read" },
      { path: "/admin/qa-sessions", label: "会话分析", perm: "system:read" },
    ],
  },
  {
    id: "quality",
    title: "质量评测",
    items: [
      { path: "/admin/ragas", label: "RAGAS 评估", perm: "system:read" },
      { path: "/admin/hit-test", label: "命中率测试", perm: "test:read" },
    ],
  },
  {
    id: "ops-security",
    title: "系统运维与安全",
    items: [
      { path: "/admin/role-caches", label: "角色缓存", perm: "system:read" },
      { path: "/admin/guard", label: "LLM Guard 拦截", perm: "system:read" },
      { path: "/admin/audit", label: "审计日志", perm: "audit:read" },
      { path: "/admin/monitor", label: "系统监控", perm: "system:read" },
    ],
  },
  {
    id: "developer",
    title: "开发者接入",
    items: [{ path: "/admin/fastapi", label: "API 接入指南", perm: "system:read" }],
  },
];

/** 扁平菜单（路由/兼容用） */
const MENUS = [...MENU_TOP, ...MENU_GROUPS.flatMap((g) => g.items)];

const SIDEBAR_COLLAPSE_KEY = "admin-sidebar-collapsed";
/** 首次进入（无本地记忆）时默认展开的分组 */
const SIDEBAR_DEFAULT_EXPANDED = new Set(["org", "knowledge", "quality"]);
/** 侧栏导航滚动位置：整壳重绘后恢复，避免点底部菜单时跳回顶部 */
let sidebarNavScrollTop = 0;

/** 读取侧栏分组折叠状态（不含当前路由强制展开的覆盖）。 */
function readSidebarCollapsedMap() {
  try {
    const raw = localStorage.getItem(SIDEBAR_COLLAPSE_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function writeSidebarCollapsedMap(map) {
  try {
    localStorage.setItem(SIDEBAR_COLLAPSE_KEY, JSON.stringify(map));
  } catch {
    /* ignore quota / private mode */
  }
}

/** 无本地记忆时：默认展开组织与权限 / 知识资产 / 质量评测，其余折叠。 */
function isSidebarGroupCollapsedDefault(groupId) {
  return !SIDEBAR_DEFAULT_EXPANDED.has(groupId);
}

/** 当前路径是否落在该分组的任一可见菜单下。 */
function menuGroupHasActivePath(group, path) {
  return group.items.some((m) => path === m.path || (m.path !== "/admin" && path.startsWith(m.path)));
}

/** 页面级权限门禁（防深链绕过菜单隐藏） */
function requirePerm(perm, title) {
  if (!renderShell(title)) return false;
  if (!hasPermission(perm)) {
    document.getElementById("pageRoot").innerHTML = `<div class="card empty-state">无权限访问本页（需要 <code>${escapeHtml(perm)}</code>）</div>`;
    return false;
  }
  return true;
}

/** 登录门禁：未登录或不具备管理权限则回访客登录页 */
function guard() {
  if (!isLoggedIn()) {
    toast("请先登录管理端", "error");
    location.href = "/#/";
    return false;
  }
  if (!canAccessAdmin()) {
    toast("当前账号无管理端权限", "error");
    location.href = "/#/chat";
    return false;
  }
  return true;
}

/** 渲染管理端壳层：侧栏导航 + 顶部工具栏，权限判断逻辑保持不变。 */
function renderShell(title) {
  if (!guard()) return false;
  const user = getUser() || {};
  const path = currentPath();
  const displayName = escapeHtml(user.nickname || user.username || "管理员");
  const roleText = `${displayName} · ${getRoleLabel()}`;

  const prevNav = document.querySelector(".app-shell-admin .sidebar-nav");
  if (prevNav) sidebarNavScrollTop = prevNav.scrollTop;

  document.getElementById("app").innerHTML = `
    <div class="ambient-orbs" aria-hidden="true"><i></i><i></i><i></i></div>
    <div class="app-shell app-shell-admin">
      <aside class="sidebar" aria-label="管理导航">
        <div class="sidebar-brand" data-go="/admin" title="管理首页">
          <i class="logo-dot"></i>
          <span><b>Knowledge</b> AI<small>智能知识中枢</small></span>
        </div>
        <nav class="sidebar-nav" aria-label="管理导航分组">
          ${(() => {
            const collapsedMap = readSidebarCollapsedMap();
            const topLinks = MENU_TOP.filter((m) => hasPermission(m.perm))
              .map((m) => {
                const active = path === m.path || (m.path !== "/admin" && path.startsWith(m.path));
                return `<button type="button" class="nav-item ${active ? "active" : ""}" data-go="${m.path}"><i></i>${m.label}</button>`;
              })
              .join("");
            const topHtml = topLinks ? `<div class="sidebar-top">${topLinks}</div>` : "";
            const groupsHtml = MENU_GROUPS.map((group) => {
              const visibleItems = group.items.filter((m) => hasPermission(m.perm));
              if (!visibleItems.length) return "";
              const hasActive = menuGroupHasActivePath(group, path);
              // 含当前页的分组始终展开；有本地记忆则遵循；否则用首次默认展开集。
              const collapsed = hasActive
                ? false
                : Object.prototype.hasOwnProperty.call(collapsedMap, group.id)
                  ? Boolean(collapsedMap[group.id])
                  : isSidebarGroupCollapsedDefault(group.id);
              const links = visibleItems
                .map((m) => {
                  const active = path === m.path || (m.path !== "/admin" && path.startsWith(m.path));
                  return `<button type="button" class="nav-item ${active ? "active" : ""}" data-go="${m.path}"><i></i>${m.label}</button>`;
                })
                .join("");
              return `<div class="sidebar-group ${collapsed ? "is-collapsed" : ""} ${hasActive ? "has-active" : ""}" data-group-id="${escapeHtml(group.id)}">
                <button type="button" class="sidebar-caption ${hasActive ? "is-active-parent" : ""}" data-toggle-group="${escapeHtml(group.id)}" aria-expanded="${collapsed ? "false" : "true"}">
                  <span class="sidebar-caption-label">${escapeHtml(group.title)}</span>
                  <span class="sidebar-caption-chevron" aria-hidden="true"></span>
                </button>
                <div class="sidebar-links">${links}</div>
              </div>`;
            }).join("");
            return topHtml + groupsHtml;
          })()}
        </nav>
        <div class="sidebar-user">
          <span class="avatar-mark">${displayName.slice(0, 1)}</span>
          <span><b>${displayName}</b><small>${escapeHtml(getRoleLabel())}</small></span>
        </div>
      </aside>
      <section class="app-main">
        <header class="topnav">
          <div class="page-bar-title">${escapeHtml(title)}</div>
          <div class="topnav-actions">
            ${
              isSuperAdmin()
                ? ""
                : `<button type="button" class="btn btn-secondary btn-sm" id="btnChangePassword">修改密码</button>`
            }
            <span class="role-chip">${roleText}</span>
            <button type="button" class="theme-toggle" data-theme-toggle aria-label="切换主题" title="切换主题">
              <span class="icon-sun" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg></span>
              <span class="icon-moon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M21.752 15.002A9.72 9.72 0 0 1 18 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 0 0 3 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 0 0 9.002-5.998Z"/></svg></span>
            </button>
            <a class="btn btn-secondary btn-sm" href="/#/chat">智能对话</a>
            <button type="button" class="btn btn-text" id="btnLogout">退出</button>
          </div>
        </header>
        <main class="content" id="pageRoot"></main>
      </section>
    </div>`;

  const nextNav = document.querySelector(".app-shell-admin .sidebar-nav");
  if (nextNav) {
    const restore = () => {
      nextNav.scrollTop = sidebarNavScrollTop;
    };
    restore();
    requestAnimationFrame(restore);
    nextNav.addEventListener(
      "scroll",
      () => {
        sidebarNavScrollTop = nextNav.scrollTop;
      },
      { passive: true }
    );
  }

  document.querySelectorAll("[data-go]").forEach((el) => {
    el.addEventListener("click", () => navigate(el.getAttribute("data-go")));
  });
  document.querySelectorAll("[data-toggle-group]").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const groupId = btn.getAttribute("data-toggle-group");
      const groupEl = btn.closest(".sidebar-group");
      if (!groupId || !groupEl) return;
      const nextCollapsed = !groupEl.classList.contains("is-collapsed");
      groupEl.classList.toggle("is-collapsed", nextCollapsed);
      btn.setAttribute("aria-expanded", nextCollapsed ? "false" : "true");
      const map = readSidebarCollapsedMap();
      map[groupId] = nextCollapsed;
      writeSidebarCollapsedMap(map);
    });
  });
  document.getElementById("btnLogout").onclick = async () => {
    const ok = await confirmDialog({ title: "退出", message: "确定退出管理端吗？", confirmText: "退出" });
    if (!ok) return;
    clearAuth();
    location.href = "/#/";
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
  applyTheme(getTheme());
  return true;
}

/** 条形图渲染（支持轴标签） */
function renderBars(values, { percent = false, labels = null } = {}) {
  const nums = values.map(Number);
  const max = Math.max(...nums, 0.0001);
  const labs = Array.isArray(labels) && labels.length === nums.length ? labels : null;
  return `<div class="bar-chart ${labs ? "bar-chart-labeled" : ""}">${nums
    .map((v, i) => {
      const h = Math.max(4, Math.round((Number(v) / max) * 100));
      const label = percent ? `${Math.round(Number(v) * 100)}%` : String(v);
      const axis = labs ? `<em>${escapeHtml(String(labs[i]))}</em>` : "";
      return `<div class="bar" style="--bar-h:${h}%;--bar-i:${i}" title="${label}"><span>${label}</span>${axis}</div>`;
    })
    .join("")}</div>`;
}

/** 离开页面时清掉残留弹窗，避免挂在日志等页面下方造成错位点击 */
function closeAllModals() {
  document.querySelectorAll(".modal-mask, .modal-backdrop").forEach((el) => el.remove());
}

/** Materio 统一页头：说明文案 + 右侧操作（不再显示一级标题） */
function pageHead({ title, desc = "", actions = "" }) {
  const line = desc || title || "";
  return `<header class="page-head"${title ? ` aria-label="${escapeHtml(title)}"` : ""}>
    <div class="page-head-text">
      ${line ? `<p class="page-desc">${escapeHtml(line)}</p>` : ""}
    </div>
    ${actions ? `<div class="page-head-actions">${actions}</div>` : ""}
  </header>`;
}

/** 路由分发 */
function playPageEnter() {
  const root = document.getElementById("pageRoot");
  if (!root) return;
  root.classList.remove("page-enter");
  void root.offsetWidth;
  root.classList.add("page-enter");
}

async function dispatchRender() {
  closeAllModals();
  playPageEnter();
  const path = currentPath();
  // 知识库工作区（旧 /documents、/snapshots 归一化到 ?tab=）
  let m;
  if ((m = path.match(/^\/admin\/knowledge-bases\/([^/]+)\/documents$/))) return navigate(kbWorkspacePath(m[1], "docs"));
  if ((m = path.match(/^\/admin\/knowledge-bases\/([^/]+)\/snapshots$/))) return navigate(kbWorkspacePath(m[1], "snaps"));
  if ((m = path.match(/^\/admin\/knowledge-bases\/([^/]+)$/))) return pageKbWorkspace(m[1]);
  if (path === "/admin/users") return pageUsers();
  if (path === "/admin/roles") return pageRoles();
  if ((m = path.match(/^\/admin\/departments\/([^/]+)$/))) return pageDepartmentDetail(m[1]);
  if (path === "/admin/departments") return pageDepartments();
  if (path === "/admin/models") return pageModels();
  if (path === "/admin/knowledge-bases") return pageKbList();
  if (path === "/admin/ragas") return pageRagas();
  if (path === "/admin/qa-sessions") return pageQaSessions();
  if (path === "/admin/role-caches") return pageRoleCaches();
  if (path === "/admin/hit-test") return pageHitTest();
  if (path === "/admin/audit") return pageAudit();
  if (path === "/admin/guard") return pageGuardEvents();
  if (path === "/admin/monitor") return pageMonitor();
  if (path === "/admin/fastapi") return pageFastApi();
  return pageDashboard();
}

/* ========== 首页 /admin：精简欢迎区 + 指标 + 图表 + 快捷入口 ========== */
function renderDashboardWelcome() {
  const user = getUser() || {};
  const name = escapeHtml(user.nickname || user.username || "用户");
  const roleLabel = escapeHtml(getRoleLabel());
  const hour = new Date().getHours();
  let timeGreeting = "你好";
  if (hour < 6) timeGreeting = "夜深了";
  else if (hour < 12) timeGreeting = "早上好";
  else if (hour < 14) timeGreeting = "中午好";
  else if (hour < 18) timeGreeting = "下午好";
  else timeGreeting = "晚上好";

  let focus = "查看运行指标，处理知识库与问答运营。";
  if (isSuperAdmin()) focus = "可配置模型、权限与全库资产。";
  else if (hasPermission("user:read") || hasPermission("role:read")) focus = "可管理用户、知识库与系统运维。";

  return `
    <section class="dash-welcome">
      <div class="dash-welcome-main">
        <p class="dash-welcome-kicker">知识运营控制台</p>
        <h1>${timeGreeting}，${name} 👋</h1>
        <p>当前身份 <strong>${roleLabel}</strong> · ${focus}</p>
      </div>
      <div class="dash-welcome-actions">
        ${hasPermission("kb:read") ? `<button type="button" class="btn" data-go="/admin/knowledge-bases">知识库</button>` : ""}
        <a class="btn btn-secondary" href="/#/chat">去问答</a>
      </div>
    </section>`;
}

function renderDashboardShortcuts() {
  const items = [
    { path: "/admin/knowledge-bases", label: "知识库", perm: "kb:read", desc: "文档与向量" },
    { path: "/admin/users", label: "用户", perm: "user:read", desc: "账号与角色" },
    { path: "/admin/hit-test", label: "命中测试", perm: "test:read", desc: "检索评测" },
    { path: "/admin/qa-sessions", label: "会话分析", perm: "system:read", desc: "问答洞察" },
    { path: "/admin/monitor", label: "系统监控", perm: "system:read", desc: "Grafana" },
    { path: "/admin/audit", label: "审计日志", perm: "audit:read", desc: "操作追踪" },
  ].filter((i) => hasPermission(i.perm));

  if (!items.length) return "";
  return `
    <section class="dash-section">
      <div class="dash-section-head"><h2>快捷入口</h2></div>
      <div class="dash-shortcut-grid">
        ${items
          .map(
            (i) => `<button type="button" class="dash-shortcut" data-go="${i.path}">
              <strong>${i.label}</strong><span>${i.desc}</span>
            </button>`
          )
          .join("")}
      </div>
    </section>`;
}

function weekLabels(n) {
  const out = [];
  const now = new Date();
  for (let i = n - 1; i >= 0; i -= 1) {
    const d = new Date(now);
    d.setDate(now.getDate() - i);
    out.push(`${d.getMonth() + 1}/${d.getDate()}`);
  }
  return out;
}

/** 图表右上角时间范围下拉 */
function chartRangeSelect(id, options, selected) {
  const opts = options
    .map(
      ([value, label]) =>
        `<option value="${escapeHtml(String(value))}"${String(value) === String(selected) ? " selected" : ""}>${escapeHtml(label)}</option>`
    )
    .join("");
  return `<div class="chart-range"><select id="${escapeHtml(id)}" class="chart-range-select" aria-label="时间范围">${opts}</select></div>`;
}

function sliceDailyTrend(series, days) {
  const src = Array.isArray(series) && series.length ? series.map(Number) : [0];
  const n = Math.max(1, Math.min(Number(days) || 7, src.length));
  return src.slice(-n);
}

/** 将小时序列切成固定桶数（默认 4） */
function bucketHourlyErrors(hourly, hours, buckets = 4) {
  const src = Array.isArray(hourly) && hourly.length ? hourly.map(Number) : [];
  const h = Math.max(1, Number(hours) || 24);
  let slice = src.slice(-h);
  if (slice.length < h) slice = Array(h - slice.length).fill(0).concat(slice);
  const out = [];
  for (let i = 0; i < buckets; i += 1) {
    const a = Math.floor((i * h) / buckets);
    const b = Math.floor(((i + 1) * h) / buckets);
    out.push(slice.slice(a, b).reduce((sum, v) => sum + Number(v || 0), 0));
  }
  return out;
}

function errorRangeLabels(hours, buckets = 4) {
  const h = Math.max(1, Number(hours) || 24);
  const labels = [];
  for (let i = 0; i < buckets; i += 1) {
    const a = Math.round((i * h) / buckets);
    const b = Math.round(((i + 1) * h) / buckets);
    labels.push(`${a}-${b}h`);
  }
  return labels;
}

async function pageDashboard() {
  if (!requirePerm("system:read", "首页")) return;
  const welcome = renderDashboardWelcome();
  document.getElementById("pageRoot").innerHTML = `${welcome}<div class="loading">加载统计数据…</div>`;
  try {
    const s = await api.get("/monitor/stats");
    const qaFull = s.qa_trend_30d?.length ? s.qa_trend_30d : s.qa_trend_7d || [0, 0, 0, 0, 0, 0, 0];
    const hitFull = s.hit_rate_trend_30d?.length ? s.hit_rate_trend_30d : s.hit_rate_trend_7d || [0, 0, 0, 0, 0, 0, 0];
    const errHourly =
      s.error_hourly_48h?.length
        ? s.error_hourly_48h
        : (() => {
            const e24 = s.error_24h || [0, 0, 0, 0];
            // 兼容旧接口：每段 6 小时拆成 6 个小时点
            return e24.flatMap((v) => {
              const n = Number(v) || 0;
              const base = Math.floor(n / 6);
              const rem = n % 6;
              return Array.from({ length: 6 }, (_, i) => base + (i < rem ? 1 : 0));
            });
          })();

    const dayOpts = [
      [3, "近 3 天"],
      [7, "近 7 天"],
      [14, "近 14 天"],
      [30, "近 30 天"],
    ];
    const errOpts = [
      [6, "近 6 小时"],
      [12, "近 12 小时"],
      [24, "近 24 小时"],
      [48, "近 48 小时"],
    ];
    let qaDays = 7;
    let hitDays = 7;
    let errHours = 24;

    const paintQa = () => {
      const values = sliceDailyTrend(qaFull, qaDays);
      const title = document.getElementById("dashQaTitle");
      const body = document.getElementById("dashQaChart");
      if (title) title.textContent = `近 ${qaDays} 天问答量`;
      if (body) body.innerHTML = renderBars(values, { labels: weekLabels(values.length) });
    };
    const paintHit = () => {
      const values = sliceDailyTrend(hitFull, hitDays);
      const title = document.getElementById("dashHitTitle");
      const body = document.getElementById("dashHitChart");
      if (title) title.textContent = `近 ${hitDays} 天命中率`;
      if (body) body.innerHTML = renderBars(values, { percent: true, labels: weekLabels(values.length) });
    };
    const paintErr = () => {
      const values = bucketHourlyErrors(errHourly, errHours, 4);
      const title = document.getElementById("dashErrTitle");
      const body = document.getElementById("dashErrChart");
      if (title) title.textContent = `近 ${errHours} 小时错误`;
      if (body) body.innerHTML = renderBars(values, { labels: errorRangeLabels(errHours, 4) });
    };

    document.getElementById("pageRoot").innerHTML = `
      ${welcome}
      <section class="dash-section">
        <div class="dash-section-head"><h2>核心指标</h2><span class="text-muted">实时汇总</span></div>
        <div class="stat-grid dash-stat-grid">
          <div class="stat-card"><div class="label">知识库</div><div class="value" data-count-up="${s.kb_count ?? 0}">0</div></div>
          <div class="stat-card"><div class="label">文档</div><div class="value" data-count-up="${s.doc_count ?? 0}">0</div></div>
          <div class="stat-card"><div class="label">用户</div><div class="value" data-count-up="${s.user_count ?? 0}">0</div></div>
          <div class="stat-card"><div class="label">活跃会话</div><div class="value" data-count-up="${s.active_sessions ?? 0}">0</div></div>
        </div>
      </section>
      <section class="dash-section page-grid dash-bento">
        <div class="card dash-chart-card span-8">
          <div class="card-header">
            <div class="card-header-text"><h3 class="card-title" id="dashQaTitle">近 7 天问答量</h3></div>
            <div class="card-header-actions">${chartRangeSelect("dashQaRange", dayOpts, qaDays)}</div>
          </div>
          <div id="dashQaChart" class="dash-chart-body"></div>
        </div>
        <div class="card dash-chart-card dash-security-card span-4">
          <div class="card-header"><div class="card-header-text"><h3 class="card-title">安全窗口</h3></div></div>
          <div class="dash-security-body">
            <div class="dash-security-metrics">
              <div><span class="label">近 24h 阻拦</span><strong data-count-up="${s.guard_blocked_24h ?? 0}">0</strong></div>
              <div><span class="label">近 7 天阻拦</span><strong data-count-up="${s.guard_blocked_7d ?? 0}">0</strong></div>
            </div>
            <p class="text-muted dash-security-note">涵盖提示注入、窃密、越权与危险命令。</p>
          </div>
          <div class="dash-security-actions">
            <button type="button" class="btn btn-secondary btn-sm" data-go="/admin/guard">拦截详情</button>
          </div>
        </div>
        <div class="card dash-chart-card span-4">
          <div class="card-header">
            <div class="card-header-text"><h3 class="card-title" id="dashHitTitle">近 7 天命中率</h3></div>
            <div class="card-header-actions">${chartRangeSelect("dashHitRange", dayOpts, hitDays)}</div>
          </div>
          <div id="dashHitChart" class="dash-chart-body"></div>
        </div>
        <div class="card dash-chart-card span-8">
          <div class="card-header">
            <div class="card-header-text"><h3 class="card-title" id="dashErrTitle">近 24 小时错误</h3></div>
            <div class="card-header-actions">${chartRangeSelect("dashErrRange", errOpts, errHours)}</div>
          </div>
          <div id="dashErrChart" class="dash-chart-body"></div>
        </div>
      </section>
      ${renderDashboardShortcuts()}`;

    paintQa();
    paintHit();
    paintErr();

    document.getElementById("dashQaRange")?.addEventListener("change", (e) => {
      qaDays = Number(e.target.value) || 7;
      paintQa();
    });
    document.getElementById("dashHitRange")?.addEventListener("change", (e) => {
      hitDays = Number(e.target.value) || 7;
      paintHit();
    });
    document.getElementById("dashErrRange")?.addEventListener("change", (e) => {
      errHours = Number(e.target.value) || 24;
      paintErr();
    });

    document.querySelectorAll("#pageRoot [data-go]").forEach((el) => {
      el.addEventListener("click", () => navigate(el.getAttribute("data-go")));
    });
    runCountUps(document.getElementById("pageRoot"));
  } catch (e) {
    document.getElementById("pageRoot").innerHTML = `${welcome}<div class="card text-danger">${escapeHtml(e.message)}</div>`;
    document.querySelectorAll("#pageRoot [data-go]").forEach((el) => {
      el.addEventListener("click", () => navigate(el.getAttribute("data-go")));
    });
  }
}

/* ========== 用户管理 ========== */
function roleLabelOf(u) {
  if (Array.isArray(u.role_labels) && u.role_labels.length) return u.role_labels.join("、");
  const names = (u.roles || [u.role]).filter(Boolean);
  const map = { super_admin: "超级管理员", admin: "管理员", staff: "员工", guest: "访客" };
  return names.map((n) => map[n] || n).join("、") || "-";
}

/** 角色等级：越高权限越大。仅可分配/删除低于自己等级的用户。 */
function roleRankOfName(name) {
  const map = { super_admin: 100, admin: 50, staff: 20, kb_admin: 20, guest: 10, user: 10 };
  return map[name] || 5;
}

function maxRoleRankOfUser(u) {
  const names = (u?.roles || []).filter(Boolean);
  if (!names.length) return 0;
  return Math.max(...names.map(roleRankOfName));
}

function openUserRolePicker({ user, roles, departments = [], onSave }) {
  closeAllModals();
  const dialogId = `userRole-${Date.now()}`;
  const current = new Set(user.roles || []);
  const iAmSuper = isSuperAdmin();
  // 全系统禁止分配/撤销超管；角色列表永不出现 super_admin
  const options = (roles || [])
    .filter((r) => {
      if (r.name === "user" || r.name === "kb_admin" || r.name === "super_admin") return false;
      if (iAmSuper) return true;
      return r.name !== "admin";
    })
    .map(
      (r) => `<label><input type="radio" name="role_id" value="${escapeHtml(r.id)}" ${current.has(r.name) ? "checked" : ""}>
        ${escapeHtml(r.display_name || r.name)} <small>${escapeHtml(r.name)}</small></label>`
    )
    .join("");
  document.body.insertAdjacentHTML(
    "beforeend",
    `<div id="${dialogId}" class="modal-backdrop" style="display:flex">
      <form class="modal" style="max-width:520px;width:92%">
        <div class="modal-header"><h3>变更「${escapeHtml(user.username)}」角色</h3></div>
        <div class="modal-body">
          <p class="text-muted">系统仅支持唯一超管账号 super，界面不可增设或撤销超管。${iAmSuper ? "可将用户设为管理员/员工/访客。" : "管理员不可将他人设为管理员，也不可改超管账号。"}</p>
          <div class="checkbox-grid">${options || "<span class='text-muted'>无可分配角色</span>"}</div>
          <label class="form-label" style="margin-top:12px">所属部门（员工上传隔离用）</label>
          <select class="form-control" name="department">
            ${departmentSelectHtml(departments, user.department, { emptyLabel: "不限 / 管理员" })}
          </select>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" data-close>取消</button>
          <button class="btn btn-primary" type="submit">保存</button>
        </div>
      </form>
    </div>`
  );
  const root = document.getElementById(dialogId);
  root.querySelector("[data-close]").onclick = () => root.remove();
  root.querySelector("form").onsubmit = async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const roleId = String(form.get("role_id") || "").trim();
    if (!roleId) return toast("请选择角色", "error");
    try {
      await onSave({ role_ids: [roleId], department: String(form.get("department") || "") });
      root.remove();
    } catch (error) {
      toast(error.message || "保存失败", "error");
    }
  };
}

async function openCreateUserForm() {
  closeAllModals();
  let roles = [];
  let departments = [];
  try {
    const [roleData, deptData] = await Promise.all([
      api.get("/roles?page=1&page_size=100"),
      loadDepartmentOptions(),
    ]);
    roles = (roleData.items || []).filter((r) => {
      if (r.name === "user" || r.name === "kb_admin" || r.name === "super_admin") return false;
      if (isSuperAdmin()) return true;
      return r.name !== "admin";
    });
    departments = deptData;
  } catch (e) {
    toast(e.message || "加载角色/部门失败", "error");
    return;
  }

  const roleOptions = roles
    .map((r) => `<option value="${escapeHtml(r.id)}">${escapeHtml(r.display_name || r.name)}（${escapeHtml(r.name)}）</option>`)
    .join("");

  const mask = document.createElement("div");
  mask.className = "modal-mask";
  mask.innerHTML = `
    <form class="modal" style="width:min(520px,calc(100vw - 24px));max-height:90vh;overflow:auto">
      <div class="modal-header"><h3>新增用户</h3></div>
      <div class="modal-body">
        <label class="form-label">账号 <span style="color:var(--color-danger)">*</span></label>
        <input class="form-control" name="username" required minlength="3" maxlength="50" placeholder="3-50 位" />
        <label class="form-label" style="margin-top:10px">邮箱 <span style="color:var(--color-danger)">*</span></label>
        <input class="form-control" name="email" type="email" required placeholder="user@example.com" />
        <label class="form-label" style="margin-top:10px">初始密码 <span style="color:var(--color-danger)">*</span></label>
        <input class="form-control" name="password" type="text" required minlength="8" maxlength="128" placeholder="至少 8 位" />
        <label class="form-label" style="margin-top:10px">昵称</label>
        <input class="form-control" name="nickname" maxlength="100" placeholder="可留空，默认同账号" />
        <label class="form-label" style="margin-top:10px">角色</label>
        <select class="form-control" name="role_id">
          <option value="">默认（访客）</option>
          ${roleOptions}
        </select>
        <label class="form-label" style="margin-top:10px">所属部门</label>
        <select class="form-control" name="department">
          ${departmentSelectHtml(departments, "", { emptyLabel: "不限 / 管理员" })}
        </select>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-secondary" data-close>取消</button>
        <button type="submit" class="btn btn-primary">创建</button>
      </div>
    </form>`;
  document.body.appendChild(mask);
  mask.querySelector("[data-close]").onclick = () => mask.remove();
  mask.addEventListener("click", (e) => {
    if (e.target === mask) mask.remove();
  });
  mask.querySelector("form").onsubmit = async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.currentTarget);
    const username = String(fd.get("username") || "").trim();
    const email = String(fd.get("email") || "").trim();
    const password = String(fd.get("password") || "");
    const nickname = String(fd.get("nickname") || "").trim() || username;
    const roleId = String(fd.get("role_id") || "").trim();
    const department = String(fd.get("department") || "").trim().toUpperCase();
    if (!username || !email || !password) {
      toast("请填写账号、邮箱与密码", "error");
      return;
    }
    if (password.length < 8) {
      toast("密码至少 8 位", "error");
      return;
    }
    const submitBtn = ev.currentTarget.querySelector('button[type="submit"]');
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = "创建中…";
    }
    try {
      const payload = { username, email, password, nickname };
      if (roleId) payload.role_ids = [roleId];
      const created = await api.post("/users", payload);
      if (department && created?.id) {
        await api.put(`/users/${created.id}`, { department });
      }
      toast("用户创建成功", "success");
      mask.remove();
      pageUsers();
    } catch (e) {
      toast(e.message || "用户创建失败", "error");
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = "创建";
      }
    }
  };
}

async function pageUsers() {
  if (!requirePerm("user:read", "用户管理")) return;
  const canWrite = hasPermission("user:write");
  const focusUserId = new URLSearchParams(location.hash.split("?")[1] || "").get("user");
  document.getElementById("pageRoot").innerHTML = `<div class="loading">加载用户…</div>`;
  try {
    const data = await api.get("/users?page=1&page_size=50");
    const items = data.items || [];
    document.getElementById("pageRoot").innerHTML = `
      ${pageHead({
        title: "用户管理",
        desc: canWrite ? "可新增用户、启用/禁用、变更角色、删除权限更低的用户。" : "当前为只读，可查看用户列表。",
        actions: canWrite ? `<button class="btn btn-sm" id="btnNewUser">新增用户</button>` : "",
      })}
      <div class="card panel-fill users-panel">
        <div class="card-header">
          <div class="card-header-text">
            <h3 class="card-title">用户列表</h3>
            <p class="card-sub">共 ${items.length} 人</p>
          </div>
        </div>
        <div class="table-wrap"><table class="table table-users">
          <thead><tr>
            <th class="col-time">创建时间</th>
            <th class="col-name">账号</th>
            <th>用户名</th>
            <th class="col-status">状态</th>
            <th>角色</th>
            <th>所属部门</th>
            <th class="col-time">最近登录</th>
            <th class="col-actions">操作</th>
          </tr></thead>
          <tbody>
            ${items
              .map((u) => {
                const isFixedSuper = String(u.username || "") === "super";
                const st = u.status === "active" ? `<span class="badge badge-success">活跃</span>` : u.status === "disabled" ? `<span class="badge badge-danger">禁用</span>` : `<span class="badge badge-warning">待验证</span>`;
                const myRank = isSuperAdmin() ? 100 : isAdminUser() ? 50 : 0;
                const targetRank = isFixedSuper ? 100 : maxRoleRankOfUser(u);
                const canManage = canWrite && !isFixedSuper && targetRank < myRank;
                const roleCell = isFixedSuper
                  ? `<span class="badge badge-gold">超级管理员</span>`
                  : escapeHtml(roleLabelOf(u));
                const ops = canWrite
                  ? isFixedSuper
                    ? `<span class="cell-muted cell-muted-stack">固定超管<br />（不可操作）</span>`
                    : canManage
                      ? `<div class="table-actions table-actions-stack">
                    <div class="table-actions-row">
                      <button type="button" class="btn btn-secondary btn-sm" data-role="${escapeHtml(u.id)}">角色</button>
                    </div>
                    <div class="table-actions-row">
                      <button type="button" class="btn ${u.status === "disabled" ? "btn-success" : "btn-danger"} btn-sm" data-toggle="${escapeHtml(u.id)}" data-status="${escapeHtml(u.status)}">${u.status === "disabled" ? "启用" : "禁用"}</button>
                      <button type="button" class="btn btn-danger btn-sm" data-del-user="${escapeHtml(u.id)}">删除</button>
                    </div>
                  </div>`
                      : `<span class="cell-muted">权限不足</span>`
                  : `<span class="cell-muted">—</span>`;
                const focused = focusUserId && String(u.id) === String(focusUserId);
                return `<tr data-id="${escapeHtml(u.id)}" class="${focused ? "row-focus" : ""}" ${focused ? 'style="outline:2px solid var(--color-primary, #5b8def);outline-offset:-2px"' : ""}>
                  <td class="col-time">${formatDateTimeHtml(u.created_at)}</td>
                  <td class="col-name"><strong class="cell-primary">${escapeHtml(u.username)}</strong></td>
                  <td>${escapeHtml(u.nickname || "-")}</td>
                  <td class="col-status">${st}</td>
                  <td class="cell-role">${roleCell}</td>
                  <td>${escapeHtml(u.department || "-")}</td>
                  <td class="col-time">${formatDateTimeHtml(u.last_login_at)}</td>
                  <td class="col-actions">${ops}</td>
                </tr>`;
              })
              .join("")}
          </tbody>
        </table></div>
      </div>`;

    if (focusUserId) {
      const row = [...document.querySelectorAll("tr[data-id]")].find(
        (el) => el.getAttribute("data-id") === String(focusUserId)
      );
      if (row) row.scrollIntoView({ behavior: "smooth", block: "center" });
    }

    if (!canWrite) return;

    document.querySelectorAll("[data-toggle]").forEach((btn) => {
      btn.onclick = async () => {
        const id = btn.getAttribute("data-toggle");
        const cur = btn.getAttribute("data-status");
        const next = cur === "disabled" ? "active" : "disabled";
        const ok = await confirmDialog({
          title: next === "disabled" ? "禁用用户" : "启用用户",
          message: next === "disabled" ? "禁用后该用户将无法登录，确定继续？" : "确定启用该用户？",
          confirmText: "确认",
          danger: next === "disabled",
        });
        if (!ok) return;
        try {
          await api.patch(`/users/${id}/status`, { status: next });
          toast("状态已更新", "success");
          pageUsers();
        } catch (e) {
          toast(e.message || "操作失败", "error");
        }
      };
    });

    document.querySelectorAll("[data-role]").forEach((btn) => {
      btn.onclick = async () => {
        const id = btn.getAttribute("data-role");
        const user = items.find((x) => x.id === id);
        if (!user) return;
        if (String(user.username || "") === "super") {
          toast("唯一超管账号 super 不可变更角色", "error");
          return;
        }
        if (user.is_super_admin && !isSuperAdmin()) {
          toast("无权变更超级管理员", "error");
          return;
        }
        const myRank = isSuperAdmin() ? 100 : isAdminUser() ? 50 : 0;
        if (maxRoleRankOfUser(user) >= myRank) {
          toast("只能变更权限低于自己的用户", "error");
          return;
        }
        try {
          const [roleData, departments] = await Promise.all([
            api.get("/roles?page=1&page_size=100"),
            loadDepartmentOptions(),
          ]);
          openUserRolePicker({
            user,
            roles: roleData.items || [],
            departments,
            onSave: async ({ role_ids, department }) => {
              await api.put(`/users/${id}/roles`, { role_ids });
              await api.put(`/users/${id}`, { department });
              toast("用户角色与部门已更新", "success");
              pageUsers();
            },
          });
        } catch (e) {
          toast(e.message || "角色更新失败", "error");
        }
      };
    });

    document.querySelectorAll("[data-del-user]").forEach((btn) => {
      btn.onclick = async () => {
        const id = btn.getAttribute("data-del-user");
        const user = items.find((x) => x.id === id);
        if (!user) return;
        if (String(user.username || "") === "super") {
          toast("唯一超管账号 super 不可删除", "error");
          return;
        }
        const ok = await confirmDialog({
          title: "删除用户",
          message: `确定删除用户「${user.username}」？此操作不可恢复。`,
          confirmText: "删除",
          danger: true,
        });
        if (!ok) return;
        try {
          await api.delete(`/users/${id}`);
          toast("用户已删除", "success");
          pageUsers();
        } catch (e) {
          toast(e.message || "删除失败", "error");
        }
      };
    });

    const btnNewUser = document.getElementById("btnNewUser");
    if (btnNewUser) btnNewUser.onclick = () => openCreateUserForm();
  } catch (e) {
    document.getElementById("pageRoot").innerHTML = `<div class="card text-danger">${escapeHtml(e.message)}</div>`;
  }
}

/* ========== 角色管理 ========== */
async function fetchPermissionCatalog() {
  const raw = await api.get("/roles/permissions");
  if (Array.isArray(raw)) return raw;
  if (Array.isArray(raw?.items)) return raw.items;
  return [];
}

function openRolePermissionForm({ title, role = null, permissionData, onSave }) {
  closeAllModals();
  const dialogId = `roleForm-${Date.now()}`;
  const selected = new Set(role?.permissions || []);
  const perms = Array.isArray(permissionData) ? permissionData : [];
  document.body.insertAdjacentHTML(
    "beforeend",
    `<div id="${dialogId}" class="modal-backdrop" style="display:flex">
      <form class="modal" style="max-width:680px;width:92%">
        <div class="modal-header"><h3>${escapeHtml(title)}</h3></div>
        <div class="modal-body">
          <label class="form-label">角色标识（英文/下划线，创建后不可改）</label>
          <input class="form-control" name="name" value="${escapeHtml(role?.name || "")}" ${role ? "readonly" : "required"} placeholder="例如 dept_a_staff" />
          <label class="form-label" style="margin-top:12px">角色说明</label>
          <input class="form-control" name="description" value="${escapeHtml(role?.description || "")}" placeholder="中文说明" />
          <p class="text-muted" style="margin-top:14px">功能权限（显示为中文名；可不勾选）</p>
          <div class="checkbox-grid">${
            perms.length
              ? perms
                  .map(
                    (item) =>
                      `<label><input type="checkbox" name="permission" value="${escapeHtml(item.code)}" ${selected.has(item.code) ? "checked" : ""}>
                        ${escapeHtml(item.name || item.code)} <small>${escapeHtml(item.code)}</small></label>`
                  )
                  .join("")
              : `<span class="text-muted">暂无权限清单</span>`
          }</div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" data-close>取消</button>
          <button class="btn btn-primary" type="submit">保存</button>
        </div>
      </form>
    </div>`
  );
  const root = document.getElementById(dialogId);
  root.querySelector("[data-close]").onclick = () => root.remove();
  root.onclick = (e) => {
    if (e.target === root) root.remove();
  };
  root.querySelector("form").onsubmit = async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const name = String(form.get("name") || "").trim();
    if (!name || name.length < 2) return toast("角色标识至少 2 个字符", "error");
    try {
      await onSave({
        name,
        description: String(form.get("description") || "").trim(),
        permission_codes: form.getAll("permission").map(String),
      });
      root.remove();
      pageRoles();
    } catch (error) {
      toast(error.message || "保存失败", "error");
    }
  };
}

async function pageRoles() {
  if (!requirePerm("role:read", "角色管理")) return;
  const canWrite = hasPermission("role:write");
  document.getElementById("pageRoot").innerHTML = `<div class="loading">加载角色…</div>`;
  try {
    const data = await api.get("/roles?page=1&page_size=50");
    const items = data.items || [];
    document.getElementById("pageRoot").innerHTML = `
      ${pageHead({
        title: "角色管理",
        desc: "内置：超级管理员 / 管理员 / 员工 / 访客。仅超级管理员可配置角色权限。",
        actions: canWrite ? `<button class="btn btn-sm" id="btnNewRole">新建角色</button>` : "",
      })}
      <div class="card panel-fill">
        <div class="card-header">
          <div class="card-header-text">
            <h3 class="card-title">角色列表</h3>
            <p class="card-sub">共 ${items.filter((r) => r.name !== "user" && r.name !== "kb_admin").length} 个角色</p>
          </div>
        </div>
        <div class="table-wrap"><table class="table table-roles">
          <colgroup>
            <col class="roles-col-name" />
            <col class="roles-col-code" />
            <col class="roles-col-desc" />
            <col class="roles-col-builtin" />
            <col class="roles-col-num" />
            <col class="roles-col-actions" />
          </colgroup>
          <thead><tr>
            <th class="col-name">身份角色</th>
            <th class="col-code">标识</th>
            <th class="col-desc">说明</th>
            <th class="col-builtin">内置</th>
            <th class="col-num">权限数</th>
            <th class="col-actions">操作</th>
          </tr></thead>
          <tbody>
            ${items
              .filter((r) => r.name !== "user" && r.name !== "kb_admin")
              .map((r) => {
                const isSuperRole = r.name === "super_admin";
                const canEditThis = canWrite && (isSuperAdmin() || !isSuperRole);
                const canConfigPerms = isSuperAdmin() && canEditThis;
                const desc = r.description || "";
                return `<tr>
                  <td class="col-name"><strong>${escapeHtml(r.display_name || r.name)}</strong></td>
                  <td class="col-code"><code>${escapeHtml(r.name)}</code></td>
                  <td class="col-desc">${escapeHtml(desc || "—")}</td>
                  <td class="col-builtin">${r.is_builtin ? `<span class="badge badge-info">内置</span>` : "-"}</td>
                  <td class="col-num">${(r.permissions || []).length}</td>
                  <td class="col-actions">
                    <div class="table-actions">
                      <button class="btn btn-secondary btn-sm" data-view="${escapeHtml(r.id)}">查看权限</button>
                      ${canEditThis ? `<button class="btn btn-secondary btn-sm" data-edit-meta="${escapeHtml(r.id)}">编辑说明</button>` : ""}
                      ${canConfigPerms ? `<button class="btn btn-secondary btn-sm" data-edit-perms="${escapeHtml(r.id)}">配置权限</button>` : ""}
                      ${!r.is_builtin && canEditThis ? `<button class="btn btn-danger btn-sm" data-del="${escapeHtml(r.id)}">删除</button>` : ""}
                    </div>
                  </td>
                </tr>`;
              })
              .join("")}
          </tbody>
        </table></div>
      </div>`;

    const btnNew = document.getElementById("btnNewRole");
    if (btnNew) {
      btnNew.onclick = async () => {
        try {
          const permissionData = await fetchPermissionCatalog();
          openRolePermissionForm({
            title: "新建角色",
            permissionData,
            onSave: async (payload) => {
              await api.post("/roles", payload);
              toast("角色创建成功", "success");
            },
          });
        } catch (e) {
          toast(e.message || "无法加载权限清单", "error");
        }
      };
    }

    document.querySelectorAll("[data-view]").forEach((btn) => {
      btn.onclick = async () => {
        const r = items.find((x) => x.id === btn.getAttribute("data-view"));
        if (!r) return;
        try {
          const catalog = await fetchPermissionCatalog();
          const byCode = Object.fromEntries(catalog.map((p) => [p.code, p.name]));
          const lines = (r.permissions || []).map((c) => `${byCode[c] || c}（${c}）`);
          await openWideModal({
            title: `${r.display_name || r.name} · 权限`,
            bodyHtml: `<pre style="white-space:pre-wrap;font-size:13px;margin:0">${escapeHtml(lines.join("\n") || "无权限")}</pre>`,
            actionsHtml: `<button type="button" class="btn btn-secondary" data-act="cancel">关闭</button>`,
          });
        } catch {
          alert((r.permissions || []).join("\n") || "无");
        }
      };
    });

    document.querySelectorAll("[data-edit-meta]").forEach((btn) => {
      btn.onclick = async () => {
        const role = items.find((item) => item.id === btn.getAttribute("data-edit-meta"));
        if (!role) return;
        const result = await openWideModal({
          title: `编辑角色 · ${role.display_name || role.name}`,
          bodyHtml: `
            <label class="text-muted">角色标识</label>
            <input class="form-control" id="roleMetaName" value="${escapeHtml(role.name)}" ${role.is_builtin ? "readonly" : ""} style="margin:6px 0 12px" />
            <label class="text-muted">说明</label>
            <textarea class="form-control" id="roleMetaDesc" rows="3" style="margin:6px 0">${escapeHtml(role.description || "")}</textarea>
            <label style="display:flex;gap:8px;align-items:center;margin-top:8px"><input type="checkbox" id="roleMetaEnabled" ${role.is_enabled !== false ? "checked" : ""} /> 启用</label>`,
          actionsHtml: `<button type="button" class="btn btn-secondary" data-act="cancel">取消</button>
            <button type="button" class="btn" data-act="ok">保存</button>`,
        });
        if (!result) return;
        const name = result.root.querySelector("#roleMetaName")?.value?.trim();
        const description = result.root.querySelector("#roleMetaDesc")?.value?.trim() || null;
        const is_enabled = Boolean(result.root.querySelector("#roleMetaEnabled")?.checked);
        result.root.remove();
        if (!name || name.length < 2) return toast("角色标识至少 2 字符", "error");
        try {
          await api.put(`/roles/${role.id}`, { name, description, is_enabled, permission_codes: role.permissions || [] });
          toast("角色已更新", "success");
          pageRoles();
        } catch (e) {
          toast(e.message || "更新失败", "error");
        }
      };
    });

    document.querySelectorAll("[data-edit-perms]").forEach((btn) => {
      btn.onclick = async () => {
        if (!isSuperAdmin()) {
          toast("仅超级管理员可配置角色权限", "error");
          return;
        }
        const role = items.find((item) => item.id === btn.getAttribute("data-edit-perms"));
        if (!role) return;
        try {
          const permissionData = await fetchPermissionCatalog();
          openRolePermissionForm({
            title: `配置「${role.display_name || role.name}」权限`,
            role,
            permissionData,
            onSave: async (payload) => {
              await api.put(`/roles/${role.id}/permissions`, { permission_codes: payload.permission_codes });
              toast("角色权限已更新", "success");
            },
          });
        } catch (e) {
          toast(e.message || "无法打开权限配置", "error");
        }
      };
    });

    document.querySelectorAll("[data-del]").forEach((btn) => {
      btn.onclick = async () => {
        const ok = await confirmDialog({ title: "删除角色", message: "确定删除该角色？", confirmText: "删除" });
        if (!ok) return;
        try {
          await api.delete(`/roles/${btn.getAttribute("data-del")}`);
          toast("已删除", "success");
          pageRoles();
        } catch (e) {
          toast(e.message || "删除失败", "error");
        }
      };
    });
  } catch (e) {
    document.getElementById("pageRoot").innerHTML = `<div class="card text-danger">${escapeHtml(e.message)}</div>`;
  }
}

/* ========== 部门管理 ========== */
async function loadDepartmentOptions() {
  try {
    const data = await api.get("/departments?page=1&page_size=100");
    return data.items || [];
  } catch {
    return [];
  }
}

/** 访问范围（部门驱动）标签：GUEST=访客专用；其余=部门；空=私有 */
function accessScopeBadge(k) {
  const dept = String(k.department || "").toUpperCase();
  if (dept === "GUEST") return `<span class="badge badge-success">访客专用</span>`;
  if (dept) return `<span class="badge">${escapeHtml(k.department)} 部门</span>`;
  return `<span class="badge">私有</span>`;
}

/** 知识库类型中文 */
function kbTypeLabel(type) {
  return (
    { general: "通用知识", technical: "技术文档", product: "产品手册", faq: "FAQ" }[String(type || "").toLowerCase()] ||
    type ||
    "通用知识"
  );
}

function kbTypeBadge(type) {
  return `<span class="badge badge-info">${escapeHtml(kbTypeLabel(type))}</span>`;
}

function departmentSelectHtml(departments, selectedCode, { emptyLabel = "不限 / 未分配" } = {}) {
  const cur = String(selectedCode || "").toUpperCase();
  const opts = (departments || [])
    .filter((d) => d.is_enabled !== false)
    .map(
      (d) =>
        `<option value="${escapeHtml(d.code)}" ${String(d.code).toUpperCase() === cur ? "selected" : ""}>${escapeHtml(d.name)}（${escapeHtml(d.code)}）</option>`
    )
    .join("");
  return `<option value="">${escapeHtml(emptyLabel)}</option>${opts}`;
}

function openDepartmentForm({ title, dept = null, onSave }) {
  closeAllModals();
  const mask = document.createElement("div");
  mask.className = "modal-mask";
  mask.innerHTML = `
    <form class="modal" style="width:min(520px,calc(100vw - 24px))">
      <div class="modal-header"><h3>${escapeHtml(title)}</h3></div>
      <div class="modal-body">
        <label class="form-label">部门编码</label>
        <input class="form-control" name="code" required maxlength="50" value="${escapeHtml(dept?.code || "")}" placeholder="如 A / B / HR" ${dept ? "" : ""} />
        <label class="form-label" style="margin-top:10px">部门名称</label>
        <input class="form-control" name="name" required maxlength="100" value="${escapeHtml(dept?.name || "")}" placeholder="如 研发部" />
        <label class="form-label" style="margin-top:10px">部门介绍</label>
        <textarea class="form-control" name="description" rows="4" placeholder="可选，介绍部门职责与范围">${escapeHtml(dept?.description || "")}</textarea>
        <label class="form-label" style="margin-top:10px;display:flex;align-items:center;gap:8px">
          <input type="checkbox" name="is_enabled" ${dept?.is_enabled === false ? "" : "checked"} /> 启用
        </label>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-secondary" data-close>取消</button>
        <button type="submit" class="btn btn-primary">保存</button>
      </div>
    </form>`;
  document.body.appendChild(mask);
  mask.querySelector("[data-close]").onclick = () => mask.remove();
  mask.addEventListener("click", (e) => {
    if (e.target === mask) mask.remove();
  });
  mask.querySelector("form").onsubmit = async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.currentTarget);
    const payload = {
      code: String(fd.get("code") || "").trim(),
      name: String(fd.get("name") || "").trim(),
      description: String(fd.get("description") || "").trim() || null,
      is_enabled: !!fd.get("is_enabled"),
    };
    if (!payload.code || !payload.name) {
      toast("请填写编码与名称", "error");
      return;
    }
    try {
      await onSave(payload);
      mask.remove();
      if (dept?.id) pageDepartmentDetail(String(dept.id));
      else pageDepartments();
    } catch (e) {
      toast(e.message || "保存失败", "error");
    }
  };
}

async function pageDepartments() {
  if (!requirePerm("department:read", "部门管理")) return;
  const canWrite = hasPermission("department:write");
  document.getElementById("pageRoot").innerHTML = `<div class="loading">加载部门…</div>`;
  try {
    const data = await api.get("/departments?page=1&page_size=100");
    const items = data.items || [];
    document.getElementById("pageRoot").innerHTML = `
      ${pageHead({
        title: "部门管理",
        desc: "维护部门介绍、成员与关联知识库；部门编码用于上传与访问隔离。",
        actions: canWrite ? `<button type="button" class="btn btn-sm" id="btnNewDept">新建部门</button>` : "",
      })}
      <div class="card panel-fill">
        <div class="card-header">
          <div class="card-header-text">
            <h3 class="card-title">部门列表</h3>
            <p class="card-sub">共 ${items.length} 个部门</p>
          </div>
        </div>
        <div class="table-wrap"><table class="table">
          <thead><tr><th class="col-name">名称</th><th class="col-code">编码</th><th class="col-desc">介绍</th><th>成员</th><th>知识库</th><th>状态</th><th class="col-actions">操作</th></tr></thead>
          <tbody>
            ${
              items.length
                ? items
                    .map(
                      (d) => `<tr>
                        <td class="col-name"><strong>${escapeHtml(d.name)}</strong></td>
                        <td class="col-code"><code>${escapeHtml(d.code)}</code></td>
                        <td class="col-desc" title="${escapeHtml(d.description || "")}"><span class="cell-clamp">${escapeHtml(d.description || "-")}</span></td>
                        <td>${escapeHtml(d.member_count ?? 0)}</td>
                        <td>${escapeHtml(d.kb_count ?? 0)}</td>
                        <td>${d.is_enabled ? `<span class="badge badge-success">启用</span>` : `<span class="badge badge-danger">停用</span>`}</td>
                        <td class="col-actions">
                          <div class="table-actions table-actions-stack">
                            <div class="table-actions-row">
                              <button type="button" class="btn btn-secondary btn-sm" data-go="/admin/departments/${escapeHtml(d.id)}">管理</button>
                              ${canWrite ? `<button type="button" class="btn btn-secondary btn-sm" data-edit="${escapeHtml(d.id)}">编辑</button>` : ""}
                            </div>
                            ${
                              canWrite && String(d.code).toUpperCase() !== "GUEST"
                                ? `<div class="table-actions-row">
                              <button type="button" class="btn btn-danger btn-sm" data-del="${escapeHtml(d.id)}">删除</button>
                            </div>`
                                : ""
                            }
                          </div>
                        </td>
                      </tr>`
                    )
                    .join("")
                : `<tr><td colspan="7" class="text-muted">暂无部门</td></tr>`
            }
          </tbody>
        </table></div>
      </div>`;

    document.querySelectorAll("[data-go]").forEach((btn) => {
      btn.onclick = () => navigate(btn.getAttribute("data-go"));
    });

    const btnNew = document.getElementById("btnNewDept");
    if (btnNew) {
      btnNew.onclick = () =>
        openDepartmentForm({
          title: "新建部门",
          onSave: async (payload) => {
            await api.post("/departments", payload);
            toast("部门已创建", "success");
          },
        });
    }

    document.querySelectorAll("[data-edit]").forEach((btn) => {
      btn.onclick = () => {
        const d = items.find((x) => String(x.id) === btn.getAttribute("data-edit"));
        if (!d) return;
        openDepartmentForm({
          title: `编辑「${d.name}」`,
          dept: d,
          onSave: async (payload) => {
            await api.put(`/departments/${d.id}`, payload);
            toast("部门已更新", "success");
          },
        });
      };
    });

    document.querySelectorAll("[data-del]").forEach((btn) => {
      btn.onclick = async () => {
        const ok = await confirmDialog({
          title: "删除部门",
          message: "删除后将解除该部门下成员与知识库关联，确定继续？",
          confirmText: "删除",
          danger: true,
        });
        if (!ok) return;
        try {
          await api.delete(`/departments/${btn.getAttribute("data-del")}`);
          toast("已删除", "success");
          pageDepartments();
        } catch (e) {
          toast(e.message || "删除失败", "error");
        }
      };
    });
  } catch (e) {
    document.getElementById("pageRoot").innerHTML = `<div class="card text-danger">${escapeHtml(e.message)}</div>`;
  }
}

async function pageDepartmentDetail(deptId) {
  if (!requirePerm("department:read", "部门详情")) return;
  const canWrite = hasPermission("department:write");
  document.getElementById("pageRoot").innerHTML = `<div class="loading">加载部门详情…</div>`;
  try {
    const d = await api.get(`/departments/${deptId}`);
    const members = d.members || [];
    const kbs = d.knowledge_bases || [];
    document.getElementById("pageRoot").innerHTML = `
      ${pageHead({
        title: d.name || "部门详情",
        desc: `${d.is_enabled ? "启用" : "停用"} · 编码 ${d.code} · 成员 ${members.length} · 知识库 ${kbs.length}`,
        actions: `
          <button type="button" class="btn btn-secondary btn-sm" data-go="/admin/departments">返回列表</button>
          ${canWrite ? `<button type="button" class="btn btn-sm" id="btnEditDept">编辑介绍</button>` : ""}
        `,
      })}
      <div class="page-grid">
      <div class="card span-12">
        <div class="card-header"><div class="card-header-text"><h3 class="card-title">部门介绍</h3></div></div>
        <div style="padding:14px 16px;background:var(--color-bg);border:1px solid var(--color-border);border-radius:var(--radius);white-space:pre-wrap;line-height:1.6">${escapeHtml(d.description || "暂无部门介绍")}</div>
      </div>
      <div class="card span-6">
          <div class="card-header">
            <div class="card-header-text"><h3 class="card-title">成员列表</h3></div>
            ${canWrite ? `<div class="card-header-actions"><button type="button" class="btn btn-secondary btn-sm" id="btnAddMember">添加成员</button></div>` : ""}
          </div>
          <div class="table-wrap"><table class="table">
            <thead><tr><th>用户名</th><th>昵称</th><th>状态</th><th></th></tr></thead>
            <tbody>
              ${
                members.length
                  ? members
                      .map(
                        (u) => `<tr>
                          <td>${escapeHtml(u.username)}</td>
                          <td>${escapeHtml(u.nickname || "-")}</td>
                          <td>${escapeHtml(u.status || "-")}</td>
                          <td>${
                            canWrite
                              ? `<button type="button" class="btn btn-text btn-sm" data-rm-user="${escapeHtml(u.id)}" style="color:var(--color-danger)">移除</button>`
                              : ""
                          }</td>
                        </tr>`
                      )
                      .join("")
                  : `<tr><td colspan="4" class="text-muted">暂无成员</td></tr>`
              }
            </tbody>
          </table></div>
        </div>
        <div class="card span-6">
          <div class="card-header">
            <div class="card-header-text"><h3 class="card-title">关联知识库</h3></div>
            ${canWrite ? `<div class="card-header-actions"><button type="button" class="btn btn-secondary btn-sm" id="btnAddKb">关联知识库</button></div>` : ""}
          </div>
          <div class="table-wrap"><table class="table">
            <thead><tr><th>名称</th><th>可见性</th><th>状态</th><th></th></tr></thead>
            <tbody>
              ${
                kbs.length
                  ? kbs
                      .map(
                        (k) => `<tr>
                          <td>${escapeHtml(k.name)}</td>
                          <td>${k.visibility === "public" ? `<span class="badge badge-success">公开(访客可见)</span>` : `<span class="badge">部门内</span>`}</td>
                          <td>${escapeHtml(k.status || "-")}</td>
                          <td class="col-actions">
                            <div class="table-actions">
                              <button type="button" class="btn btn-text btn-sm" data-go="/admin/knowledge-bases/${escapeHtml(k.id)}">打开</button>
                              ${
                                canWrite
                                  ? `<button type="button" class="btn btn-text btn-sm" data-rm-kb="${escapeHtml(k.id)}" style="color:var(--color-danger)">解除</button>`
                                  : ""
                              }
                            </div>
                          </td>
                        </tr>`
                      )
                      .join("")
                  : `<tr><td colspan="4" class="text-muted">暂无关联知识库</td></tr>`
              }
            </tbody>
          </table></div>
        </div>
      </div>`;

    document.querySelectorAll("[data-go]").forEach((btn) => {
      btn.onclick = () => navigate(btn.getAttribute("data-go"));
    });

    const btnEdit = document.getElementById("btnEditDept");
    if (btnEdit) {
      btnEdit.onclick = () =>
        openDepartmentForm({
          title: `编辑「${d.name}」`,
          dept: d,
          onSave: async (payload) => {
            await api.put(`/departments/${d.id}`, payload);
            toast("部门已更新", "success");
          },
        });
    }

    const btnAddMember = document.getElementById("btnAddMember");
    if (btnAddMember) {
      btnAddMember.onclick = async () => {
        try {
          const usersData = await api.get("/users?page=1&page_size=100");
          const users = (usersData.items || []).filter(
            (u) => String(u.department || "").toUpperCase() !== String(d.code).toUpperCase()
          );
          if (!users.length) {
            toast("没有可添加的用户（均已属于本部门或列表为空）", "error");
            return;
          }
          const options = users
            .map(
              (u) =>
                `<label style="display:block;margin:4px 0"><input type="checkbox" name="uid" value="${escapeHtml(u.id)}" /> ${escapeHtml(u.nickname || u.username)} <small class="text-muted">${escapeHtml(u.username)}${u.department ? ` · 当前 ${escapeHtml(u.department)}` : ""}</small></label>`
            )
            .join("");
          const mask = document.createElement("div");
          mask.className = "modal-mask";
          mask.innerHTML = `
            <form class="modal" style="width:min(480px,calc(100vw - 24px));max-height:90vh;overflow:auto">
              <div class="modal-header"><h3>添加成员到「${escapeHtml(d.name)}」</h3></div>
              <div class="modal-body">${options}</div>
              <div class="modal-footer">
                <button type="button" class="btn btn-secondary" data-close>取消</button>
                <button type="submit" class="btn btn-primary">加入</button>
              </div>
            </form>`;
          document.body.appendChild(mask);
          mask.querySelector("[data-close]").onclick = () => mask.remove();
          mask.addEventListener("click", (e) => {
            if (e.target === mask) mask.remove();
          });
          mask.querySelector("form").onsubmit = async (ev) => {
            ev.preventDefault();
            const ids = [...ev.currentTarget.querySelectorAll('input[name="uid"]:checked')].map((el) => el.value);
            if (!ids.length) {
              toast("请至少选择一名用户", "error");
              return;
            }
            try {
              await api.post(`/departments/${d.id}/members`, { user_ids: ids });
              toast("成员已加入", "success");
              mask.remove();
              pageDepartmentDetail(deptId);
            } catch (err) {
              toast(err.message || "添加失败", "error");
            }
          };
        } catch (e) {
          toast(e.message || "加载用户失败", "error");
        }
      };
    }

    document.querySelectorAll("[data-rm-user]").forEach((btn) => {
      btn.onclick = async () => {
        const ok = await confirmDialog({
          title: "移除成员",
          message: "确定将该用户移出本部门？",
          confirmText: "移除",
          danger: true,
        });
        if (!ok) return;
        try {
          await api.delete(`/departments/${d.id}/members/${btn.getAttribute("data-rm-user")}`);
          toast("已移除", "success");
          pageDepartmentDetail(deptId);
        } catch (e) {
          toast(e.message || "移除失败", "error");
        }
      };
    });

    const btnAddKb = document.getElementById("btnAddKb");
    if (btnAddKb) {
      btnAddKb.onclick = async () => {
        try {
          const kbData = await api.get("/knowledge-bases?page=1&page_size=100");
          const list = (kbData.items || []).filter(
            (k) => String(k.department || "").toUpperCase() !== String(d.code).toUpperCase()
          );
          if (!list.length) {
            toast("没有可关联的知识库", "error");
            return;
          }
          const options = list
            .map(
              (k) =>
                `<label style="display:block;margin:4px 0"><input type="checkbox" name="kid" value="${escapeHtml(k.id)}" /> ${escapeHtml(k.name)} <small class="text-muted">${k.department ? `当前 ${escapeHtml(k.department)}` : "不限部门"}</small></label>`
            )
            .join("");
          const mask = document.createElement("div");
          mask.className = "modal-mask";
          mask.innerHTML = `
            <form class="modal" style="width:min(480px,calc(100vw - 24px));max-height:90vh;overflow:auto">
              <div class="modal-header"><h3>关联知识库到「${escapeHtml(d.name)}」</h3></div>
              <div class="modal-body">${options}</div>
              <div class="modal-footer">
                <button type="button" class="btn btn-secondary" data-close>取消</button>
                <button type="submit" class="btn btn-primary">关联</button>
              </div>
            </form>`;
          document.body.appendChild(mask);
          mask.querySelector("[data-close]").onclick = () => mask.remove();
          mask.addEventListener("click", (e) => {
            if (e.target === mask) mask.remove();
          });
          mask.querySelector("form").onsubmit = async (ev) => {
            ev.preventDefault();
            const ids = [...ev.currentTarget.querySelectorAll('input[name="kid"]:checked')].map((el) => el.value);
            if (!ids.length) {
              toast("请至少选择一个知识库", "error");
              return;
            }
            try {
              await api.post(`/departments/${d.id}/knowledge-bases`, { kb_ids: ids });
              toast("知识库已关联", "success");
              mask.remove();
              pageDepartmentDetail(deptId);
            } catch (err) {
              toast(err.message || "关联失败", "error");
            }
          };
        } catch (e) {
          toast(e.message || "加载知识库失败", "error");
        }
      };
    }

    document.querySelectorAll("[data-rm-kb]").forEach((btn) => {
      btn.onclick = async () => {
        const ok = await confirmDialog({
          title: "解除关联",
          message: "确定解除该知识库与本部门的关联？",
          confirmText: "解除",
          danger: true,
        });
        if (!ok) return;
        try {
          await api.delete(`/departments/${d.id}/knowledge-bases/${btn.getAttribute("data-rm-kb")}`);
          toast("已解除", "success");
          pageDepartmentDetail(deptId);
        } catch (e) {
          toast(e.message || "解除失败", "error");
        }
      };
    });
  } catch (e) {
    document.getElementById("pageRoot").innerHTML = `<div class="card text-danger">${escapeHtml(e.message)}</div>`;
  }
}

/* ========== 大模型管理 ========== */
/**
 * 管理端模型预设仅用于辅助填写，不限制管理员接入兼容模型。
 * Rerank 默认项与后端 `.env.example` 保持一致，避免类型下拉有 rerank 却没有可选模型。
 */
const MODEL_PRESETS = {
  llm: [
    { provider: "openai", model: "gpt-4o", baseUrl: "", keyEnv: "LLM_API_KEY" },
    { provider: "dashscope", model: "qwen-plus", baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1", keyEnv: "LLM_API_KEY" },
  ],
  embedding: [
    { provider: "dashscope", model: "text-embedding-v3", baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1", keyEnv: "EMBEDDING_API_KEY" },
    { provider: "openai", model: "text-embedding-3-large", baseUrl: "", keyEnv: "EMBEDDING_API_KEY" },
  ],
  rerank: [
    { provider: "cohere", model: "rerank-v4.0-pro", baseUrl: "https://api.cohere.ai", keyEnv: "RERANK_API_KEY" },
    { provider: "cohere", model: "rerank-v4.0-fast", baseUrl: "https://api.cohere.ai", keyEnv: "RERANK_API_KEY" },
    { provider: "cohere", model: "rerank-v3.5", baseUrl: "https://api.cohere.ai", keyEnv: "RERANK_API_KEY" },
  ],
};

function openModelForm({ title, model = null, onSave }) {
  closeAllModals();
  const dialogId = `modelForm-${Date.now()}`;
  const m = model || {};
  document.body.insertAdjacentHTML(
    "beforeend",
    `<div id="${dialogId}" class="modal-backdrop" style="display:flex">
      <form class="modal" style="max-width:560px;width:92%">
        <div class="modal-header"><h3>${escapeHtml(title)}</h3></div>
        <div class="modal-body">
          <label class="form-label">显示名称</label>
          <input class="form-control" name="name" required value="${escapeHtml(m.name || "")}" />
          <label class="form-label" style="margin-top:10px">类型</label>
          <select class="form-control" name="model_type" ${model ? "disabled" : ""}>
            ${["llm", "embedding", "rerank"]
              .map((t) => `<option value="${t}" ${m.model_type === t ? "selected" : ""}>${t}</option>`)
              .join("")}
          </select>
          <label class="form-label" style="margin-top:10px">提供方</label>
          <input class="form-control" name="provider" list="${dialogId}-providers" value="${escapeHtml(m.provider || "")}" placeholder="openai / dashscope / cohere" />
          <datalist id="${dialogId}-providers"></datalist>
          <label class="form-label" style="margin-top:10px">模型名称</label>
          <input class="form-control" name="model_name" list="${dialogId}-models" required value="${escapeHtml(m.model_name || "")}" placeholder="请选择预设或填写兼容模型名" />
          <datalist id="${dialogId}-models"></datalist>
          <label class="form-label" style="margin-top:10px">API Base URL</label>
          <input class="form-control" name="base_url" value="${escapeHtml(m.base_url || "")}" placeholder="https://…" />
          <label class="form-label" style="margin-top:10px">API Key 环境变量名</label>
          <input class="form-control" name="api_key_env" value="${escapeHtml(m.api_key_env || "")}" placeholder="如 LLM_API_KEY（密钥写在 .env）" />
          <label class="form-label" style="margin-top:10px">优先级（数值越小越优先）</label>
          <input class="form-control" name="priority" type="number" min="0" max="10000" value="${escapeHtml(String(m.priority ?? 100))}" />
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" data-close>取消</button>
          <button class="btn btn-primary" type="submit">保存</button>
        </div>
      </form>
    </div>`
  );
  const root = document.getElementById(dialogId);
  const typeInput = root.querySelector('[name="model_type"]');
  const providerInput = root.querySelector('[name="provider"]');
  const modelInput = root.querySelector('[name="model_name"]');
  const baseUrlInput = root.querySelector('[name="base_url"]');
  const keyEnvInput = root.querySelector('[name="api_key_env"]');

  /** 根据类型刷新预设；新建模型时自动带入首个推荐项，编辑时保留管理员原值。 */
  const refreshModelPresets = ({ fillRecommended = false } = {}) => {
    const type = typeInput.value || "llm";
    const presets = MODEL_PRESETS[type] || [];
    root.querySelector(`#${dialogId}-providers`).innerHTML = [...new Set(presets.map((item) => item.provider))]
      .map((provider) => `<option value="${escapeHtml(provider)}"></option>`)
      .join("");
    root.querySelector(`#${dialogId}-models`).innerHTML = presets
      .map((item) => `<option value="${escapeHtml(item.model)}">${escapeHtml(item.provider)}</option>`)
      .join("");
    if (fillRecommended && presets[0]) {
      providerInput.value = presets[0].provider;
      modelInput.value = presets[0].model;
      baseUrlInput.value = presets[0].baseUrl;
      keyEnvInput.value = presets[0].keyEnv;
    }
  };

  typeInput.addEventListener("change", () => refreshModelPresets({ fillRecommended: true }));
  modelInput.addEventListener("change", () => {
    const preset = (MODEL_PRESETS[typeInput.value] || []).find((item) => item.model === modelInput.value);
    if (!preset) return;
    providerInput.value = preset.provider;
    baseUrlInput.value = preset.baseUrl;
    keyEnvInput.value = preset.keyEnv;
  });
  refreshModelPresets({ fillRecommended: !model });

  root.querySelector("[data-close]").onclick = () => root.remove();
  root.onclick = (e) => {
    if (e.target === root) root.remove();
  };
  root.querySelector("form").onsubmit = async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload = {
      name: String(form.get("name") || "").trim(),
      model_type: String(form.get("model_type") || m.model_type || "llm"),
      provider: String(form.get("provider") || "").trim() || "custom",
      model_name: String(form.get("model_name") || "").trim(),
      base_url: String(form.get("base_url") || "").trim() || null,
      api_key_env: String(form.get("api_key_env") || "").trim() || null,
      priority: Number(form.get("priority") || 100),
      is_enabled: true,
    };
    try {
      await onSave(payload);
      root.remove();
      pageModels();
    } catch (error) {
      toast(error.message || "保存失败", "error");
    }
  };
}

async function pageModels() {
  if (!requirePerm("model:read", "大模型管理")) return;
  const canWrite = hasPermission("model:write");
  document.getElementById("pageRoot").innerHTML = `<div class="loading">加载模型配置…</div>`;
  try {
    const data = await api.get("/models?page=1&page_size=50");
    const items = data.items || [];
    document.getElementById("pageRoot").innerHTML = `
      ${pageHead({
        title: "大模型管理",
        desc: "API Key 通过环境变量名引用；同类型按优先级升序选用。",
        actions: canWrite
          ? `<button class="btn btn-sm" id="btnNewModel">添加模型</button>`
          : "",
      })}
      <div class="page-grid">
      <div class="card panel-fill span-12">
        <div class="card-header">
          <div class="card-header-text">
            <h3 class="card-title">LLM / Embedding / Rerank</h3>
            <p class="card-sub">${canWrite ? "可编辑密钥引用与优先级" : "仅超级管理员可配置密钥与优先级（需 model:write）"}</p>
          </div>
        </div>
        <div class="table-wrap"><table class="table table-models">
          <colgroup>
            <col class="models-col-name" />
            <col class="models-col-type" />
            <col class="models-col-model" />
            <col class="models-col-url" />
            <col class="models-col-key" />
            <col class="models-col-priority" />
            <col class="models-col-enabled" />
            <col class="models-col-default" />
            <col class="models-col-actions" />
          </colgroup>
          <thead><tr>
            <th class="col-name">名称</th>
            <th class="col-type">类型</th>
            <th class="col-model">模型</th>
            <th class="col-url">URL</th>
            <th class="col-key">Key 环境变量</th>
            <th class="col-num">优先级</th>
            <th class="col-status">启用</th>
            <th class="col-default">默认</th>
            <th class="col-actions">操作</th>
          </tr></thead>
          <tbody>
            ${items
              .map(
                (m) => `<tr>
                  <td class="col-name">${escapeHtml(m.name)}</td>
                  <td class="col-type"><span class="badge">${escapeHtml(m.model_type)}</span></td>
                  <td class="col-model">${escapeHtml(m.model_name || "-")}</td>
                  <td class="col-url text-muted" title="${escapeHtml(m.base_url || "")}">${escapeHtml(m.base_url || "-")}</td>
                  <td class="col-key">
                    <div class="models-key-cell">
                      <code>${escapeHtml(m.api_key_env || "-")}</code>
                      ${m.has_api_key ? `<span class="badge badge-success">已配置</span>` : ""}
                    </div>
                  </td>
                  <td class="col-num">${escapeHtml(m.priority ?? 100)}</td>
                  <td class="col-status">${m.is_enabled ? `<span class="badge badge-success">是</span>` : `<span class="badge badge-danger">否</span>`}</td>
                  <td class="col-default">${m.is_default ? "✓" : ""}</td>
                  <td class="col-actions">
                    ${
                      canWrite
                        ? `<div class="table-actions table-actions-stack models-actions">
                      <div class="table-actions-row">
                        <button class="btn btn-text btn-sm" data-edit="${escapeHtml(m.id)}">编辑</button>
                      </div>
                      <div class="table-actions-row">
                        <button class="btn ${m.is_enabled ? "btn-danger" : "btn-success"} btn-sm" data-toggle="${escapeHtml(m.id)}" data-on="${m.is_enabled ? 1 : 0}">${m.is_enabled ? "停用" : "启用"}</button>
                      </div>
                    </div>`
                        : `<span class="cell-muted">—</span>`
                    }
                  </td>
                </tr>`
              )
              .join("")}
          </tbody>
        </table></div>
      </div>
      <div class="card span-12" id="usageCard">
        <div class="card-header">
          <div class="card-header-text">
            <h3 class="card-title">模型用量监测</h3>
            <p class="card-sub">Langfuse 用量汇总</p>
          </div>
          <div class="card-header-actions">
          <select class="form-control" id="usageModel" style="width:auto;min-width:180px">
            <option value="">全部模型</option>
            ${Array.from(new Set(items.map((m) => m.model_name).filter(Boolean)))
              .map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`)
              .join("")}
          </select>
          <select class="form-control" id="usageDays" style="width:auto">
            <option value="7">近 7 天</option>
            <option value="30" selected>近 30 天</option>
            <option value="90">近 90 天</option>
          </select>
          <button class="btn btn-sm" id="usageRefresh">刷新</button>
          </div>
        </div>
        <div id="usageBody"><div class="loading">加载用量…</div></div>
      </div>
      </div>`;

    const usageModelSel = document.getElementById("usageModel");
    const usageDaysSel = document.getElementById("usageDays");
    const usageRefreshBtn = document.getElementById("usageRefresh");
    const loadUsage = () =>
      renderModelUsage(usageModelSel.value, Number(usageDaysSel.value || 30));
    if (usageModelSel) usageModelSel.onchange = loadUsage;
    if (usageDaysSel) usageDaysSel.onchange = loadUsage;
    if (usageRefreshBtn) usageRefreshBtn.onclick = loadUsage;
    loadUsage();

    const btnNew = document.getElementById("btnNewModel");
    if (btnNew) {
      btnNew.onclick = () =>
        openModelForm({
          title: "添加模型",
          onSave: async (payload) => {
            await api.post("/models", payload);
            toast("模型已添加", "success");
          },
        });
    }

    document.querySelectorAll("[data-edit]").forEach((btn) => {
      btn.onclick = () => {
        const model = items.find((x) => x.id === btn.getAttribute("data-edit"));
        if (!model) return;
        openModelForm({
          title: `编辑「${model.name}」`,
          model,
          onSave: async (payload) => {
            const { model_type, ...rest } = payload;
            await api.put(`/models/${model.id}`, rest);
            toast("模型已更新", "success");
          },
        });
      };
    });

    document.querySelectorAll("[data-toggle]").forEach((btn) => {
      btn.onclick = async () => {
        const id = btn.getAttribute("data-toggle");
        const on = btn.getAttribute("data-on") === "1";
        try {
          await api.patch(`/models/${id}/status`, { is_enabled: !on });
          toast("已更新", "success");
          pageModels();
        } catch (e) {
          toast(e.message || "更新失败", "error");
        }
      };
    });
  } catch (e) {
    document.getElementById("pageRoot").innerHTML = `<div class="card text-danger">${escapeHtml(e.message)}</div>`;
  }
}

function fmtNum(n) {
  const v = Number(n || 0);
  return v.toLocaleString("zh-CN");
}

async function renderModelUsage(model, days) {
  const body = document.getElementById("usageBody");
  if (!body) return;
  body.innerHTML = `<div class="loading">加载用量…</div>`;
  try {
    const qs = new URLSearchParams({ days: String(days || 30) });
    if (model) qs.set("model", model);
    const data = await api.get(`/models/usage?${qs.toString()}`);
    if (!data.enabled) {
      body.innerHTML = `<p class="text-muted">未启用 Langfuse 监测：请在 <code>.env</code> 配置 <code>LANGFUSE_PUBLIC_KEY</code> / <code>LANGFUSE_SECRET_KEY</code> 后重启后端。</p>`;
      return;
    }
    const t = data.totals || {};
    const models = data.models || [];
    const rangeLabel = `${(data.range && data.range.days) || days} 天`;
    const noticeHtml = data.notice
      ? `<div class="usage-notice">提示：${escapeHtml(data.notice)}</div>`
      : "";

    const statCard = (label, value) =>
      `<div class="stat-card usage-stat-card"><div class="label">${label}</div><div class="value">${value}</div></div>`;

    let html = `
      ${noticeHtml}
      <div class="stat-grid usage-stat-grid">
        ${statCard("总 Token", fmtNum(t.total_tokens))}
        ${statCard("输入 Token", fmtNum(t.input_tokens))}
        ${statCard("输出 Token", fmtNum(t.output_tokens))}
        ${statCard("调用次数", fmtNum(t.total_observations))}
        ${statCard("会话数", fmtNum(t.total_traces))}
        ${statCard("成本 (USD)", "$" + (t.total_cost || 0).toFixed(4))}
      </div>
      <p class="text-muted" style="margin:0 0 10px">统计范围：最近 ${rangeLabel}${model ? `，模型：<code>${escapeHtml(model)}</code>` : "（全部模型）"}</p>`;

    if (!models.length) {
      html += `<p class="text-muted">该时间范围内暂无用量数据。发起几次问答后再刷新即可看到统计。</p>`;
      body.innerHTML = html;
      return;
    }

    html += `<div class="table-wrap"><table class="table">
      <thead><tr><th>模型</th><th>输入 Token</th><th>输出 Token</th><th>总 Token</th><th>调用次数</th><th>会话数</th><th>成本 (USD)</th></tr></thead>
      <tbody>
        ${models
          .map(
            (mu) => `<tr>
              <td><code>${escapeHtml(mu.model)}</code></td>
              <td>${fmtNum(mu.input_tokens)}</td>
              <td>${fmtNum(mu.output_tokens)}</td>
              <td>${fmtNum(mu.total_tokens)}</td>
              <td>${fmtNum(mu.total_observations)}</td>
              <td>${fmtNum(mu.total_traces)}</td>
              <td>$${(mu.total_cost || 0).toFixed(4)}</td>
            </tr>`
          )
          .join("")}
      </tbody></table></div>`;

    if (model && models.length === 1 && (models[0].daily || []).length) {
      const daily = models[0].daily;
      html += `<h4 style="margin:16px 0 8px">每日趋势</h4>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>日期</th><th>输入 Token</th><th>输出 Token</th><th>总 Token</th><th>调用次数</th></tr></thead>
          <tbody>
            ${daily
              .map(
                (d) => `<tr>
                  <td>${escapeHtml(d.date || "-")}</td>
                  <td>${fmtNum(d.input_tokens)}</td>
                  <td>${fmtNum(d.output_tokens)}</td>
                  <td>${fmtNum(d.total_tokens)}</td>
                  <td>${fmtNum(d.observations)}</td>
                </tr>`
              )
              .join("")}
          </tbody></table></div>`;
    }

    body.innerHTML = html;
  } catch (e) {
    body.innerHTML = `<p class="text-danger">用量加载失败：${escapeHtml(e.message || "未知错误")}</p>`;
  }
}

/* ========== 知识库工作区（同页 Tab + ?tab=） ========== */
const KB_WS_TABS = ["overview", "docs", "snaps"];
const KB_WS_TAB_LABELS = { overview: "文档详情", docs: "文档上传", snaps: "历史快照" };

function normalizeKbTab(tab) {
  const t = String(tab || "overview").toLowerCase();
  if (t === "documents") return "docs";
  if (t === "snapshots") return "snaps";
  if (t === "acl") return "overview"; // ACL 入口已下线，旧链接回退到详情
  return KB_WS_TABS.includes(t) ? t : "overview";
}

function getKbTabFromHash() {
  const q = location.hash.split("?")[1] || "";
  return normalizeKbTab(new URLSearchParams(q).get("tab"));
}

function kbWorkspacePath(kbId, tab) {
  const t = normalizeKbTab(tab);
  return t === "overview" ? `/admin/knowledge-bases/${kbId}` : `/admin/knowledge-bases/${kbId}?tab=${t}`;
}

function isKbDocsView(kbId) {
  const path = currentPath();
  const re = new RegExp(`^/admin/knowledge-bases/${String(kbId).replace(/[.*+?^${}()|[\\]\\\\]/g, "\\$&")}$`);
  if (!re.test(path)) return false;
  return getKbTabFromHash() === "docs";
}

function renderKbWorkspaceBar(kbId, kbName, tab, kbList) {
  const curTab = normalizeKbTab(tab);
  const options = (kbList || [])
    .map(
      (k) =>
        `<option value="${escapeHtml(k.id)}" ${String(k.id) === String(kbId) ? "selected" : ""}>${escapeHtml(k.name || k.id)}</option>`
    )
    .join("");
  const visibleTabs = KB_WS_TABS.filter((t) => {
    if (t === "docs") return hasPermission("doc:read");
    if (t === "snaps") return hasPermission("snapshot:read");
    return true;
  });
  const tabs = visibleTabs
    .map(
      (t) =>
        `<button type="button" class="kb-ws-tab ${t === curTab ? "is-active" : ""}" data-kb-tab="${t}">${KB_WS_TAB_LABELS[t]}</button>`
    )
    .join("");
  return `<nav class="kb-workspace-bar" aria-label="知识库工作区">
    <div class="kb-ws-nav">
      <button type="button" class="kb-ws-tab kb-ws-back" data-go="/admin/knowledge-bases">知识库管理</button>
      <span class="kb-ws-sep" aria-hidden="true">——</span>
      <select class="form-control kb-ws-select" id="kbWsSelect" aria-label="切换知识库">${options}</select>
    </div>
    <div class="kb-ws-tabs" role="tablist">${tabs}</div>
  </nav>`;
}

function bindKbWorkspaceBar(kbId) {
  document.querySelectorAll(".kb-workspace-bar [data-go]").forEach((b) =>
    b.addEventListener("click", () => navigate(b.getAttribute("data-go")))
  );
  const sel = document.getElementById("kbWsSelect");
  if (sel) {
    sel.onchange = () => {
      const nextId = sel.value;
      if (nextId && String(nextId) !== String(kbId)) navigate(kbWorkspacePath(nextId, getKbTabFromHash()));
    };
  }
  document.querySelectorAll(".kb-ws-tab[data-kb-tab]").forEach((btn) => {
    btn.onclick = () => {
      const t = btn.getAttribute("data-kb-tab");
      if (normalizeKbTab(t) !== getKbTabFromHash()) navigate(kbWorkspacePath(kbId, t));
    };
  });
}

async function pageKbWorkspace(id) {
  if (!requirePerm("kb:read", "知识库")) return;
  let tab = getKbTabFromHash();
  if (tab === "docs" && !hasPermission("doc:read")) tab = "overview";
  if (tab === "snaps" && !hasPermission("snapshot:read")) tab = "overview";
  document.getElementById("pageRoot").innerHTML = `<div class="loading">加载知识库…</div>`;
  let kbList = [];
  let kbName = id;
  try {
    const data = await api.get("/knowledge-bases?page=1&page_size=100");
    kbList = data.items || [];
    const cur = kbList.find((k) => String(k.id) === String(id));
    if (cur) kbName = cur.name || id;
  } catch (e) {
    document.getElementById("pageRoot").innerHTML = `<div class="card text-danger">${escapeHtml(e.message)}</div>`;
    return;
  }
  document.getElementById("pageRoot").innerHTML = `
    ${renderKbWorkspaceBar(id, kbName, tab, kbList)}
    <div id="kbWsBody"></div>`;
  bindKbWorkspaceBar(id);
  if (tab === "docs") await pageDocuments(id, { embedded: true, mountId: "kbWsBody" });
  else if (tab === "snaps") await pageSnapshots(id, { embedded: true, mountId: "kbWsBody" });
  else await pageKbDetail(id, { embedded: true, mountId: "kbWsBody" });
}

/* ========== 知识库列表 ========== */
async function pageKbList() {
  if (!requirePerm("kb:read", "知识库管理")) return;
  document.getElementById("pageRoot").innerHTML = `<div class="loading">加载知识库…</div>`;
  try {
    const [data, departments] = await Promise.all([
      api.get("/knowledge-bases?page=1&page_size=100"),
      loadDepartmentOptions(),
    ]);
    const allItems = data.items || [];
    const statusLabel = (status) =>
      ({ active: "已同步", ready: "已就绪", processing: "处理中", vectorizing: "向量化中" }[String(status || "").toLowerCase()] ||
        status ||
        "待配置");
    const filters = { q: "", department: "", type: "" };

    const matchKb = (k) => {
      const q = filters.q.trim().toLowerCase();
      if (q) {
        const hay = `${k.name || ""} ${k.description || ""} ${(k.tags || []).join(" ")}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      if (filters.type && String(k.type || "").toLowerCase() !== filters.type) return false;
      if (filters.department === "__private__") {
        if (String(k.department || "").trim()) return false;
      } else if (filters.department) {
        if (String(k.department || "").toUpperCase() !== filters.department.toUpperCase()) return false;
      }
      return true;
    };

    const renderCard = (k) => {
      const st = String(k.status || "").toLowerCase();
      const canWriteKb = hasPermission("kb:write");
      return `<article class="kb-card kb-card-clickable" data-kb-open="${escapeHtml(k.id)}" tabindex="0" role="link" aria-label="打开 ${escapeHtml(k.name)}">
          <div class="kb-card-cover"><span>${escapeHtml((k.name || "知").slice(0, 1))}</span>${kbTypeBadge(k.type)}</div>
          <div class="kb-card-body">
            <div class="kb-card-heading"><h3>${escapeHtml(k.name)}</h3><span class="status-dot ${st === "processing" || st === "vectorizing" ? "is-processing" : ""}">${escapeHtml(statusLabel(k.status))}</span></div>
            <p>${escapeHtml(k.description || "暂未填写知识库简介，可进入详情页补充说明。")}</p>
            <div class="kb-card-meta"><span>${escapeHtml(k.document_count ?? k.doc_count ?? 0)} 份文档</span><span>${formatDateTime(k.updated_at)}</span></div>
            <div class="kb-card-access kb-card-tags">${accessScopeBadge(k)}</div>
            <div class="kb-card-actions">
              <button type="button" class="btn btn-sm kb-card-btn kb-card-btn-detail" data-kb-detail="${escapeHtml(k.id)}">文档详情</button>
              ${
                canWriteKb
                  ? `<button type="button" class="btn btn-sm kb-card-btn kb-card-btn-del" data-kb-del="${escapeHtml(k.id)}" data-kb-name="${escapeHtml(k.name || "")}">删除</button>`
                  : ""
              }
            </div>
          </div>
        </article>`;
    };

    const bindCards = () => {
      const stopOnAction = (e) => e.target.closest("[data-kb-detail], [data-kb-del]");
      document.querySelectorAll(".kb-card-clickable[data-kb-open]").forEach((card) => {
        const open = () => navigate(kbWorkspacePath(card.getAttribute("data-kb-open"), "overview"));
        card.addEventListener("click", (e) => {
          if (stopOnAction(e)) return;
          open();
        });
        card.addEventListener("keydown", (e) => {
          if (stopOnAction(e)) return;
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            open();
          }
        });
      });
      document.querySelectorAll("[data-kb-detail]").forEach((b) => {
        b.addEventListener("click", (e) => {
          e.stopPropagation();
          navigate(kbWorkspacePath(b.getAttribute("data-kb-detail"), "overview"));
        });
      });
      document.querySelectorAll("[data-kb-del]").forEach((b) => {
        b.addEventListener("click", async (e) => {
          e.stopPropagation();
          const kid = b.getAttribute("data-kb-del");
          const kname = b.getAttribute("data-kb-name") || kid;
          const ok = await confirmDialog({
            title: "删除知识库",
            message: `确定删除知识库「${escapeHtml(kname)}」吗？删除后将无法恢复。`,
            confirmText: "删除",
            danger: true,
          });
          if (!ok) return;
          try {
            await api.delete(`/knowledge-bases/${kid}`);
            toast("已删除", "success");
            await pageKbList();
          } catch (err) {
            toast(err.message || "删除失败", "error");
          }
        });
      });
      const btnCreateCard = document.getElementById("btnCreateKbCard");
      if (btnCreateCard) btnCreateCard.onclick = () => document.getElementById("btnCreateKb")?.click();
    };

    const paintList = () => {
      const items = allItems.filter(matchKb);
      const grid = document.getElementById("kbCardGrid");
      const summary = document.getElementById("kbListSummary");
      if (summary) {
        const docTotal = items.reduce(
          (sum, k) => sum + Number(k.document_count ?? k.doc_count ?? 0),
          0
        );
        summary.innerHTML = `<span>共 <b>${items.length}</b> 个知识库 · 文档合计 <b>${docTotal}</b> 份${
          items.length !== allItems.length ? `（筛选自 ${allItems.length} 个知识库）` : ""
        }</span><span>仅展示当前账号有权访问的内容</span>`;
      }
      if (!grid) return;
      const createCard = hasPermission("kb:write")
        ? `<button type="button" class="kb-create-card" id="btnCreateKbCard"><span>+</span><b>创建新知识库</b><small>配置类型和访问范围</small></button>`
        : "";
      grid.innerHTML =
        createCard +
        (items.map(renderCard).join("") ||
          `<div class="card empty-state span-12">${
            allItems.length ? "无匹配的知识库，请调整搜索或筛选条件" : "暂未创建可访问的知识库"
          }</div>`);
      bindCards();
    };

    const deptFilterOpts = [
      `<option value="">全部部门</option>`,
      `<option value="__private__">私有</option>`,
      ...(departments || [])
        .filter((d) => d.is_enabled !== false)
        .map((d) => `<option value="${escapeHtml(d.code)}">${escapeHtml(d.name)}（${escapeHtml(d.code)}）</option>`),
    ].join("");

    document.getElementById("pageRoot").innerHTML = `
      ${pageHead({
        title: "知识库管理",
        desc: "管理企业知识资产、文档索引与访问范围。",
        actions: hasPermission("kb:write") ? "" : `<span class="role-chip">只读访问</span>`,
      })}
      <div class="kb-list-toolbar">
        <div class="kb-list-toolbar-filters">
          <input type="search" class="form-control kb-list-search" id="kbSearchInput" placeholder="搜索名称、简介或标签…" autocomplete="off" />
          <select class="form-control kb-list-filter" id="kbFilterDept" aria-label="按部门筛选">${deptFilterOpts}</select>
          <select class="form-control kb-list-filter" id="kbFilterType" aria-label="按类型筛选">
            <option value="">全部类型</option>
            <option value="general">通用知识</option>
            <option value="technical">技术文档</option>
            <option value="product">产品手册</option>
            <option value="faq">FAQ</option>
          </select>
        </div>
        <div class="kb-list-toolbar-create">
          ${
            hasPermission("kb:write")
              ? `<button class="btn" id="btnCreateKb">+ 新建知识库</button>`
              : ""
          }
        </div>
        <div class="kb-list-toolbar-spacer" aria-hidden="true"></div>
      </div>
      <div class="kb-summary-row" id="kbListSummary"></div>
      <section class="kb-card-grid" id="kbCardGrid"></section>`;

    paintList();

    const searchInput = document.getElementById("kbSearchInput");
    const deptSel = document.getElementById("kbFilterDept");
    const typeSel = document.getElementById("kbFilterType");
    let searchTimer = null;
    const applyFilters = () => {
      filters.q = searchInput?.value || "";
      filters.department = deptSel?.value || "";
      filters.type = typeSel?.value || "";
      paintList();
    };
    if (searchInput) {
      searchInput.oninput = () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(applyFilters, 180);
      };
    }
    if (deptSel) deptSel.onchange = applyFilters;
    if (typeSel) typeSel.onchange = applyFilters;

    const btnCreate = document.getElementById("btnCreateKb");
    if (btnCreate) {
      btnCreate.onclick = async () => {
        const deptOptions = departmentSelectHtml(departments, "", { emptyLabel: "私有（仅创建者与管理员可见）" });
        const mask = document.createElement("div");
        mask.className = "modal-mask";
        mask.innerHTML = `
          <form class="modal" style="width:min(520px,calc(100vw - 24px));max-height:90vh;overflow:auto">
            <div class="modal-header"><h3>创建知识库</h3></div>
            <div class="modal-body">
              <label class="form-label">名称 <span style="color:var(--color-danger)">*</span></label>
              <input class="form-control" name="name" required maxlength="200" placeholder="知识库名称" />
              <label class="form-label" style="margin-top:10px">类型</label>
              <select class="form-control" name="type">
                <option value="general">通用知识</option>
                <option value="technical">技术文档</option>
                <option value="product">产品手册</option>
                <option value="faq">FAQ</option>
              </select>
              <label class="form-label" style="margin-top:10px">访问范围（所属部门）</label>
              <select class="form-control" name="department">${deptOptions}</select>
              <p class="text-muted" style="margin:6px 0 0;font-size:12px">访客专用=所有人可见；某部门=仅该部门员工与管理员；私有=仅创建者与管理员。功能权限请在「组织与权限」由超管配置。</p>
              <label class="form-label" style="margin-top:10px">标签（逗号分隔）</label>
              <input class="form-control" name="tags" maxlength="500" placeholder="可选" />
              <label class="form-label" style="margin-top:10px">描述</label>
              <textarea class="form-control" name="description" rows="3" maxlength="2000" placeholder="可选"></textarea>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-secondary" data-close>取消</button>
              <button type="submit" class="btn btn-primary">创建</button>
            </div>
          </form>`;
        document.body.appendChild(mask);
        mask.querySelector("[data-close]").onclick = () => mask.remove();
        mask.addEventListener("click", (e) => {
          if (e.target === mask) mask.remove();
        });
        mask.querySelector("form").onsubmit = async (ev) => {
          ev.preventDefault();
          const fd = new FormData(ev.currentTarget);
          const kbName = String(fd.get("name") || "").trim();
          const dept = String(fd.get("department") || "").trim().toUpperCase() || null;
          const tags = String(fd.get("tags") || "")
            .split(",")
            .map((t) => t.trim())
            .filter(Boolean);
          if (!kbName) {
            toast("请填写名称", "error");
            return;
          }
          const submitBtn = ev.currentTarget.querySelector('button[type="submit"]');
          if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.textContent = "创建中…";
          }
          try {
            const kb = await api.post("/knowledge-bases", {
              name: kbName,
              type: String(fd.get("type") || "general"),
              description: String(fd.get("description") || "").trim(),
              tags,
              department: dept,
              embedding_model: "text-embedding-v3",
              chunk_size: 500,
              chunk_overlap: 50,
            });
            toast("创建成功", "success");
            mask.remove();
            navigate(`/admin/knowledge-bases/${kb.id || ""}`);
          } catch (e) {
            toast(e.message || "创建失败", "error");
            if (submitBtn) {
              submitBtn.disabled = false;
              submitBtn.textContent = "创建";
            }
          }
        };
      };
    }
  } catch (e) {
    document.getElementById("pageRoot").innerHTML = `<div class="card text-danger">${escapeHtml(e.message)}</div>`;
  }
}

/* ========== 知识库详情（工作区内嵌：基本信息） ========== */
async function pageKbDetail(id, opts = {}) {
  const { embedded = false, mountId = "pageRoot" } = opts;
  if (!embedded && !requirePerm("kb:read", "知识库详情")) return;
  const canWrite = hasPermission("kb:write");
  const mountEl = () => document.getElementById(mountId);

  async function render() {
    mountEl().innerHTML = `<div class="loading">加载详情…</div>`;
    try {
      const k = await api.get(`/knowledge-bases/${id}`);
      const overviewHead = pageHead({
        title: k.name || "知识库详情",
        desc: `${k.type || "通用"} · ${k.status || "-"} · Embedding ${k.embedding_model || "-"}`,
        actions: canWrite
          ? `<button type="button" class="btn btn-sm kb-card-btn kb-card-btn-detail" id="btnEditKb">编辑知识库</button>
             <button class="btn btn-danger btn-sm" id="btnDeleteKb">删除知识库</button>`
          : "",
      });
      const overviewGrid = `<div class="page-grid kb-detail-top">
          <div class="card span-6">
            <div class="card-header">
              <div class="card-header-text"><h3 class="card-title">基本信息</h3></div>
            </div>
            <div class="meta-list">
              <div class="meta-row"><span class="meta-label">类型</span><span class="meta-value">${escapeHtml(
                ({ general: "通用知识", technical: "技术文档", product: "产品手册", faq: "FAQ" }[String(k.type || "").toLowerCase()] ||
                  k.type ||
                  "-")
              )}</span></div>
              <div class="meta-row"><span class="meta-label">简介</span><span class="meta-value">${escapeHtml(k.description || "无简介")}</span></div>
              <div class="meta-row"><span class="meta-label">标签</span><span class="meta-value">${escapeHtml((k.tags || []).join(", ") || "-")}</span></div>
              <div class="meta-row"><span class="meta-label">访问范围</span><span class="meta-value">${accessScopeBadge(k)}</span></div>
              <div class="meta-row"><span class="meta-label">索引版本</span><span class="meta-value">${escapeHtml(k.current_index_version)}</span></div>
            </div>
          </div>
          <div class="card span-6">
            <div class="card-header"><div class="card-header-text"><h3 class="card-title">概览</h3></div></div>
            <div class="kb-detail-overview-body">
              <div class="stat-grid" style="grid-template-columns:1fr 1fr;margin-bottom:12px">
                <div class="stat-card"><div class="label">文档数</div><div class="value">${escapeHtml(k.document_count ?? k.doc_count ?? 0)}</div></div>
                <div class="stat-card"><div class="label">分段数</div><div class="value">${escapeHtml(k.chunk_count ?? 0)}</div></div>
              </div>
              <div class="meta-list">
                <div class="meta-row"><span class="meta-label">创建</span><span class="meta-value">${formatDateTime(k.created_at)}</span></div>
                <div class="meta-row"><span class="meta-label">更新</span><span class="meta-value">${formatDateTime(k.updated_at)}</span></div>
              </div>
              <p class="page-desc kb-detail-overview-note">知识库可绑定部门；员工仅能上传本部门库。功能权限请在「组织与权限」中由超级管理员配置。管理员与超管不受部门隔离。</p>
            </div>
          </div>
        </div>`;

      mountEl().innerHTML = `${overviewHead}${overviewGrid}`;

      document.querySelectorAll("[data-go]").forEach((b) => b.addEventListener("click", () => navigate(b.getAttribute("data-go"))));

      const btnEdit = document.getElementById("btnEditKb");
      if (btnEdit) {
        btnEdit.onclick = async () => {
          const departments = await loadDepartmentOptions();
          const result = await openWideModal({
            title: "编辑知识库",
            bodyHtml: `
              <label class="text-muted">名称</label>
              <input class="form-control" id="editName" maxlength="200" value="${escapeHtml(k.name)}" style="margin:6px 0 12px" />
              <label class="text-muted">类型</label>
              <select class="form-control" id="editType" style="margin:6px 0 12px">
                <option value="technical" ${k.type === "technical" ? "selected" : ""}>技术文档</option>
                <option value="product" ${k.type === "product" ? "selected" : ""}>产品手册</option>
                <option value="faq" ${k.type === "faq" ? "selected" : ""}>FAQ</option>
                <option value="general" ${k.type === "general" ? "selected" : ""}>通用知识</option>
              </select>
              <label class="text-muted">访问范围（所属部门）</label>
              <select class="form-control" id="editDepartment" style="margin:6px 0 12px">
                ${departmentSelectHtml(departments, k.department, { emptyLabel: "私有（仅创建者与管理员可见）" })}
              </select>
              <p class="text-muted" style="margin:0 0 12px;font-size:12px">访客专用=所有人可见；某部门=仅该部门员工与管理员；私有=仅创建者与管理员。功能权限请在「组织与权限」由超管配置。</p>
              <label class="text-muted">标签（逗号分隔）</label>
              <input class="form-control" id="editTags" maxlength="500" value="${escapeHtml((k.tags || []).join(", "))}" style="margin:6px 0 12px" />
              <label class="text-muted">描述</label>
              <textarea class="form-control" id="editDesc" rows="3" maxlength="2000" style="margin:6px 0">${escapeHtml(k.description || "")}</textarea>`,
            actionsHtml: `
              <button type="button" class="btn btn-secondary" data-act="cancel">取消</button>
              <button type="button" class="btn" data-act="ok">保存</button>`,
          });
          if (!result) return;
          const name = result.root.querySelector("#editName")?.value?.trim();
          const type = result.root.querySelector("#editType")?.value;
          const department = result.root.querySelector("#editDepartment")?.value || "";
          const tags = result.root.querySelector("#editTags")?.value?.split(",").map((t) => t.trim()).filter(Boolean) || [];
          const description = result.root.querySelector("#editDesc")?.value?.trim() || undefined;
          result.root.remove();
          if (!name) {
            toast("请填写名称", "error");
            return;
          }
          try {
            await api.put(`/knowledge-bases/${id}`, {
              name,
              type,
              tags,
              description,
              department: department || null,
            });
            toast("已更新", "success");
            await render();
          } catch (e) {
            toast(e.message || "更新失败", "error");
          }
        };
      }

      const btnDelete = document.getElementById("btnDeleteKb");
      if (btnDelete) {
        btnDelete.onclick = async () => {
          const ok = await confirmDialog({
            title: "删除知识库",
            message: `确定删除知识库「${escapeHtml(k.name)}」吗？删除后将无法恢复。`,
            confirmText: "删除",
            danger: true,
          });
          if (!ok) return;
          try {
            await api.delete(`/knowledge-bases/${id}`);
            toast("已删除", "success");
            navigate("/admin/knowledge-bases");
          } catch (e) {
            toast(e.message || "删除失败", "error");
          }
        };
      }
    } catch (e) {
      mountEl().innerHTML = `<div class="card text-danger">${escapeHtml(e.message)}</div>`;
    }
  }

  await render();
}

/* ========== 文档管理 ========== */
const DOC_BUSY_STATUSES = new Set([
  "uploaded",
  "parsing",
  "processing",
  "normalizing",
  "segmenting",
  "vectorizing",
  "pending_segment",
]);

/** 文档流水线状态：中文文案 + 徽章色 */
const DOC_STATUS_META = {
  uploaded: { label: "已上传", badge: "badge-info" },
  parsing: { label: "解析中", badge: "badge-info" },
  processing: { label: "清洗中", badge: "badge-info" },
  normalizing: { label: "规范化中", badge: "badge-info" },
  segmenting: { label: "分段中", badge: "badge-info" },
  pending_segment: { label: "待分段", badge: "badge-warning" },
  vectorizing: { label: "向量化中", badge: "badge-info" },
  ready: { label: "已就绪", badge: "badge-success" },
  error: { label: "失败", badge: "badge-danger" },
  archived: { label: "已归档", badge: "" },
};

function docStatusBadge(status) {
  const key = String(status || "").toLowerCase();
  const meta = DOC_STATUS_META[key];
  const label = meta?.label || (status ? String(status) : "-");
  const badgeClass = meta?.badge ? `badge ${meta.badge}` : "badge";
  return `<span class="${badgeClass}">${escapeHtml(label)}</span>`;
}

async function pageDocuments(kbId, opts = {}) {
  const { embedded = false, mountId = "pageRoot" } = opts;
  if (!embedded && !requirePerm("doc:read", "文档管理")) return;
  const mountEl = () => document.getElementById(mountId);
  mountEl().innerHTML = `<div class="loading">加载文档…</div>`;

  const canWrite = hasPermission("doc:write");
  const canSegment = hasPermission("doc:segment");
  const canUpload = canWrite || hasPermission("kb:upload");
  let refreshTimer = null;
  const DOC_PAGE_SIZE = 10;
  let listPage = 1;
  let isUploading = false;

  const formatSize = (n) => {
    const v = Number(n);
    if (!Number.isFinite(v) || v < 0) return "-";
    if (v < 1024) return `${v} B`;
    if (v < 1024 * 1024) return `${(v / 1024).toFixed(1)} KB`;
    return `${(v / 1024 / 1024).toFixed(1)} MB`;
  };

  /** @type {{ name: string, file?: File, docId?: string, pipeStatus?: string, status: "pending"|"uploading"|"processing"|"ready"|"upload_error"|"error"|"cancelled", error?: string }[] | null} */
  let uploadBatch = null;
  let uploadBatchDone = false;
  let uploadCancelled = false;
  /** @type {AbortController | null} */
  let uploadAbort = null;

  const UPLOAD_EXTS = new Set([".pdf", ".doc", ".docx", ".txt", ".md"]);
  const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;
  const MAX_BATCH_FILES = 100;

  const dropzoneIdleHtml = () => `
      <div class="kb-dropzone-inner">
        <span class="kb-dropzone-icon" aria-hidden="true"></span>
        <p class="kb-dropzone-title">
          <span class="kb-dropzone-copy-idle">将文件或文件夹拖拽到此处</span>
          <span class="kb-dropzone-copy-active">松手即可上传</span>
        </p>
        <p class="kb-dropzone-lead">
          <span class="kb-dropzone-copy-idle">也可点击本区域选择文件，或用上方按钮选择文件夹（自动扫描可上传文件）</span>
          <span class="kb-dropzone-copy-active">释放鼠标开始批量上传</span>
        </p>
        <ul class="kb-dropzone-meta">
          <li>支持格式：PDF、DOC、DOCX、TXT、MD</li>
          <li>单文件最大：100MB · 支持文件夹递归扫描</li>
          <li>一次可批量上传多个文件（逐个上传）</li>
        </ul>
      </div>`;

  const statusLabel = (item) => {
    if (item.status === "pending") return "等待中";
    if (item.status === "uploading") return "上传中…";
    if (item.status === "processing") {
      const pipe = String(item.pipeStatus || "").toLowerCase();
      const meta = DOC_STATUS_META[pipe];
      return meta?.label ? `处理中 · ${meta.label}` : "处理中…";
    }
    if (item.status === "ready") return "已就绪";
    if (item.status === "cancelled") return "已取消";
    if (item.status === "upload_error") return item.error ? `上传失败：${item.error}` : "上传失败";
    if (item.status === "error") return item.error ? `处理失败：${item.error}` : "处理失败";
    return item.error || "失败";
  };

  const uploadRowClass = (status) => {
    if (status === "ready") return "is-success";
    if (status === "processing") return "is-processing";
    if (status === "upload_error" || status === "error") return "is-error";
    if (status === "uploading") return "is-uploading";
    if (status === "cancelled") return "is-cancelled";
    if (status === "pending") return "is-pending";
    return `is-${status}`;
  };

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  const PIPE_POLL_MS = 1800;
  const PIPE_POLL_MAX_MS = 180000;
  let listRefreshAt = 0;

  const refreshListThrottled = async () => {
    const now = Date.now();
    if (now - listRefreshAt < 2500) return;
    listRefreshAt = now;
    try {
      await renderList();
    } catch {
      /* ignore */
    }
  };

  /** 轮询文档至 ready / error；超时也标为处理失败 */
  const waitForPipeline = async (item) => {
    if (!item?.docId) {
      item.status = "error";
      item.error = "缺少文档 ID，无法跟踪处理状态";
      return;
    }
    item.status = "processing";
    const started = Date.now();
    while (Date.now() - started < PIPE_POLL_MAX_MS) {
      if (uploadCancelled) {
        item.status = "cancelled";
        item.error = "已取消";
        return;
      }
      try {
        const doc = await api.get(`/knowledge-bases/${kbId}/documents/${item.docId}`);
        const st = String(doc?.status || "").toLowerCase();
        item.pipeStatus = st;
        if (st === "ready") {
          item.status = "ready";
          delete item.error;
          return;
        }
        if (st === "error") {
          item.status = "error";
          item.error = String(doc?.error_message || "处理失败").slice(0, 120);
          return;
        }
        if (!DOC_BUSY_STATUSES.has(st) && st && st !== "uploaded") {
          // 未知终态：按失败处理，避免死循环
          item.status = "error";
          item.error = `未知状态：${st}`;
          return;
        }
      } catch (e) {
        if (String(e.message || "").includes("不存在") || String(e.message || "").includes("404")) {
          item.status = "error";
          item.error = "文档已不存在或已被删除";
          return;
        }
        // 瞬时错误继续轮询
      }
      paintDropzoneBatch();
      await refreshListThrottled();
      await sleep(PIPE_POLL_MS);
    }
    item.status = "error";
    item.error = "处理超时，请在文档列表查看或重试";
  };

  const extOfName = (name) => {
    const n = String(name || "");
    const i = n.lastIndexOf(".");
    return i >= 0 ? n.slice(i).toLowerCase() : "";
  };

  const isHiddenRelPath = (rel) =>
    String(rel || "")
      .replace(/\\/g, "/")
      .split("/")
      .some((p) => p.startsWith(".") && p !== "." && p !== "..");

  /** 相对路径压扁为上传文件名，避免同名冲突 */
  const flattenUploadName = (relPath, fallbackName) => {
    const parts = String(relPath || fallbackName || "unnamed")
      .replace(/\\/g, "/")
      .replace(/^\/+/, "")
      .split("/")
      .filter(Boolean);
    const joined = parts.join("_") || String(fallbackName || "unnamed");
    return joined.replace(/[^\w.\u4e00-\u9fff\-]+/g, "_").slice(0, 200);
  };

  const readDirectoryEntries = (dirEntry) =>
    new Promise((resolve, reject) => {
      const reader = dirEntry.createReader();
      const all = [];
      const readBatch = () => {
        reader.readEntries((batch) => {
          if (!batch.length) return resolve(all);
          all.push(...batch);
          readBatch();
        }, reject);
      };
      readBatch();
    });

  const entryToCollected = async (entry, pathPrefix = "") => {
    if (!entry) return [];
    if (entry.isFile) {
      const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
      const rel = pathPrefix
        ? `${pathPrefix}/${file.name}`
        : String(entry.fullPath || file.name).replace(/^\/+/, "");
      return [{ file, relativePath: rel }];
    }
    if (entry.isDirectory) {
      const children = await readDirectoryEntries(entry);
      const prefix = pathPrefix ? `${pathPrefix}/${entry.name}` : entry.name;
      const out = [];
      for (const child of children) {
        out.push(...(await entryToCollected(child, prefix)));
      }
      return out;
    }
    return [];
  };

  /** 从拖放 DataTransfer 收集文件（支持文件夹） */
  const collectFromDataTransfer = async (dt) => {
    const items = dt?.items;
    if (items?.length) {
      const entries = [];
      for (let i = 0; i < items.length; i++) {
        const item = items[i];
        const entry = item.webkitGetAsEntry?.() || item.getAsEntry?.();
        if (entry) entries.push(entry);
      }
      if (entries.length) {
        const collected = [];
        for (const entry of entries) {
          collected.push(...(await entryToCollected(entry)));
        }
        return collected;
      }
    }
    return Array.from(dt?.files || []).map((f) => ({
      file: f,
      relativePath: f.webkitRelativePath || f.name,
    }));
  };

  /** 从 input.files（含 webkitdirectory）收集 */
  const collectFromFileList = (fileList) =>
    Array.from(fileList || []).map((f) => ({
      file: f,
      relativePath: f.webkitRelativePath || f.name,
    }));

  /** 过滤可上传文件；同名用相对路径压扁 */
  const filterUploadableFiles = (collected) => {
    const files = [];
    let skipped = 0;
    for (const item of collected || []) {
      const raw = item.file;
      if (!raw) continue;
      const rel = String(item.relativePath || raw.name || "").replace(/\\/g, "/");
      if (isHiddenRelPath(rel)) {
        skipped += 1;
        continue;
      }
      if (!raw.size) {
        skipped += 1;
        continue;
      }
      if (raw.size > MAX_UPLOAD_BYTES) {
        skipped += 1;
        continue;
      }
      if (!UPLOAD_EXTS.has(extOfName(raw.name))) {
        skipped += 1;
        continue;
      }
      const uploadName = flattenUploadName(rel, raw.name);
      const file =
        uploadName === raw.name
          ? raw
          : new File([raw], uploadName, { type: raw.type, lastModified: raw.lastModified });
      files.push({
        file,
        displayName: rel.includes("/") ? rel : raw.name,
      });
    }
    return { files, skipped };
  };

  const clearUploadSession = () => {
    uploadBatch = null;
    uploadBatchDone = false;
    uploadCancelled = false;
    uploadAbort = null;
  };

  const paintDropzoneBatch = () => {
    const zone = document.getElementById("kbDropzone");
    if (!zone || !uploadBatch?.length) return;
    const total = uploadBatch.length;
    const ready = uploadBatch.filter((x) => x.status === "ready").length;
    const pipeFail = uploadBatch.filter((x) => x.status === "error").length;
    const uploadFail = uploadBatch.filter((x) => x.status === "upload_error").length;
    const fail = pipeFail + uploadFail;
    const cancelled = uploadBatch.filter((x) => x.status === "cancelled").length;
    const processing = uploadBatch.filter((x) => x.status === "processing" || x.status === "uploading").length;
    const pending = uploadBatch.filter((x) => x.status === "pending").length;
    const terminal = ready + fail + cancelled;
    const doneCount = terminal;
    const pct = Math.round((doneCount / total) * 100);
    const busy = !uploadBatchDone || processing > 0 || pending > 0;
    const canResume = uploadBatchDone && cancelled > 0;
    const canRetry = uploadBatchDone && fail > 0 && cancelled === 0;
    zone.classList.remove("dragover");
    zone.classList.toggle("is-uploading", busy);
    zone.classList.toggle("is-upload-report", uploadBatchDone && !busy);
    zone.setAttribute("aria-busy", busy ? "true" : "false");
    zone.style.pointerEvents = "";
    zone.style.cursor = "default";
    zone.onclick = null;

    let title;
    let lead;
    if (busy && (pending > 0 || uploadBatch.some((x) => x.status === "uploading"))) {
      const step = Math.min(uploadBatch.filter((x) => x.status !== "pending").length + 1, total);
      title = `文档上传中 · ${Math.min(step, total)}/${total}`;
      lead = "正在逐个上传；上传后仍会解析与向量化，可随时取消剩余文件";
    } else if (busy && processing > 0) {
      title = `处理中 · ${ready + fail}/${total}`;
      lead = "文件已接收，正在解析 / 分段 / 向量化，请稍候";
    } else if (cancelled) {
      title = `已结束 · 就绪 ${ready} · 失败 ${fail} · 取消 ${cancelled}`;
      lead = "可继续上传剩余文件；处理失败项会留在文档列表，可点重试";
    } else if (fail) {
      title = `已结束 · 就绪 ${ready} 个，失败 ${fail} 个`;
      lead = "上传失败可在本区重试；处理失败会留在下方列表，也可点列表「重试」";
    } else {
      title = `全部就绪（${ready} 个）`;
      lead = "本批已全部处理完成，可继续选择新文件或文件夹上传";
    }

    const actionsHtml = busy
      ? `<div class="kb-upload-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}">
            <div class="kb-upload-progress-bar" style="width:${pct}%"></div>
          </div>
          <p class="kb-dropzone-progress-text">${pct}%</p>
          <div class="kb-dropzone-actions">
            <button type="button" class="btn btn-secondary btn-sm" id="btnDropzoneCancel">取消上传</button>
          </div>`
      : `<div class="kb-dropzone-actions">
            ${
              canResume
                ? `<button type="button" class="btn btn-sm" id="btnDropzoneResume">继续上传剩余（${cancelled}）</button>`
                : ""
            }
            ${
              canRetry
                ? `<button type="button" class="btn btn-sm" id="btnDropzoneRetry">重试失败项（${fail}）</button>`
                : ""
            }
            <button type="button" class="btn ${canResume || canRetry ? "btn-secondary" : ""} btn-sm" id="btnDropzoneNew">
              ${canResume || canRetry ? "上传新文件" : "上传更多"}
            </button>
          </div>`;

    zone.innerHTML = `
      <div class="kb-dropzone-inner kb-dropzone-batch">
        ${busy ? `<span class="kb-dropzone-spinner" aria-hidden="true"></span>` : ""}
        <p class="kb-dropzone-title">${escapeHtml(title)}</p>
        <p class="kb-dropzone-lead">${escapeHtml(lead)}</p>
        <ul class="kb-upload-file-list" role="list">
          ${uploadBatch
            .map(
              (item) => `<li class="kb-upload-file ${uploadRowClass(item.status)}">
            <span class="kb-upload-file-name" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</span>
            <span class="kb-upload-file-status" title="${escapeHtml(statusLabel(item))}">${escapeHtml(statusLabel(item))}</span>
          </li>`
            )
            .join("")}
        </ul>
        ${actionsHtml}
      </div>`;

    const btnUpload = document.getElementById("btnAdminUpload");
    if (btnUpload) btnUpload.disabled = busy;
    const btnFolder = document.getElementById("btnAdminUploadFolder");
    if (btnFolder) btnFolder.disabled = busy;

    const btnNew = document.getElementById("btnDropzoneNew");
    if (btnNew) {
      btnNew.onclick = (e) => {
        e.stopPropagation();
        clearUploadSession();
        restoreDropzoneIdle();
      };
    }
    const btnResume = document.getElementById("btnDropzoneResume");
    if (btnResume) {
      btnResume.onclick = (e) => {
        e.stopPropagation();
        resumeUploadBatch("cancelled");
      };
    }
    const btnRetry = document.getElementById("btnDropzoneRetry");
    if (btnRetry) {
      btnRetry.onclick = (e) => {
        e.stopPropagation();
        retryFailedUploadItems();
      };
    }
    const btnCancel = document.getElementById("btnDropzoneCancel");
    if (btnCancel) {
      btnCancel.onclick = (e) => {
        e.stopPropagation();
        if (uploadCancelled || uploadBatchDone) return;
        uploadCancelled = true;
        btnCancel.disabled = true;
        btnCancel.textContent = "正在取消…";
        try {
          uploadAbort?.abort();
        } catch {
          /* ignore */
        }
      };
    }
  };

  const restoreDropzoneIdle = () => {
    const zone = document.getElementById("kbDropzone");
    if (!zone) return;
    zone.classList.remove("is-uploading", "is-upload-report", "dragover");
    zone.removeAttribute("aria-busy");
    zone.style.pointerEvents = "";
    zone.style.cursor = "pointer";
    zone.innerHTML = dropzoneIdleHtml();
    const btnUpload = document.getElementById("btnAdminUpload");
    if (btnUpload) btnUpload.disabled = false;
    const btnFolder = document.getElementById("btnAdminUploadFolder");
    if (btnFolder) btnFolder.disabled = false;
    wireDropzone();
  };

  const doUploadFile = async (file) => {
    if (!file) throw new Error("请选择文件");
    const fd = new FormData();
    fd.append("file", file);
    const doc = await api.upload(`/knowledge-bases/${kbId}/documents/upload`, fd, {
      signal: uploadAbort?.signal,
    });
    return doc;
  };

  const markRemainingCancelled = () => {
    if (!uploadBatch) return;
    for (const item of uploadBatch) {
      if (item.status === "pending" || item.status === "uploading" || item.status === "processing") {
        item.status = "cancelled";
        item.error = "已取消";
      }
    }
  };

  /** 处理当前批次中 status=pending 的项，并轮询至 ready/error */
  const runPendingUploads = async () => {
    if (!uploadBatch?.length || isUploading) return;
    const pendingCount = uploadBatch.filter((x) => x.status === "pending").length;
    if (!pendingCount) {
      const needPoll = uploadBatch.filter((x) => x.status === "processing" && x.docId);
      if (needPoll.length) {
        isUploading = true;
        uploadBatchDone = false;
        paintDropzoneBatch();
        try {
          await Promise.all(needPoll.map((item) => waitForPipeline(item)));
        } finally {
          uploadBatchDone = true;
          isUploading = false;
          paintDropzoneBatch();
          listPage = 1;
          await renderList();
        }
      } else {
        uploadBatchDone = true;
        paintDropzoneBatch();
      }
      return;
    }
    isUploading = true;
    uploadBatchDone = false;
    uploadCancelled = false;
    uploadAbort = typeof AbortController !== "undefined" ? new AbortController() : null;
    paintDropzoneBatch();
    try {
      for (let i = 0; i < uploadBatch.length; i++) {
        const item = uploadBatch[i];
        if (item.status !== "pending") continue;
        if (uploadCancelled) {
          markRemainingCancelled();
          break;
        }
        item.status = "uploading";
        delete item.error;
        delete item.pipeStatus;
        paintDropzoneBatch();
        try {
          const doc = await doUploadFile(item.file);
          if (uploadCancelled) {
            item.status = "cancelled";
            item.error = "已取消";
          } else {
            item.docId = doc?.id ? String(doc.id) : "";
            item.pipeStatus = String(doc?.status || "uploaded").toLowerCase();
            item.status = "processing";
            delete item.error;
          }
        } catch (e) {
          if (uploadCancelled || e.message === "已取消上传") {
            item.status = "cancelled";
            item.error = "已取消";
            markRemainingCancelled();
            break;
          }
          item.status = "upload_error";
          item.error = e.message || "上传失败";
        }
        paintDropzoneBatch();
      }
      if (uploadCancelled) markRemainingCancelled();
      else {
        const toPoll = uploadBatch.filter((x) => x.status === "processing" && x.docId);
        paintDropzoneBatch();
        await Promise.all(toPoll.map((item) => waitForPipeline(item)));
      }
    } finally {
      uploadBatchDone = true;
      isUploading = false;
      uploadAbort = null;
      paintDropzoneBatch();
      listPage = 1;
      await renderList();
    }
  };

  /** 取消后续传：把目标状态重置为 pending 再跑队列 */
  const resumeUploadBatch = async (fromStatus) => {
    if (!uploadBatch?.length || isUploading) return;
    let reset = 0;
    for (const item of uploadBatch) {
      if (item.status !== fromStatus) continue;
      if (!item.file) {
        item.status = "upload_error";
        item.error = "文件已失效，请重新选择上传";
        continue;
      }
      item.status = "pending";
      delete item.error;
      delete item.docId;
      delete item.pipeStatus;
      reset += 1;
    }
    if (!reset) {
      paintDropzoneBatch();
      return;
    }
    await runPendingUploads();
  };

  /** 失败重试：上传失败重新传文件；处理失败调 retry API 再轮询 */
  const retryFailedUploadItems = async () => {
    if (!uploadBatch?.length || isUploading) return;
    const uploadFails = uploadBatch.filter((x) => x.status === "upload_error");
    const pipeFails = uploadBatch.filter((x) => x.status === "error");
    if (!uploadFails.length && !pipeFails.length) return;

    uploadCancelled = false;
    for (const item of uploadFails) {
      if (!item.file) {
        item.status = "upload_error";
        item.error = "文件已失效，请重新选择上传";
        continue;
      }
      item.status = "pending";
      delete item.error;
      delete item.docId;
      delete item.pipeStatus;
    }

    const hadPending = uploadBatch.some((x) => x.status === "pending");
    if (hadPending) {
      await runPendingUploads();
    }

    const stillPipe = uploadBatch.filter((x) => x.status === "error" && x.docId);
    if (!stillPipe.length || uploadCancelled) {
      paintDropzoneBatch();
      return;
    }

    isUploading = true;
    uploadBatchDone = false;
    paintDropzoneBatch();
    try {
      for (const item of stillPipe) {
        if (uploadCancelled) {
          item.status = "cancelled";
          item.error = "已取消";
          continue;
        }
        item.status = "processing";
        delete item.error;
        paintDropzoneBatch();
        try {
          await api.post(`/knowledge-bases/${kbId}/documents/${item.docId}/retry`, {});
          await waitForPipeline(item);
        } catch (e) {
          item.status = "error";
          item.error = e.message || "重试失败";
        }
        paintDropzoneBatch();
      }
    } finally {
      uploadBatchDone = true;
      isUploading = false;
      paintDropzoneBatch();
      listPage = 1;
      await renderList();
    }
  };

  const doUploadFiles = async (fileListOrCollected) => {
    if (isUploading) return;
    let collected;
    if (Array.isArray(fileListOrCollected) && fileListOrCollected[0]?.file) {
      collected = fileListOrCollected;
    } else {
      collected = collectFromFileList(fileListOrCollected);
    }
    const { files, skipped } = filterUploadableFiles(collected);
    if (!files.length) {
      return toast(
        skipped ? `未找到可上传文件（已跳过 ${skipped} 个无效项）` : "请选择文件或文件夹",
        "error"
      );
    }
    let batch = files;
    if (batch.length > MAX_BATCH_FILES) {
      toast(`单次最多上传 ${MAX_BATCH_FILES} 个，已截取前 ${MAX_BATCH_FILES} 个`, "error");
      batch = batch.slice(0, MAX_BATCH_FILES);
    } else if (skipped) {
      toast(`已跳过 ${skipped} 个不支持或无效文件`, "success");
    }
    uploadBatch = batch.map((x) => ({
      name: x.displayName || x.file.name || "未命名文件",
      file: x.file,
      status: "pending",
    }));
    await runPendingUploads();
  };

  const openDocWorkbench = async (docId, filenameHint) => {
    try {
      const [detail, content, chunksPage] = await Promise.all([
        api.get(`/knowledge-bases/${kbId}/documents/${docId}`).catch(() => null),
        api.get(`/knowledge-bases/${kbId}/documents/${docId}/content`),
        api
          .get(`/knowledge-bases/${kbId}/documents/${docId}/chunks?page=1&page_size=100`)
          .catch(() => ({ items: [], total: 0 })),
      ]);
      let rules = { ...(content.segment_rules || detail?.segment_rules || {}) };
      let chunks = chunksPage.items || [];
      const status = detail?.status || content.status || "-";

      const mask = document.createElement("div");
      mask.className = "modal-mask";
      mask.innerHTML = `
        <div class="modal doc-wb-modal" role="dialog" aria-modal="true">
          <h3 class="modal-title">文档工作台 · ${escapeHtml(filenameHint || content.filename || detail?.filename || "文档")}</h3>
          <div class="modal-body doc-wb-body">
            <p class="text-muted doc-wb-meta">
              状态 <span class="badge">${escapeHtml(status)}</span>
              · 分段 <span id="docWbChunkCount">${escapeHtml(content.chunk_count ?? detail?.chunk_count ?? chunks.length)}</span>
              · 清洗 ${escapeHtml(content.normalized_char_count ?? 0)} 字
              · 原文 ${escapeHtml(content.raw_char_count ?? 0)} 字
              ${content.error_message || detail?.error_message ? ` · <span class="text-danger">${escapeHtml(content.error_message || detail.error_message)}</span>` : ""}
            </p>
            <div class="doc-wb-tabs" role="tablist" aria-label="文档工作台">
              <button type="button" class="btn btn-sm" data-tab="normalized">清洗文档</button>
              <button type="button" class="btn btn-sm btn-secondary" data-tab="raw">文档解析</button>
              <button type="button" class="btn btn-sm btn-secondary" data-tab="chunks">分段详情</button>
              <button type="button" class="btn btn-sm btn-secondary" data-tab="preview">分段效果</button>
              <button type="button" class="btn btn-sm btn-secondary" data-tab="rules">分段规则</button>
            </div>
            <div class="doc-wb-panel">
              <pre id="docPreviewBody" class="doc-wb-pane doc-wb-pane-surface"></pre>
              <div id="docPreviewChunks" class="doc-wb-pane" style="display:none"></div>
              <div id="docPreviewEffect" class="doc-wb-pane doc-wb-pane-surface" style="display:none">
                <p class="text-muted doc-wb-effect-hint" id="docPreviewEffectHint">按当前分段规则干跑预览（未写库）</p>
                <div id="docPreviewDryRunList"><p class="text-muted">加载预览中…</p></div>
              </div>
              <div id="docPreviewRules" class="doc-wb-pane" style="display:none">
                <label class="text-muted">chunk_size（100–5000）</label>
                <input class="form-control" id="ruleSize" type="number" min="100" max="5000" style="margin:6px 0 10px" />
                <label class="text-muted">chunk_overlap（0–1000）</label>
                <input class="form-control" id="ruleOverlap" type="number" min="0" max="1000" style="margin:6px 0 10px" />
                <label class="text-muted">split_mode</label>
                <select class="form-control" id="ruleMode" style="margin:6px 0 10px">
                  <option value="fixed">fixed</option>
                  <option value="sliding">sliding</option>
                  <option value="paragraph">paragraph</option>
                  <option value="heading">heading</option>
                  <option value="markdown">markdown</option>
                </select>
                <label class="text-muted">separators（可选，逗号分隔）</label>
                <input class="form-control" id="ruleSeps" style="margin:6px 0 10px" placeholder="例如 \\n\\n,\\n" />
              </div>
            </div>
          </div>
          <div class="modal-actions doc-wb-actions" id="docWbActions">
            <button type="button" class="btn btn-secondary btn-sm" data-close>关闭</button>
          </div>
        </div>`;
      document.body.appendChild(mask);

      const bodyEl = mask.querySelector("#docPreviewBody");
      const chunksEl = mask.querySelector("#docPreviewChunks");
      const effectEl = mask.querySelector("#docPreviewEffect");
      const effectListEl = mask.querySelector("#docPreviewDryRunList");
      const rulesEl = mask.querySelector("#docPreviewRules");
      const actionsEl = mask.querySelector("#docWbActions");

      const fillRulesForm = () => {
        mask.querySelector("#ruleSize").value = rules.chunk_size ?? 500;
        mask.querySelector("#ruleOverlap").value = rules.chunk_overlap ?? 50;
        mask.querySelector("#ruleMode").value = rules.split_mode || "fixed";
        mask.querySelector("#ruleSeps").value = Array.isArray(rules.separators) ? rules.separators.join(",") : "";
      };
      fillRulesForm();

      const readRulesForm = () => {
        const chunk_size = Number(mask.querySelector("#ruleSize").value);
        const chunk_overlap = Number(mask.querySelector("#ruleOverlap").value);
        const split_mode = mask.querySelector("#ruleMode").value || "fixed";
        const sepsRaw = mask.querySelector("#ruleSeps").value.trim();
        const separators = sepsRaw ? sepsRaw.split(",").map((s) => s.trim()).filter(Boolean) : undefined;
        if (!Number.isFinite(chunk_size) || chunk_size < 100 || chunk_size > 5000) throw new Error("分段长度须在 100–5000");
        if (!Number.isFinite(chunk_overlap) || chunk_overlap < 0 || chunk_overlap > 1000) throw new Error("分段重叠须在 0–1000");
        return { chunk_size, chunk_overlap, split_mode, ...(separators ? { separators } : {}) };
      };

      const renderChunks = () => {
        chunksEl.innerHTML = chunks.length
          ? chunks
              .map((c) => {
                const disabled = c.is_enabled === false;
                return `<div data-chunk-id="${escapeHtml(c.id)}" style="border:1px solid var(--color-border,#e0e0e0);border-radius:8px;padding:10px;margin-bottom:8px;opacity:${disabled ? "0.65" : "1"}">
                  <div style="display:flex;justify-content:space-between;gap:8px;align-items:center;margin-bottom:6px">
                    <div class="text-muted" style="font-size:12px">#${escapeHtml(c.chunk_index)} · ${escapeHtml(c.char_count)} 字${disabled ? " · <span class='badge badge-warning'>不参与检索</span>" : ""}</div>
                    ${canSegment ? `<label style="display:flex;gap:6px;align-items:center;font-size:12px"><input type="checkbox" data-enable-chunk ${c.is_enabled !== false ? "checked" : ""} /> 启用</label>` : ""}
                  </div>
                  ${
                    canSegment
                      ? `<textarea class="form-control" data-chunk-content rows="3" style="font-size:13px;margin-bottom:8px">${escapeHtml(c.content || "")}</textarea>
                         <button type="button" class="btn btn-secondary btn-sm" data-save-chunk>保存分段</button>`
                      : `<div style="white-space:pre-wrap;word-break:break-word;font-size:13px">${escapeHtml(c.content || "")}</div>`
                  }
                </div>`;
              })
              .join("")
          : `<p class="text-muted">暂无分段</p>`;

        chunksEl.querySelectorAll("[data-enable-chunk]").forEach((input) => {
          input.onchange = async () => {
            const card = input.closest("[data-chunk-id]");
            const chunkId = card.getAttribute("data-chunk-id");
            try {
              const updated = await api.put(`/knowledge-bases/${kbId}/documents/${docId}/chunks/${chunkId}`, {
                is_enabled: input.checked,
              });
              const idx = chunks.findIndex((x) => String(x.id) === String(chunkId));
              if (idx >= 0) chunks[idx] = { ...chunks[idx], ...updated };
              toast(input.checked ? "已启用" : "已禁用（不参与检索）", "success");
              renderChunks();
            } catch (e) {
              input.checked = !input.checked;
              toast(e.message || "更新失败", "error");
            }
          };
        });
        chunksEl.querySelectorAll("[data-save-chunk]").forEach((btn) => {
          btn.onclick = async () => {
            const card = btn.closest("[data-chunk-id]");
            const chunkId = card.getAttribute("data-chunk-id");
            const contentText = card.querySelector("[data-chunk-content]")?.value ?? "";
            try {
              await api.put(`/knowledge-bases/${kbId}/documents/${docId}/chunks/${chunkId}`, { content: contentText });
              const idx = chunks.findIndex((x) => String(x.id) === String(chunkId));
              if (idx >= 0) chunks[idx] = { ...chunks[idx], content: contentText };
              toast("分段已保存", "success");
            } catch (e) {
              toast(e.message || "保存失败", "error");
            }
          };
        });
      };
      renderChunks();

      const loadSegmentPreview = async () => {
        effectListEl.innerHTML = `<p class="text-muted">加载预览中…</p>`;
        try {
          const body = readRulesForm();
          const preview = await api.post(`/knowledge-bases/${kbId}/documents/${docId}/segment-preview`, body);
          effectListEl.innerHTML = `<p class="text-muted">共 ${escapeHtml(preview.total_chunks ?? 0)} 段（未写库）</p>${(preview.chunks || [])
            .slice(0, 50)
            .map(
              (c) => `<div style="border:1px solid var(--color-border);border-radius:6px;padding:8px;margin-bottom:6px;font-size:12px">
                <div class="text-muted">#${escapeHtml(c.chunk_index)} · ${escapeHtml(c.char_count)} 字</div>
                <div style="white-space:pre-wrap">${escapeHtml((c.content || "").slice(0, 400))}</div>
              </div>`
            )
            .join("")}`;
        } catch (e) {
          effectListEl.innerHTML = `<p class="text-danger">${escapeHtml(e.message || "预览失败")}</p>`;
        }
      };

      const wireActionButtons = () => {
        const btnNormalize = mask.querySelector("#btnNormalize");
        if (btnNormalize) {
          btnNormalize.onclick = async () => {
            try {
              const result = await api.post(`/knowledge-bases/${kbId}/documents/${docId}/normalize`, {});
              toast(
                `规范化完成：删空行 ${result.removed_blank_lines ?? 0} · 删重复块 ${result.removed_duplicate_blocks ?? 0}`,
                "success"
              );
              mask.remove();
              openDocWorkbench(docId, filenameHint);
              renderList();
            } catch (e) {
              toast(e.message || "规范化失败", "error");
            }
          };
        }
        const btnSaveRules = mask.querySelector("#btnSaveRules");
        if (btnSaveRules) {
          btnSaveRules.onclick = async () => {
            try {
              const body = readRulesForm();
              const doc = await api.put(`/knowledge-bases/${kbId}/documents/${docId}/segment-rules`, body);
              rules = { ...(doc.segment_rules || body) };
              fillRulesForm();
              toast("分段规则已保存（未重分段）", "success");
            } catch (e) {
              toast(e.message || "保存失败", "error");
            }
          };
        }
        const btnResegment = mask.querySelector("#btnResegment");
        if (btnResegment) {
          btnResegment.onclick = async () => {
            const ok = await confirmDialog({
              title: "重新分段",
              message: "将按当前规则重新分段并向量化，可能耗时较长。确定继续？",
              confirmText: "重分段",
            });
            if (!ok) return;
            try {
              const body = readRulesForm();
              await api.put(`/knowledge-bases/${kbId}/documents/${docId}/segment-rules`, body);
              await api.post(`/knowledge-bases/${kbId}/documents/${docId}/re-segment`, {});
              toast("已提交重分段任务", "success");
              mask.remove();
              renderList();
            } catch (e) {
              toast(e.message || "重分段失败", "error");
            }
          };
        }
        const closeBtn = mask.querySelector("[data-close]");
        if (closeBtn) closeBtn.onclick = () => mask.remove();
      };

      const renderActions = (tab) => {
        const parts = [];
        if (tab === "normalized" && canWrite) {
          parts.push(`<button type="button" class="btn btn-secondary btn-sm" id="btnNormalize">规范化</button>`);
        }
        if (tab === "rules" && canSegment) {
          parts.push(`<button type="button" class="btn btn-success btn-sm" id="btnSaveRules">保存规则</button>`);
          parts.push(`<button type="button" class="btn btn-primary btn-sm" id="btnResegment">重新分段并向量化</button>`);
        }
        parts.push(`<button type="button" class="btn btn-danger btn-sm" data-close>关闭</button>`);
        actionsEl.innerHTML = parts.join("");
        wireActionButtons();
      };

      const setActiveTab = (tab) => {
        mask.querySelectorAll("[data-tab]").forEach((b) => {
          b.className = b.getAttribute("data-tab") === tab ? "btn btn-sm" : "btn btn-sm btn-secondary";
        });
        bodyEl.style.display = tab === "normalized" || tab === "raw" ? "block" : "none";
        chunksEl.style.display = tab === "chunks" ? "block" : "none";
        effectEl.style.display = tab === "preview" ? "block" : "none";
        rulesEl.style.display = tab === "rules" ? "block" : "none";
        if (tab === "raw") bodyEl.textContent = content.raw_text || "（无原文）";
        else if (tab === "normalized") bodyEl.textContent = content.normalized_text || content.raw_text || "（无内容）";
        if (tab === "preview") loadSegmentPreview();
        renderActions(tab);
      };
      bodyEl.textContent = content.normalized_text || content.raw_text || "（无内容）";
      mask.querySelectorAll("[data-tab]").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          setActiveTab(btn.getAttribute("data-tab"));
        });
      });

      setActiveTab("normalized");

      mask.addEventListener("click", (e) => {
        if (e.target === mask) mask.remove();
      });
    } catch (e) {
      toast(e.message || "打开文档工作台失败", "error");
    }
  };

  const wireDropzone = () => {
    const zone = document.getElementById("kbDropzone");
    const fileInput = document.getElementById("adminFile");
    const folderInput = document.getElementById("adminFolder");
    if (!zone || !fileInput || !canUpload) return;

    const pickFromInput = (input) => {
      if (!input) return;
      input.onchange = () => {
        if (isUploading) {
          input.value = "";
          return;
        }
        if (input.files?.length) {
          doUploadFiles(input.files);
          input.value = "";
        }
      };
    };
    pickFromInput(fileInput);
    pickFromInput(folderInput);

    if (uploadBatch?.length && (uploadBatchDone || isUploading)) {
      paintDropzoneBatch();
      return;
    }

    zone.removeAttribute("aria-hidden");
    zone.removeAttribute("aria-busy");
    zone.classList.remove("is-uploading", "is-upload-report", "dragover");
    zone.style.cursor = "pointer";
    zone.style.pointerEvents = "";
    let dragDepth = 0;
    const setDragActive = (on) => {
      zone.classList.toggle("dragover", on);
      zone.setAttribute("aria-dropeffect", on ? "copy" : "none");
    };
    zone.onclick = () => {
      if (isUploading) return;
      fileInput.click();
    };
    zone.addEventListener("dragenter", (e) => {
      if (isUploading) return;
      e.preventDefault();
      dragDepth += 1;
      setDragActive(true);
    });
    zone.addEventListener("dragover", (e) => {
      if (isUploading) return;
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
      setDragActive(true);
    });
    zone.addEventListener("dragleave", () => {
      dragDepth = Math.max(0, dragDepth - 1);
      if (dragDepth === 0) setDragActive(false);
    });
    zone.addEventListener("drop", async (e) => {
      e.preventDefault();
      dragDepth = 0;
      setDragActive(false);
      if (isUploading) return;
      try {
        const collected = await collectFromDataTransfer(e.dataTransfer);
        await doUploadFiles(collected);
      } catch (err) {
        toast(err.message || "读取拖拽内容失败", "error");
      }
    });
  };

  const renderList = async () => {
    try {
      const data = await api.get(
        `/knowledge-bases/${kbId}/documents?page=${listPage}&page_size=${DOC_PAGE_SIZE}`
      );
      const items = data.items || [];
      const total = Number(data.total ?? items.length) || 0;
      const totalPages = Math.max(1, Math.ceil(total / DOC_PAGE_SIZE) || 1);
      if (listPage > totalPages) {
        listPage = totalPages;
        return renderList();
      }
      const busy = items.some((d) => DOC_BUSY_STATUSES.has(String(d.status || "")));
      if (refreshTimer) {
        clearTimeout(refreshTimer);
        refreshTimer = null;
      }
      if (busy) {
        refreshTimer = setTimeout(() => {
          if (embedded ? isKbDocsView(kbId) : currentPath().includes(`/knowledge-bases/${kbId}/documents`)) renderList();
        }, 4000);
      }

      const { buttons: pageButtons, jump: pageJump } = renderCompactPagerParts(listPage, totalPages);

      const selectableCount = items.filter((d) => !DOC_BUSY_STATUSES.has(String(d.status || ""))).length;

      const docActions = canUpload
        ? `<input type="file" id="adminFile" class="hidden" multiple accept=".pdf,.doc,.docx,.txt,.md,text/markdown,application/pdf" />
                 <input type="file" id="adminFolder" class="hidden" webkitdirectory directory multiple />
                 <button class="btn btn-sm" id="btnAdminUpload">选择文件</button>
                 <button class="btn btn-secondary btn-sm" id="btnAdminUploadFolder">选择文件夹</button>`
        : "";

      mountEl().innerHTML = `
      ${pageHead({
        title: "文档管理",
        desc: "支持 PDF、Word（DOC/DOCX）、TXT、Markdown；可拖拽文件/文件夹。上传后仍会解析与向量化；处理失败会留在列表并可重试。",
        actions: docActions,
      })}
      ${
        canUpload
          ? `<div class="kb-dropzone" id="kbDropzone">${dropzoneIdleHtml()}
        </div>`
          : ""
      }
      <div class="card panel-fill">
        <div class="card-header">
          <div class="card-header-text">
            <h3 class="card-title">文档列表</h3>
            <p class="card-sub">分段 / 预处理 / 向量化状态 · 共 ${total} 份 · 第 ${listPage}/${totalPages} 页${busy ? " · 处理中自动刷新" : ""}</p>
          </div>
        </div>
        <div class="table-wrap"><table class="table table-docs">
          <colgroup>
            ${canWrite ? `<col class="docs-col-check" />` : ""}
            <col class="docs-col-index" />
            <col class="docs-col-time" />
            <col class="docs-col-name" />
            <col class="docs-col-size" />
            <col class="docs-col-num" />
            <col class="docs-col-status" />
            <col class="docs-col-actions" />
          </colgroup>
          <thead><tr>
            ${canWrite ? `<th class="col-check"><input type="checkbox" id="docSelectAll" title="全选当前页" aria-label="全选当前页" ${selectableCount ? "" : "disabled"} /></th>` : ""}
            <th class="col-index">序号</th>
            <th class="col-time">上传时间</th>
            <th class="col-name">文件名</th>
            <th class="col-size">大小</th>
            <th class="col-num">分段</th>
            <th class="col-status">状态</th>
            <th class="col-actions">操作</th>
          </tr></thead>
          <tbody>
            ${items
              .map((d, i) => {
                const st = String(d.status || "");
                const isError = st === "error";
                const isBusy = DOC_BUSY_STATUSES.has(st);
                const seq = (listPage - 1) * DOC_PAGE_SIZE + i + 1;
                return `<tr>
                  ${
                    canWrite
                      ? `<td class="col-check"><input type="checkbox" class="doc-row-check" value="${escapeHtml(d.id)}" ${isBusy ? "disabled" : ""} aria-label="选择 ${escapeHtml(d.filename || d.name || "文档")}" /></td>`
                      : ""
                  }
                  <td class="col-index">${seq}</td>
                  <td class="col-time">${formatDateTimeHtml(d.created_at)}</td>
                  <td class="col-name"><span class="cell-primary">${escapeHtml(d.filename || d.name)}</span></td>
                  <td class="col-size">${escapeHtml(formatSize(d.file_size ?? d.size))}</td>
                  <td class="col-num">${escapeHtml(d.chunk_count ?? 0)}</td>
                  <td class="col-status">${docStatusBadge(st)}${
                    isError && d.error_message
                      ? `<div class="text-danger" style="font-size:12px;margin-top:4px;line-height:1.35;max-width:9.5rem;margin-inline:auto;word-break:break-word">${escapeHtml(String(d.error_message).slice(0, 100))}</div>`
                      : ""
                  }</td>
                  <td class="col-actions">
                    <div class="table-actions">
                      <button class="btn btn-secondary btn-sm" data-preview="${escapeHtml(d.id)}" data-name="${escapeHtml(d.filename || "")}">文档处理</button>
                      ${canWrite && !isBusy ? `<button class="btn btn-danger btn-sm" data-del="${escapeHtml(d.id)}">删除</button>` : ""}
                      ${canWrite && isError && !isBusy ? `<button class="btn btn-sm" data-retry="${escapeHtml(d.id)}">重试</button>` : ""}
                    </div>
                  </td>
                </tr>`;
              })
              .join("") ||
              `<tr><td colspan="${canWrite ? 8 : 7}" class="text-muted">暂无文档</td></tr>`}
          </tbody>
        </table></div>
        <div class="table-card-footer">
          <div class="table-card-footer-start">
            ${
              canWrite
                ? `<button type="button" class="btn btn-danger btn-sm" id="btnBatchDeleteDocs" disabled>批量删除</button>`
                : ""
            }
          </div>
          ${
            total > 0
              ? `<div class="pager pager-center" id="docPager">
                <button type="button" class="btn btn-secondary btn-sm" data-page-prev ${listPage <= 1 ? "disabled" : ""}>上一页</button>
                ${pageButtons}
                <button type="button" class="btn btn-secondary btn-sm" data-page-next ${listPage >= totalPages ? "disabled" : ""}>下一页</button>
                ${pageJump}
              </div>`
              : ""
          }
        </div>
      </div>`;

      document.querySelectorAll("[data-go]").forEach((b) => b.addEventListener("click", () => navigate(b.getAttribute("data-go"))));
      wireDropzone();

      const syncBatchDeleteState = () => {
        const btn = document.getElementById("btnBatchDeleteDocs");
        const selectAll = document.getElementById("docSelectAll");
        const checks = Array.from(document.querySelectorAll(".doc-row-check:not(:disabled)"));
        const selected = checks.filter((c) => c.checked);
        if (btn) btn.disabled = selected.length === 0;
        if (selectAll && checks.length) {
          selectAll.checked = selected.length === checks.length;
          selectAll.indeterminate = selected.length > 0 && selected.length < checks.length;
        } else if (selectAll) {
          selectAll.checked = false;
          selectAll.indeterminate = false;
        }
      };

      const selectAll = document.getElementById("docSelectAll");
      if (selectAll) {
        selectAll.onchange = () => {
          document.querySelectorAll(".doc-row-check:not(:disabled)").forEach((cb) => {
            cb.checked = selectAll.checked;
          });
          syncBatchDeleteState();
        };
      }
      document.querySelectorAll(".doc-row-check").forEach((cb) => {
        cb.onchange = () => syncBatchDeleteState();
      });

      const btnBatch = document.getElementById("btnBatchDeleteDocs");
      if (btnBatch) {
        btnBatch.onclick = async () => {
          const ids = Array.from(document.querySelectorAll(".doc-row-check:checked")).map((el) => el.value);
          if (!ids.length) return toast("请先勾选要删除的文档", "error");
          const ok = await confirmDialog({
            title: "批量删除文档",
            message: `将删除已勾选的 ${ids.length} 份文档及其向量数据，确定？`,
            confirmText: "批量删除",
          });
          if (!ok) return;
          let success = 0;
          const failures = [];
          for (const id of ids) {
            try {
              await api.delete(`/knowledge-bases/${kbId}/documents/${id}`);
              success += 1;
            } catch (e) {
              failures.push(e.message || "删除失败");
            }
          }
          if (success && !failures.length) {
            toast(`已删除 ${success} 份文档`, "success");
          } else if (success && failures.length) {
            toast(`成功 ${success} 份，失败 ${failures.length} 份：${failures[0]}`, "error");
          } else {
            toast(failures[0] || "批量删除失败", "error");
          }
          await renderList();
        };
      }

      const pager = document.getElementById("docPager");
      if (pager) {
        bindCompactPager(pager, {
          page: listPage,
          totalPages,
          onGo: (p) => {
            listPage = p;
            renderList();
          },
        });
      }

      const btnUpload = document.getElementById("btnAdminUpload");
      if (btnUpload) btnUpload.onclick = () => document.getElementById("adminFile")?.click();
      const btnFolder = document.getElementById("btnAdminUploadFolder");
      if (btnFolder) btnFolder.onclick = () => document.getElementById("adminFolder")?.click();

      document.querySelectorAll("[data-preview]").forEach((btn) => {
        btn.onclick = () => openDocWorkbench(btn.getAttribute("data-preview"), btn.getAttribute("data-name"));
      });
      document.querySelectorAll("[data-retry]").forEach((btn) => {
        btn.onclick = async () => {
          try {
            await api.post(`/knowledge-bases/${kbId}/documents/${btn.getAttribute("data-retry")}/retry`, {});
            toast("已提交重试", "success");
            renderList();
          } catch (e) {
            toast(e.message || "重试失败", "error");
          }
        };
      });
      document.querySelectorAll("[data-del]").forEach((btn) => {
        btn.onclick = async () => {
          const ok = await confirmDialog({ title: "删除文档", message: "将删除文档及其向量数据，确定？", confirmText: "删除" });
          if (!ok) return;
          try {
            await api.delete(`/knowledge-bases/${kbId}/documents/${btn.getAttribute("data-del")}`);
            toast("已删除", "success");
            renderList();
          } catch (e) {
            toast(e.message || "删除失败", "error");
          }
        };
      });
      syncBatchDeleteState();
    } catch (e) {
      mountEl().innerHTML = `<div class="card text-danger">${escapeHtml(e.message)}</div>`;
    }
  };

  await renderList();
}

/* ========== 快照管理（产品手册 5.8） ========== */
const SNAPSHOT_TRIGGER_LABELS = {
  manual: "手动创建",
  auto_upload: "上传前自动",
  auto_delete: "删除前自动",
  auto_resegment: "重分段前自动",
  auto_revectorize: "重向量化前自动",
  auto_permission: "权限变更前自动",
  auto_segment_rules: "分段规则变更前自动",
  auto_normalize: "规范化前自动",
  rollback_protection: "回退保护",
};

const SNAPSHOT_CHANGE_LABELS = {
  added: "将恢复",
  removed: "不在快照中",
  modified: "内容有差异",
  unchanged: "无变化",
};

const CONFIG_FIELD_LABELS = {
  name: "知识库名称",
  chunk_size: "分段长度",
  chunk_overlap: "分段重叠",
  embedding_model: "嵌入模型",
  visibility: "可见性",
  permissions: "权限配置",
};

/** 宽弹窗（快照详情 / 差异预览）；确认时不自动卸载，便于读取表单。 */
function openWideModal({ title, bodyHtml, actionsHtml, width = "min(760px,calc(100vw - 24px))", panelClass = "", onReady = null }) {
  return new Promise((resolve) => {
    const mask = document.createElement("div");
    mask.className = "modal-mask";
    const extra = panelClass ? ` ${panelClass}` : "";
    mask.innerHTML = `
      <div class="modal${extra}" role="dialog" aria-modal="true" style="width:${width};max-height:85vh;overflow:auto">
        <h3 class="modal-title">${escapeHtml(title)}</h3>
        <div class="modal-body">${bodyHtml}</div>
        <div class="modal-actions">${actionsHtml}</div>
      </div>`;
    mask.addEventListener("click", (e) => {
      const act = e.target.getAttribute?.("data-act");
      if (!act) return;
      if (act === "cancel") {
        mask.remove();
        resolve(null);
        return;
      }
      if (act === "ok") {
        resolve({ ok: true, root: mask });
      }
    });
    document.body.appendChild(mask);
    try {
      onReady?.(mask);
    } catch (_) {
      /* ignore mount hooks */
    }
  });
}

async function pageSnapshots(kbId, opts = {}) {
  const { embedded = false, mountId = "pageRoot" } = opts;
  if (!embedded && !requirePerm("snapshot:read", "快照管理")) return;
  const mountEl = () => document.getElementById(mountId);
  const canWrite = hasPermission("snapshot:write");
  const canRestore = hasPermission("snapshot:restore");
  mountEl().innerHTML = `<div class="loading">加载快照…</div>`;

  const triggerBadge = (trigger) => {
    const label = SNAPSHOT_TRIGGER_LABELS[trigger] || trigger || "-";
    const cls =
      trigger === "rollback_protection"
        ? "badge badge-warning"
        : trigger === "manual"
          ? "badge badge-success"
          : "badge";
    return `<span class="${cls}">${escapeHtml(label)}</span>`;
  };

  /** 快照名称：括号段单独换行，避免窄列中被拆断 */
  const formatSnapNameHtml = (name) => {
    const raw = String(name || "-").trim() || "-";
    const m = raw.match(/^(.+?)\s*([（(].+)$/);
    if (m) {
      return `<strong class="cell-primary snap-name-stack" title="${escapeHtml(raw)}"><span class="snap-name-main">${escapeHtml(
        m[1].trim()
      )}</span><span class="snap-name-sub">${escapeHtml(m[2].trim())}</span></strong>`;
    }
    return `<strong class="cell-primary" title="${escapeHtml(raw)}">${escapeHtml(raw)}</strong>`;
  };

  const renderList = async () => {
    const data = await api.get(`/knowledge-bases/${kbId}/snapshots?page=1&page_size=50`);
    const items = data.items || [];
    mountEl().innerHTML = `
      ${pageHead({
        title: "快照管理",
        desc: "变更前自动留存；回退前强制生成保护快照。默认最多保留 50 份 / 90 天。",
        actions: `
          ${
            canWrite
              ? `<button class="btn btn-sm" id="btnCreateSnap">手动创建快照</button>
                 <button class="btn btn-secondary btn-sm" id="btnCleanupSnap">策略清理</button>`
              : ""
          }
        `,
      })}
      <div class="card panel-fill">
        <div class="card-header">
          <div class="card-header-text">
            <h3 class="card-title">历史快照与回退</h3>
            <p class="card-sub">共 ${items.length} 份</p>
          </div>
        </div>
        ${
          items.length
            ? `<div class="table-wrap"><table class="table table-snapshots">
          <colgroup>
            <col class="snap-col-time" />
            <col class="snap-col-name" />
            <col class="snap-col-trigger" />
            <col class="snap-col-num" />
            <col class="snap-col-num" />
            <col class="snap-col-desc" />
            <col class="snap-col-actions" />
          </colgroup>
          <thead><tr>
            <th class="col-time">创建时间</th>
            <th class="col-name">快照名称</th>
            <th class="col-trigger">触发方式</th>
            <th class="col-num">文档数</th>
            <th class="col-num">分段数</th>
            <th class="col-desc">说明</th>
            <th class="col-actions">操作</th>
          </tr></thead>
          <tbody>
            ${items
              .map((s) => {
                const isProtection = s.trigger === "rollback_protection";
                const ops = [
                  `<button type="button" class="btn btn-text btn-sm" data-detail="${escapeHtml(s.id)}">详情</button>`,
                  canRestore
                    ? `<button type="button" class="btn btn-secondary btn-sm" data-preview="${escapeHtml(s.id)}">预览/回退</button>`
                    : "",
                  canWrite && !isProtection
                    ? `<button type="button" class="btn btn-danger btn-sm" data-del="${escapeHtml(s.id)}">删除</button>`
                    : isProtection
                      ? `<span class="text-muted" title="保护快照不可手动删除">不可删</span>`
                      : "",
                ].filter(Boolean);
                return `<tr>
                  <td class="col-time">${formatDateTimeHtml(s.created_at)}</td>
                  <td class="col-name">${formatSnapNameHtml(s.name)}</td>
                  <td class="col-trigger">${triggerBadge(s.trigger)}</td>
                  <td class="col-num">${escapeHtml(s.document_count ?? 0)}</td>
                  <td class="col-num">${escapeHtml(s.total_chunks ?? 0)}</td>
                  <td class="col-desc">${escapeHtml(s.description || "—")}</td>
                  <td class="col-actions"><div class="table-actions">${ops.join("")}</div></td>
                </tr>`;
              })
              .join("")}
          </tbody>
        </table></div>`
            : `<div class="empty-state">暂无快照。上传/删除文档或点击「手动创建快照」后会出现记录。</div>`
        }
      </div>`;

    document.querySelectorAll("[data-go]").forEach((b) =>
      b.addEventListener("click", () => navigate(b.getAttribute("data-go")))
    );

    const btnCreate = document.getElementById("btnCreateSnap");
    if (btnCreate) {
      btnCreate.onclick = async () => {
        const result = await openWideModal({
          title: "手动创建快照",
          bodyHtml: `
            <p class="text-muted">建议在重大发布、批量重分段或权限调整前手工命名备份，便于事后按名称定位。</p>
            <label class="text-muted">快照名称</label>
            <input class="form-control" id="snapName" maxlength="200" placeholder="例如：上线前备份-2026Q3" style="margin:6px 0 12px" />
            <label class="text-muted">说明（可选）</label>
            <textarea class="form-control" id="snapDesc" rows="3" maxlength="2000" placeholder="记录创建原因，如：客服 FAQ 改版前"></textarea>`,
          actionsHtml: `
            <button type="button" class="btn btn-secondary" data-act="cancel">取消</button>
            <button type="button" class="btn" data-act="ok">创建</button>`,
        });
        if (!result) return;
        const name = result.root.querySelector("#snapName")?.value?.trim();
        const description = result.root.querySelector("#snapDesc")?.value?.trim() || undefined;
        result.root.remove();
        if (!name) {
          toast("请填写快照名称", "error");
          return;
        }
        try {
          await api.post(`/knowledge-bases/${kbId}/snapshots`, { name, description });
          toast("快照已创建", "success");
          await renderList();
        } catch (e) {
          toast(e.message || "创建失败", "error");
        }
      };
    }

    const btnCleanup = document.getElementById("btnCleanupSnap");
    if (btnCleanup) {
      btnCleanup.onclick = async () => {
        const ok = await confirmDialog({
          title: "策略清理快照",
          message: "将按默认策略清理：超过 90 天的快照，以及超出 50 条上限的最早非保护快照。确定继续？",
          confirmText: "开始清理",
        });
        if (!ok) return;
        try {
          const res = await api.post(`/knowledge-bases/${kbId}/snapshots/cleanup`, {});
          toast(
            `清理完成：过期 ${res?.expired_deleted ?? 0}，超额 ${res?.excess_deleted ?? 0}，剩余 ${res?.active_remaining ?? "-"}`,
            "success"
          );
          await renderList();
        } catch (e) {
          toast(e.message || "清理失败", "error");
        }
      };
    }

    document.querySelectorAll("[data-detail]").forEach((btn) => {
      btn.onclick = async () => {
        const sid = btn.getAttribute("data-detail");
        try {
          const d = await api.get(`/knowledge-bases/${kbId}/snapshots/${sid}`);
          const docs = d.documents || [];
          const rules = d.segment_rules || {};
          const perms = d.permission_snapshot || [];
          await openWideModal({
            title: `快照详情 · ${d.name || ""}`,
            bodyHtml: `
              <p><span class="text-muted">触发方式：</span>${triggerBadge(d.trigger)}
                <span class="text-muted" style="margin-left:12px">创建时间：</span>${formatDateTime(d.created_at)}</p>
              <p class="text-muted">${escapeHtml(d.description || "无说明")}</p>
              <h4 style="margin:14px 0 8px;font-size:14px">分段规则</h4>
              <p>分段长度 <code>${escapeHtml(rules.chunk_size ?? "-")}</code> · 重叠
                <code>${escapeHtml(rules.chunk_overlap ?? "-")}</code></p>
              <h4 style="margin:14px 0 8px;font-size:14px">权限配置（${perms.length} 条）</h4>
              ${
                perms.length
                  ? `<ul class="list-plain">${perms
                      .slice(0, 20)
                      .map(
                        (p) =>
                          `<li><code>${escapeHtml(p.permission_code || "-")}</code>
                            ${p.user_id ? ` · 用户 ${escapeHtml(String(p.user_id).slice(0, 8))}…` : ""}
                            ${p.role_id ? ` · 角色 ${escapeHtml(String(p.role_id).slice(0, 8))}…` : ""}</li>`
                      )
                      .join("")}${perms.length > 20 ? "<li>…</li>" : ""}</ul>`
                  : `<p class="text-muted">快照时无独立权限授予</p>`
              }
              <h4 style="margin:14px 0 8px;font-size:14px">文档清单（${docs.length}）</h4>
              <div class="table-wrap"><table class="table">
                <thead><tr><th>文件名</th><th>类型</th><th>分段数</th><th>状态</th></tr></thead>
                <tbody>${
                  docs.length
                    ? docs
                        .map(
                          (doc) => `<tr>
                          <td>${escapeHtml(doc.filename)}</td>
                          <td>${escapeHtml(doc.file_type || "-")}</td>
                          <td>${escapeHtml(doc.chunk_count ?? 0)}</td>
                          <td>${escapeHtml((doc.metadata && doc.metadata.status) || "-")}</td>
                        </tr>`
                        )
                        .join("")
                    : `<tr><td colspan="4" class="text-muted">无文档</td></tr>`
                }</tbody>
              </table></div>`,
            actionsHtml: `<button type="button" class="btn btn-secondary" data-act="cancel">关闭</button>`,
          });
        } catch (e) {
          toast(e.message || "加载详情失败", "error");
        }
      };
    });

    document.querySelectorAll("[data-preview]").forEach((btn) => {
      btn.onclick = async () => {
        const sid = btn.getAttribute("data-preview");
        try {
          const preview = await api.post(`/knowledge-bases/${kbId}/snapshots/${sid}/preview`, {});
          const affected = (preview.affected_documents || []).filter((a) => a.change_type !== "unchanged");
          const configChanges = preview.config_changes || [];
          const result = await openWideModal({
            title: `回退差异预览 · ${preview.snapshot_name || ""}`,
            width: "min(900px,calc(100vw - 24px))",
            bodyHtml: `
              <p class="text-muted">将影响 <strong>${escapeHtml(preview.total_changes ?? affected.length)}</strong> 份文档；
                回退前会自动创建保护快照；确认后仅恢复元数据并生成 <code>building</code> 索引，向量重建完成后才会原子切换。</p>
              ${
                configChanges.length
                  ? `<h4 style="margin:12px 0 8px;font-size:14px">配置差异</h4>
                    <ul class="list-plain">${configChanges
                      .map(
                        (c) =>
                          `<li>${escapeHtml(CONFIG_FIELD_LABELS[c.field] || c.field)}：
                            <code>${escapeHtml(JSON.stringify(c.current))}</code>
                            → <code>${escapeHtml(JSON.stringify(c.snapshot))}</code></li>`
                      )
                      .join("")}</ul>`
                  : `<p class="text-muted">配置项与当前一致</p>`
              }
              <h4 style="margin:12px 0 8px;font-size:14px">文档变更（可勾选做选择性恢复）</h4>
              <p class="text-muted" style="margin:0 0 8px;font-size:12px">勾选下方文档可做选择性恢复（不改整库配置/权限）；不勾选则整库回退。</p>
              <div class="table-wrap"><table class="table table-snap-preview">
                <thead><tr><th class="col-check">选用</th><th>变更</th><th class="col-name">文件名</th><th>当前分段</th><th>快照分段</th><th class="col-desc">说明</th></tr></thead>
                <tbody>${
                  (preview.affected_documents || []).length
                    ? (preview.affected_documents || [])
                        .map((a) => {
                          // 选择性恢复只能勾选快照内文档（added/modified/unchanged）；removed 仅整库回退时归档
                          const inSnapshot = a.change_type !== "removed";
                          return `<tr>
                            <td class="col-check">${
                              inSnapshot
                                ? `<input type="checkbox" class="snap-doc" value="${escapeHtml(a.document_id)}" aria-label="选择 ${escapeHtml(a.filename || "文档")}" />`
                                : `<span class="text-muted snap-doc-na" title="该文件不在此快照中，不能单独勾选；仅整库回退时才会从当前库移出（软归档）">不可选</span>`
                            }</td>
                            <td><span class="badge ${
                              a.change_type === "removed"
                                ? "badge-danger"
                                : a.change_type === "added"
                                  ? "badge-success"
                                  : a.change_type === "modified"
                                    ? "badge-warning"
                                    : ""
                            }" title="${
                              a.change_type === "removed"
                                ? "当前库有此文件，快照里没有；整库回退后会从当前库移出（软归档）"
                                : a.change_type === "added"
                                  ? "快照里有、当前库没有；回退后会恢复该文件"
                                  : a.change_type === "modified"
                                    ? "两边都有，但内容/分段不一致；回退后按快照覆盖"
                                    : ""
                            }">${escapeHtml(SNAPSHOT_CHANGE_LABELS[a.change_type] || a.change_type)}</span></td>
                            <td class="col-name">${escapeHtml(a.filename)}</td>
                            <td>${escapeHtml(a.current_chunk_count ?? "—")}</td>
                            <td>${escapeHtml(a.snapshot_chunk_count ?? "—")}</td>
                            <td class="col-desc text-muted">${escapeHtml(a.detail || "")}</td>
                          </tr>`;
                        })
                        .join("")
                    : `<tr><td colspan="6" class="text-muted">与当前状态无差异</td></tr>`
                }</tbody>
              </table></div>
              <p style="margin-top:12px;color:var(--color-danger)">二次确认后不可撤销为「覆盖原历史」；如需撤销回退，可再回退到刚生成的保护快照。</p>`,
            actionsHtml: `
              <button type="button" class="btn btn-secondary" data-act="cancel">取消</button>
              ${
                canRestore
                  ? `<button type="button" class="btn btn-danger" data-act="ok">确认回退</button>`
                  : ""
              }`,
          });
          if (!result || !canRestore) {
            if (result?.root) result.root.remove();
            return;
          }
          const checkedIds = [...result.root.querySelectorAll(".snap-doc:checked")].map((el) => el.value);
          const selective = checkedIds.length > 0;
          const document_ids = selective ? checkedIds : undefined;
          result.root.remove();
          const ok = await confirmDialog({
            title: "二次确认回退",
            message: selective
              ? `将仅恢复已选 ${document_ids.length} 份文档，并创建回退前保护快照。确定继续？`
              : "将整库恢复到该快照（含配置/权限），快照外文档将软归档，并创建回退前保护快照。确定继续？",
            confirmText: "确认回退",
            danger: true,
          });
          if (!ok) return;
          const body = { confirm: true };
          if (document_ids) body.document_ids = document_ids;
          const res = await api.post(`/knowledge-bases/${kbId}/snapshots/${sid}/rollback`, body);
          toast(
            res?.message ||
              `回退已受理：新索引 ${res?.new_index_version || ""}（${res?.index_status || "building"}）`,
            "success"
          );
          await renderList();
        } catch (e) {
          toast(e.message || "预览/回退失败", "error");
        }
      };
    });

    document.querySelectorAll("[data-del]").forEach((btn) => {
      btn.onclick = async () => {
        const sid = btn.getAttribute("data-del");
        const ok = await confirmDialog({
          title: "删除快照",
          message: "删除后列表中不再展示该快照（软删除）。回退保护快照不可删。确定删除？",
          confirmText: "删除",
          danger: true,
        });
        if (!ok) return;
        try {
          await api.delete(`/knowledge-bases/${kbId}/snapshots/${sid}`);
          toast("快照已删除", "success");
          await renderList();
        } catch (e) {
          toast(e.message || "删除失败", "error");
        }
      };
    });
  };

  try {
    await renderList();
  } catch (e) {
    mountEl().innerHTML = `<div class="card text-danger">${escapeHtml(e.message)}</div>`;
  }
}

/* ========== 命中率测试 ========== */
async function pageHitTest() {
  if (!requirePerm("test:read", "命中率测试")) return;
  const canWrite = hasPermission("test:write");
  document.getElementById("pageRoot").innerHTML = `<div class="loading">加载测试数据…</div>`;

  const pct = (v) => {
    if (v == null || Number.isNaN(Number(v))) return "-";
    return `${Math.round(Number(v) * 1000) / 10}%`;
  };

  const strategyLabel = (s) =>
    ({ vector: "向量", fulltext: "全文", hybrid: "混合" }[s] || s || "-");

  const HT_DETAIL_RUN_KEY = "htLastDetailRunId";

  const loadRunDetail = async (runId) => {
    const detail = await api.get(`/hit-tests/runs/${runId}`);
    return {
      runId: String(runId),
      summary: detail.summary || detail,
      results: detail.results || [],
    };
  };

  const exportRunCsv = async (runId) => {
    const { getAccessToken } = await import("/assets/js/auth.js?v=gap-opt-0721s");
    const res = await fetch(`/api/v1/hit-tests/runs/${runId}/export`, {
      headers: { Authorization: `Bearer ${getAccessToken()}` },
    });
    if (!res.ok) throw new Error(await res.text());
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `hit_test_run_${runId}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const formatRunSummaryLine = (summary) =>
    `策略 ${escapeHtml(strategyLabel(summary.strategy))} · TopK ${escapeHtml(summary.top_k)} · 命中 ${escapeHtml(summary.hit_count)}/${escapeHtml(summary.total_questions)} · 命中率 ${pct(summary.hit_rate ?? summary.recall_at_k)} · 得分（相关度）${pct(summary.score)} · MRR ${summary.mrr != null ? Number(summary.mrr).toFixed(3) : "-"} · 均耗时 ${summary.avg_elapsed_ms != null ? Math.round(summary.avg_elapsed_ms) + "ms" : "-"}`;

  const recallTipOf = (chunks) =>
    (chunks || [])
      .slice(0, 2)
      .map((c) => escapeHtml(`${c.doc_name || c.doc_id || ""}#${c.chunk_index ?? ""}`))
      .filter(Boolean)
      .join("；<br />");

  const answerPreviewOf = (chunks) => {
    const first = (chunks || [])[0];
    if (!first) return "";
    return String(first.content || first.text || "").trim();
  };

  const renderRunDetailCard = ({ runId, summary, results }) => {
    const card = document.getElementById("htRunDetailCard");
    if (!card) return;
    const sub = document.getElementById("htRunDetailSub");
    const actions = document.getElementById("htRunDetailActions");
    const body = document.getElementById("htRunDetailBody");
    if (sub) sub.innerHTML = formatRunSummaryLine(summary || {});
    if (actions) {
      actions.innerHTML = `<button type="button" class="btn btn-secondary btn-sm" id="btnHtExportCsv">导出 CSV</button>`;
      actions.querySelector("#btnHtExportCsv")?.addEventListener("click", async () => {
        try {
          await exportRunCsv(runId);
        } catch (err) {
          toast(err.message || "导出失败", "error");
        }
      });
    }
    if (!body) return;
    const rows = (results || []).length
      ? results
          .map((r) => {
            const chunks = r.actual_chunks || [];
            const tip = recallTipOf(chunks);
            const answer = answerPreviewOf(chunks);
            const hitRatio = r.is_hit ? "1/1" : "0/1";
            const hitPct = r.score != null ? pct(r.score) : "—";
            const strategyText = strategyLabel(r.strategy || summary?.strategy);
            return `<tr>
              <td class="col-status ht-hit-cell">${r.is_hit ? `<span class="badge badge-success">是</span>` : `<span class="badge badge-danger">否</span>`}</td>
              <td class="ht-q-cell">
                <div class="ht-qa-block">
                  <div class="ht-qa-label">问题：</div>
                  <div class="ht-qa-question">${escapeHtml(r.question || "-")}</div>
                  <div class="ht-qa-label">详情：</div>
                  <div class="ht-qa-detail${answer ? "" : " text-muted"}">${escapeHtml(answer || "—")}</div>
                </div>
              </td>
              <td class="ht-frag-cell">
                <div class="ht-frag-stack">
                  <span class="ht-frag-ratio">${escapeHtml(hitRatio)}</span>
                  <span class="ht-frag-pct">${escapeHtml(hitPct)}</span>
                </div>
              </td>
              <td class="ht-strategy-cell">${escapeHtml(strategyText)}</td>
              <td class="ht-elapsed-cell">${escapeHtml(r.elapsed_ms != null ? `${r.elapsed_ms}ms` : "-")}</td>
              <td class="text-muted ht-recall-cell">${tip || "无召回"}</td>
            </tr>`;
          })
          .join("")
      : `<tr><td colspan="6" class="text-muted">无明细</td></tr>`;
    body.innerHTML = `<div class="table-wrap ht-detail-table-wrap"><table class="table table-fit ht-detail-table">
      <colgroup>
        <col class="ht-detail-col-hit" />
        <col class="ht-detail-col-qa" />
        <col class="ht-detail-col-frag" />
        <col class="ht-detail-col-strategy" />
        <col class="ht-detail-col-elapsed" />
        <col class="ht-detail-col-recall" />
      </colgroup>
      <thead><tr>
        <th class="col-status">命中</th>
        <th class="ht-q-col">问题 / 回答</th>
        <th class="ht-frag-col">命中片段</th>
        <th class="ht-strategy-col">策略</th>
        <th class="ht-elapsed-col">耗时</th>
        <th class="ht-recall-col">召回详情</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`;
  };

  const showRunDetailOnCard = async (runId, { scroll = true } = {}) => {
    if (!runId) return;
    try {
      const payload = await loadRunDetail(runId);
      try {
        sessionStorage.setItem(HT_DETAIL_RUN_KEY, String(runId));
      } catch {
        /* ignore */
      }
      renderRunDetailCard(payload);
      if (scroll) {
        document.getElementById("htRunDetailCard")?.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    } catch (e) {
      toast(e.message || "加载详情失败", "error");
    }
  };

  const openCreateCase = async (_docsByKb, existing = null) => {
    const existingQuestions = [
      ...((existing?.questions || []).map((q) => q.question || "")),
      ...((existing?.examples || []).map((ex) => ex.question || "")),
    ]
      .map((q) => String(q).trim())
      .filter(Boolean);
    const mask = document.createElement("div");
    mask.className = "modal-mask";
    mask.innerHTML = `
      <form class="modal" style="width:min(640px,calc(100vw - 24px));max-height:90vh;overflow:auto">
        <div class="modal-header"><h3>${existing ? "编辑测试用例" : "新建测试用例"}</h3></div>
        <div class="modal-body">
          <label class="form-label">用例名称</label>
          <input class="form-control" name="name" required placeholder="如：员工手册回归集" value="${escapeHtml(existing?.name || "")}" />
          <label class="form-label" style="margin-top:10px">说明</label>
          <input class="form-control" name="description" placeholder="可选" value="${escapeHtml(existing?.description || "")}" />
          <label class="form-label" style="margin-top:10px">问题列表</label>
          <textarea
            class="form-control"
            name="questions"
            id="caseQuestions"
            rows="8"
            required
            placeholder="每行一个问题，例如：&#10;试用期年假怎么折算？&#10;加班如何申请？"
          >${escapeHtml(existingQuestions.join("\n"))}</textarea>
          <p class="text-muted" style="margin:8px 0 0;font-size:12px">仅需填写问题。未标注期望文档时，执行按检索冒烟（有召回即计命中）。</p>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" data-close>取消</button>
          <button type="submit" class="btn btn-primary">${existing ? "保存" : "创建"}</button>
        </div>
      </form>`;
    document.body.appendChild(mask);
    mask.querySelector("[data-close]").onclick = () => mask.remove();
    mask.addEventListener("click", (e) => {
      if (e.target === mask) mask.remove();
    });

    mask.querySelector("form").onsubmit = async (ev) => {
      ev.preventDefault();
      const fd = new FormData(ev.currentTarget);
      const name = String(fd.get("name") || "").trim();
      const description = String(fd.get("description") || "").trim() || null;
      const questions = String(fd.get("questions") || "")
        .split("\n")
        .map((q) => q.trim())
        .filter(Boolean)
        .map((question) => ({ question }));
      if (!name) {
        toast("请填写用例名称", "error");
        return;
      }
      if (!questions.length) {
        toast("请至少填写一道问题（每行一条）", "error");
        return;
      }
      try {
        if (existing?.id) {
          await api.put(`/hit-tests/cases/${existing.id}`, { name, description, questions, examples: [] });
          toast("用例已更新", "success");
        } else {
          await api.post("/hit-tests/cases", { name, description, questions, examples: [] });
          toast("用例已创建", "success");
        }
        mask.remove();
        pageHitTest();
      } catch (e) {
        toast(e.message || (existing ? "更新失败" : "创建失败"), "error");
      }
    };
  };

  try {
    const [casesData, runsData, kbData] = await Promise.all([
      api.get("/hit-tests/cases?page=1&page_size=50"),
      api.get("/hit-tests/runs?page=1&page_size=100"),
      api.get("/knowledge-bases?page=1&page_size=50"),
    ]);
    // 兼容 data 解包异常或直接返回数组
    const cases = Array.isArray(casesData)
      ? casesData
      : Array.isArray(casesData?.items)
        ? casesData.items
        : [];
    const runs = Array.isArray(runsData)
      ? runsData
      : Array.isArray(runsData?.items)
        ? runsData.items
        : [];
    const kbs = Array.isArray(kbData)
      ? kbData
      : Array.isArray(kbData?.items)
        ? kbData.items
        : [];

    // 预加载各库文档（创建用例时匹配期望文档）
    const docsByKb = {};
    await Promise.all(
      kbs.map(async (kb) => {
        try {
          const d = await api.get(`/knowledge-bases/${kb.id}/documents?page=1&page_size=100`);
          docsByKb[String(kb.id)] = { name: kb.name, docs: d.items || [] };
        } catch {
          docsByKb[String(kb.id)] = { name: kb.name, docs: [] };
        }
      })
    );

    const HT_CASE_KEY = "htSelectedCaseIds";
    let selectedCaseIds = [];
    try {
      const raw = sessionStorage.getItem(HT_CASE_KEY);
      const parsed = raw ? JSON.parse(raw) : [];
      if (Array.isArray(parsed)) {
        const valid = new Set(cases.map((c) => String(c.id)));
        selectedCaseIds = parsed.map(String).filter((id) => valid.has(id));
      }
    } catch {
      /* ignore */
    }

    const caseNameOf = (caseId) => {
      const c = cases.find((x) => String(x.id) === String(caseId || ""));
      return c ? c.name : caseId ? "（用例已删）" : "临时问题";
    };

    document.getElementById("pageRoot").innerHTML = `
      ${pageHead({
        title: "命中率测试",
        desc: "多选用例按序执行；也可填写临时问题做检索冒烟。配置期望文档后可计算真实命中率。",
      })}
      <div class="page-grid">
      <div class="card span-12">
        <div class="card-header">
          <div class="card-header-text">
            <h3 class="card-title">执行参数</h3>
            <p class="card-sub">选择知识库与检索策略后执行；可多选用例，或填写临时问题冒烟</p>
          </div>
        </div>
        <div id="htSelectedBanner" class="text-muted" style="margin-bottom:16px;padding:12px 14px;background:var(--color-bg);border-radius:var(--radius)">
          当前：未选用测试用例
        </div>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px">
          <div>
            <label class="form-label">知识库</label>
            <select class="form-control" id="htKb" ${kbs.length ? "" : "disabled"}>
              ${
                kbs.length
                  ? kbs
                      .map((k) => `<option value="${escapeHtml(String(k.id))}">${escapeHtml(k.name)}</option>`)
                      .join("")
                  : `<option value="">暂无知识库</option>`
              }
            </select>
          </div>
          <div>
            <label class="form-label">检索策略</label>
            <select class="form-control" id="htStrategy">
              <option value="hybrid">混合 hybrid</option>
              <option value="vector">向量 vector</option>
              <option value="fulltext">全文 fulltext</option>
            </select>
          </div>
          <div>
            <label class="form-label">Top K</label>
            <input class="form-control" id="htTopK" type="number" min="1" max="20" value="5" />
          </div>
          <div>
            <label class="form-label">相似度阈值</label>
            <input class="form-control" id="htThreshold" type="number" min="0" max="1" step="0.05" value="0.15" />
          </div>
        </div>
        <div style="margin-top:16px" id="htAdhocWrap">
          <label class="form-label">临时问题（未选用例时生效）</label>
          <textarea
            class="form-control"
            id="htQuestions"
            rows="4"
            placeholder="每行一个问题，例如：&#10;试用期年假怎么折算？&#10;加班如何申请？"
          ></textarea>
          <p class="text-muted" style="margin:6px 0 0;font-size:12px">
            未勾选用例时用临时问题做检索冒烟（有召回即计命中）。正式命中率请勾选带期望文档/分段的用例。
          </p>
        </div>
        <div style="margin-top:20px;display:flex;flex-wrap:wrap;gap:8px">
          ${
            canWrite
              ? `<button type="button" class="btn" id="btnRunTest">执行测试</button>
                 <button type="button" class="btn btn-secondary" id="btnClearCase">清除已选</button>`
              : `<span class="text-muted">需要 test:write 才能执行</span>`
          }
        </div>
      </div>

      <div class="card span-6 panel-fill">
          <div class="card-header">
            <div class="card-header-text"><h3 class="card-title">测试用例</h3></div>
          </div>
          <div class="table-wrap"><table class="table table-ht-cases" id="htCaseTable">
            <colgroup>
              <col class="ht-cases-col-check" />
              <col class="ht-cases-col-name" />
              <col class="ht-cases-col-num" />
              <col class="ht-cases-col-desc" />
              <col class="ht-cases-col-actions" />
            </colgroup>
            <thead><tr>
              <th class="col-check"><input type="checkbox" id="htCaseSelectAll" title="全选" aria-label="全选用例" ${cases.length ? "" : "disabled"} /></th>
              <th class="col-name">名称</th>
              <th class="col-num">题数</th>
              <th class="col-desc">说明</th>
              <th class="col-actions">操作</th>
            </tr></thead>
            <tbody>
              ${
                cases.length
                  ? cases
                      .map((c) => {
                        const cid = String(c.id);
                        return `<tr class="ht-case-row" data-case-row="${escapeHtml(cid)}">
                          <td class="col-check">
                            <input type="checkbox" value="${escapeHtml(cid)}" data-pick-case="${escapeHtml(cid)}" aria-label="选用用例" />
                          </td>
                          <td class="col-name">${escapeHtml(c.name)}</td>
                          <td class="col-num">${escapeHtml(c.question_count)}</td>
                          <td class="col-desc">${escapeHtml(c.description || "-")}</td>
                          <td class="col-actions">
                            ${
                              canWrite
                                ? `<div class="table-actions table-actions-stack ht-case-actions">
                              <div class="table-actions-row">
                                <button type="button" class="btn btn-secondary btn-sm" data-edit-case="${escapeHtml(cid)}">编辑</button>
                              </div>
                              <div class="table-actions-row">
                                <button type="button" class="btn btn-danger btn-sm" data-del-case="${escapeHtml(cid)}">清除</button>
                              </div>
                            </div>`
                                : `<span class="cell-muted">—</span>`
                            }
                          </td>
                        </tr>`;
                      })
                      .join("")
                  : `<tr><td colspan="5" class="text-muted">暂无用例${canWrite ? "，请点击下方「新建用例」" : ""}</td></tr>`
              }
            </tbody>
          </table></div>
          ${
            canWrite
              ? `<div class="ht-case-card-footer">
                   <button type="button" class="btn btn-sm" id="btnNewCase">新建用例</button>
                   <button type="button" class="btn btn-secondary btn-sm" id="btnCompare">多策略对比</button>
                 </div>`
              : ""
          }
        </div>
        <div class="card span-6 panel-fill">
          <div class="card-header">
            <div class="card-header-text"><h3 class="card-title">运行记录</h3></div>
            <div class="card-header-actions">
            ${
              canWrite && runs.length
                ? `<button type="button" class="btn btn-danger btn-sm" id="btnClearAllRuns">清除全部</button>`
                : ""
            }
            </div>
          </div>
          <div class="table-wrap"><table class="table table-ht-runs" id="htRunTable">
            <colgroup>
              <col class="ht-runs-col-case" />
              <col class="ht-runs-col-score" />
              <col class="ht-runs-col-hit" />
              <col class="ht-runs-col-strategy" />
              <col class="ht-runs-col-time" />
              <col class="ht-runs-col-actions" />
            </colgroup>
            <thead><tr>
              <th class="col-name">用例</th>
              <th class="col-score">相关性</th>
              <th class="col-hit">命中</th>
              <th class="col-strategy">策略</th>
              <th class="col-time">时间</th>
              <th class="col-actions">操作</th>
            </tr></thead>
            <tbody id="htRunTableBody"></tbody>
          </table></div>
          <div class="pager pager-stack" id="htRunPager" hidden></div>
        </div>

        <div class="card span-12" id="htRunDetailCard">
          <div class="card-header">
            <div class="card-header-text">
              <h3 class="card-title">运行详情</h3>
              <p class="card-sub" id="htRunDetailSub">执行测试或点击运行记录「详情」后在此查看</p>
            </div>
            <div class="card-header-actions" id="htRunDetailActions"></div>
          </div>
          <div id="htRunDetailBody">
            <div class="empty-state text-muted" style="padding:24px 8px">尚未查看运行详情</div>
          </div>
        </div>
      </div>`;

    const banner = document.getElementById("htSelectedBanner");

    const syncSelectionUi = ({ persist = true } = {}) => {
      if (persist) {
        try {
          if (selectedCaseIds.length) sessionStorage.setItem(HT_CASE_KEY, JSON.stringify(selectedCaseIds));
          else sessionStorage.removeItem(HT_CASE_KEY);
        } catch {
          /* ignore */
        }
      }
      const selected = new Set(selectedCaseIds);
      document.querySelectorAll(".ht-case-row").forEach((tr) => {
        const on = selected.has(tr.getAttribute("data-case-row"));
        tr.classList.toggle("is-selected", on);
      });
      document.querySelectorAll("[data-pick-case]").forEach((input) => {
        input.checked = selected.has(input.value);
      });
      const selectAll = document.getElementById("htCaseSelectAll");
      if (selectAll) {
        const total = cases.length;
        const n = selectedCaseIds.filter((id) => cases.some((c) => String(c.id) === id)).length;
        selectAll.checked = total > 0 && n === total;
        selectAll.indeterminate = n > 0 && n < total;
        selectAll.disabled = total === 0;
      }
      const picked = selectedCaseIds
        .map((id) => cases.find((c) => String(c.id) === id))
        .filter(Boolean);
      if (picked.length) {
        const totalQ = picked.reduce((s, c) => s + Number(c.question_count || 0), 0);
        const names = picked.map((c) => escapeHtml(c.name)).join("、");
        banner.innerHTML = `当前已选用 <strong>${picked.length}</strong> 个用例（共 ${totalQ} 题）：${names}。执行测试将按顺序逐个运行。`;
        banner.style.background = "rgba(52, 211, 153, 0.12)";
      } else {
        banner.textContent = "当前：未选用测试用例（将使用下方临时问题）";
        banner.style.background = "rgba(255, 255, 255, 0.03)";
      }
      const adhoc = document.getElementById("htQuestions");
      const adhocWrap = document.getElementById("htAdhocWrap");
      if (adhoc) {
        adhoc.disabled = picked.length > 0;
        adhoc.placeholder = picked.length
          ? "已选用例时临时问题不生效；清除选用后可填写"
          : "每行一个问题，例如：\n试用期年假怎么折算？\n加班如何申请？";
      }
      if (adhocWrap) adhocWrap.style.opacity = picked.length ? "0.55" : "1";
    };

    const setCaseSelected = (caseId, on) => {
      const id = String(caseId || "");
      if (!id) return;
      const idx = selectedCaseIds.indexOf(id);
      if (on && idx < 0) selectedCaseIds.push(id);
      if (!on && idx >= 0) selectedCaseIds.splice(idx, 1);
      syncSelectionUi();
    };

    // 事件委托：避免按钮/标签点击失效
    const caseTable = document.getElementById("htCaseTable");
    if (caseTable) {
      caseTable.addEventListener("change", (e) => {
        const input = e.target.closest("[data-pick-case]");
        if (!input) return;
        setCaseSelected(input.value, !!input.checked);
      });
      caseTable.addEventListener("click", (e) => {
        const editBtn = e.target.closest("[data-edit-case]");
        if (editBtn) {
          const c = cases.find((x) => String(x.id) === String(editBtn.getAttribute("data-edit-case")));
          if (c) openCreateCase(docsByKb, c);
          return;
        }
        const delBtn = e.target.closest("[data-del-case]");
        if (delBtn) {
          (async () => {
            const ok = await confirmDialog({
              title: "清除用例",
              message: "确定清除该测试用例？",
              confirmText: "清除",
              danger: true,
            });
            if (!ok) return;
            try {
              await api.delete(`/hit-tests/cases/${delBtn.getAttribute("data-del-case")}`);
              toast("已清除", "success");
              pageHitTest();
            } catch (err) {
              toast(err.message || "清除失败", "error");
            }
          })();
        }
      });
    }

    syncSelectionUi({ persist: false });

    const htCaseSelectAll = document.getElementById("htCaseSelectAll");
    if (htCaseSelectAll) {
      htCaseSelectAll.addEventListener("change", () => {
        selectedCaseIds = htCaseSelectAll.checked ? cases.map((c) => String(c.id)) : [];
        syncSelectionUi();
      });
    }

    const btnClear = document.getElementById("btnClearCase");
    if (btnClear) {
      btnClear.onclick = () => {
        selectedCaseIds = [];
        syncSelectionUi();
      };
    }

    const btnNew = document.getElementById("btnNewCase");
    if (btnNew) btnNew.onclick = () => openCreateCase(docsByKb);

    const HT_RUN_PAGE_SIZE = 5;
    let runListPage = 1;

    const renderRunsPage = () => {
      const tbody = document.getElementById("htRunTableBody");
      const pager = document.getElementById("htRunPager");
      if (!tbody) return;
      const total = runs.length;
      const totalPages = Math.max(1, Math.ceil(total / HT_RUN_PAGE_SIZE) || 1);
      if (runListPage > totalPages) runListPage = totalPages;
      if (runListPage < 1) runListPage = 1;
      const start = (runListPage - 1) * HT_RUN_PAGE_SIZE;
      const pageItems = runs.slice(start, start + HT_RUN_PAGE_SIZE);

      if (!total) {
        tbody.innerHTML = `<tr><td colspan="6" class="text-muted">暂无运行记录</td></tr>`;
        if (pager) {
          pager.hidden = true;
          pager.innerHTML = "";
        }
        return;
      }

      tbody.innerHTML = pageItems
        .map(
          (r) => `<tr data-run-row="${escapeHtml(String(r.id))}">
            <td class="col-name">${escapeHtml(caseNameOf(r.case_id))}</td>
            <td class="col-score"><strong>${pct(r.score)}</strong></td>
            <td class="col-hit">
              <div class="ht-run-hit-stack">
                <span class="ht-run-hit-ratio">${escapeHtml(r.hit_count)}/${escapeHtml(r.total_questions)}</span>
                <span class="ht-run-hit-pct">${r.hit_rate != null ? escapeHtml(pct(r.hit_rate)) : "—"}</span>
              </div>
            </td>
            <td class="col-strategy">${escapeHtml(strategyLabel(r.strategy))}</td>
            <td class="col-time">${formatDateTimeHtml(r.completed_at || r.created_at)}</td>
            <td class="col-actions">
              <div class="table-actions table-actions-col ht-run-actions">
                <button type="button" class="btn btn-secondary btn-sm" data-run="${escapeHtml(String(r.id))}">详情</button>
                ${canWrite ? `<button type="button" class="btn btn-danger btn-sm" data-del-run="${escapeHtml(String(r.id))}">清除</button>` : ""}
              </div>
            </td>
          </tr>`
        )
        .join("");

      if (!pager) return;
      if (totalPages <= 1) {
        pager.hidden = true;
        pager.innerHTML = "";
        return;
      }
      const { buttons, jump } = renderCompactPagerParts(runListPage, totalPages);
      pager.hidden = false;
      pager.innerHTML = `
        <div class="pager-row">
          <button type="button" class="btn btn-secondary btn-sm" data-page-prev ${runListPage <= 1 ? "disabled" : ""}>上一页</button>
          ${buttons}
          <button type="button" class="btn btn-secondary btn-sm" data-page-next ${runListPage >= totalPages ? "disabled" : ""}>下一页</button>
        </div>
        <div class="pager-row pager-row-jump">${jump}</div>`;
      bindCompactPager(pager, {
        page: runListPage,
        totalPages,
        onGo: (p) => {
          runListPage = p;
          renderRunsPage();
        },
      });
    };

    renderRunsPage();

    const runTable = document.getElementById("htRunTable");
    if (runTable) {
      runTable.addEventListener("click", (e) => {
        const detailBtn = e.target.closest("[data-run]");
        if (detailBtn) {
          showRunDetailOnCard(detailBtn.getAttribute("data-run"), { scroll: true });
          return;
        }
        const delBtn = e.target.closest("[data-del-run]");
        if (delBtn) {
          (async () => {
            const ok = await confirmDialog({
              title: "清除运行记录",
              message: "确定清除这条运行记录？",
              confirmText: "清除",
              danger: true,
            });
            if (!ok) return;
            try {
              await api.delete(`/hit-tests/runs/${delBtn.getAttribute("data-del-run")}`);
              toast("已清除", "success");
              pageHitTest();
            } catch (err) {
              toast(err.message || "清除失败", "error");
            }
          })();
        }
      });
    }

    const btnClearAllRuns = document.getElementById("btnClearAllRuns");
    if (btnClearAllRuns) {
      btnClearAllRuns.onclick = async () => {
        const ok = await confirmDialog({
          title: "清除全部运行记录",
          message: "将删除全部历史运行记录，不可恢复。确定继续？",
          confirmText: "全部清除",
          danger: true,
        });
        if (!ok) return;
        try {
          const res = await api.delete("/hit-tests/runs");
          const n = res?.deleted;
          toast(n != null ? `已清除 ${n} 条运行记录` : "已清除全部记录", "success");
          pageHitTest();
        } catch (err) {
          toast(err.message || "清除失败", "error");
        }
      };
    }

    const buildBasePayload = () => {
      const kbId = document.getElementById("htKb").value;
      if (!kbId) throw new Error("请选择知识库");
      return {
        kb_ids: [kbId],
        strategy: document.getElementById("htStrategy").value || "hybrid",
        top_k: Number(document.getElementById("htTopK").value || 5),
        similarity_threshold: Number(document.getElementById("htThreshold").value || 0.15),
      };
    };

    const btnRun = document.getElementById("btnRunTest");
    if (btnRun) {
      btnRun.onclick = async () => {
        btnRun.disabled = true;
        const prev = btnRun.textContent;
        try {
          const base = buildBasePayload();
          let lastRunId = null;
          if (selectedCaseIds.length) {
            const summaries = [];
            for (let i = 0; i < selectedCaseIds.length; i += 1) {
              const caseId = selectedCaseIds[i];
              btnRun.textContent = `执行中 ${i + 1}/${selectedCaseIds.length}…`;
              const run = await api.post("/hit-tests/runs", { ...base, case_id: caseId });
              lastRunId = run?.id || lastRunId;
              summaries.push(
                `${caseNameOf(caseId)} ${run.hit_count}/${run.total_questions}（相关度 ${pct(run.score)}）`
              );
            }
            toast(`已完成 ${summaries.length} 个用例：${summaries.join("；")}`, "success");
          } else {
            const questions = String(document.getElementById("htQuestions")?.value || "")
              .split("\n")
              .map((q) => q.trim())
              .filter(Boolean);
            if (!questions.length) {
              throw new Error("请先勾选至少一个测试用例，或填写临时问题（每行一条）");
            }
            btnRun.textContent = "执行中…";
            const run = await api.post("/hit-tests/runs", { ...base, questions });
            lastRunId = run?.id || null;
            toast(
              `临时问题完成：命中 ${run.hit_count}/${run.total_questions}（相关度 ${pct(run.score)}）`,
              "success"
            );
          }
          if (lastRunId) {
            try {
              sessionStorage.setItem(HT_DETAIL_RUN_KEY, String(lastRunId));
            } catch {
              /* ignore */
            }
          }
          pageHitTest();
        } catch (e) {
          toast(e.message || "执行失败", "error");
          btnRun.disabled = false;
          btnRun.textContent = prev || "执行测试";
        }
      };
    }

    const btnCompare = document.getElementById("btnCompare");
    if (btnCompare) {
      btnCompare.onclick = async () => {
        if (!selectedCaseIds.length) {
          toast("多策略对比需要先勾选至少一个测试用例", "error");
          return;
        }
        btnCompare.disabled = true;
        try {
          const base = buildBasePayload();
          const sections = [];
          for (let i = 0; i < selectedCaseIds.length; i += 1) {
            const caseId = selectedCaseIds[i];
            btnCompare.textContent = `对比中 ${i + 1}/${selectedCaseIds.length}…`;
            const result = await api.post("/hit-tests/compare", {
              case_id: caseId,
              kb_ids: base.kb_ids,
              strategies: ["vector", "fulltext", "hybrid"],
              top_k: base.top_k,
              similarity_threshold: base.similarity_threshold,
            });
            const rows = result.side_by_side || [];
            sections.push(`
              <h4 style="margin:16px 0 8px">${escapeHtml(caseNameOf(caseId))}</h4>
              <div class="table-wrap"><table class="table">
                <thead><tr><th>问题</th><th>向量</th><th>全文</th><th>混合</th></tr></thead>
                <tbody>
                  ${rows
                    .map((row) => {
                      const map = Object.fromEntries((row.by_strategy || []).map((x) => [x.strategy, x]));
                      const cell = (s) => {
                        const x = map[s];
                        if (!x) return "-";
                        return `${x.is_hit ? "命中" : "未命中"} ${x.score != null ? pct(x.score) : ""}`;
                      };
                      return `<tr>
                        <td>${escapeHtml(row.question)}</td>
                        <td>${escapeHtml(cell("vector"))}</td>
                        <td>${escapeHtml(cell("fulltext"))}</td>
                        <td>${escapeHtml(cell("hybrid"))}</td>
                      </tr>`;
                    })
                    .join("")}
                </tbody>
              </table></div>`);
          }
          await openWideModal({
            title: `多策略对比（${selectedCaseIds.length} 个用例）`,
            bodyHtml: `
              <p class="text-muted" style="margin-top:0">对已选用例分别对比向量 / 全文 / 混合；每个用例会产生 3 条运行记录。</p>
              ${sections.join("")}`,
            actionsHtml: `<button type="button" class="btn btn-secondary" data-act="cancel">关闭</button>`,
          });
          pageHitTest();
        } catch (e) {
          toast(e.message || "对比失败", "error");
        } finally {
          btnCompare.disabled = false;
          btnCompare.textContent = "多策略对比";
        }
      };
    }

    // 恢复上次查看 / 刚执行完的运行详情
    let pendingDetailId = null;
    try {
      pendingDetailId = sessionStorage.getItem(HT_DETAIL_RUN_KEY);
    } catch {
      pendingDetailId = null;
    }
    if (pendingDetailId) {
      const exists = runs.some((r) => String(r.id) === String(pendingDetailId));
      if (exists) {
        showRunDetailOnCard(pendingDetailId, { scroll: false });
      } else {
        try {
          sessionStorage.removeItem(HT_DETAIL_RUN_KEY);
        } catch {
          /* ignore */
        }
      }
    }
  } catch (e) {
    document.getElementById("pageRoot").innerHTML = `<div class="card text-danger">${escapeHtml(e.message)}</div>`;
  }
}

/* ========== 审计日志（产品手册 5.8.5） ========== */
const AUDIT_ACTION_LABELS = {
  "snapshot.create": "创建快照",
  "snapshot.auto_create": "自动创建快照",
  "snapshot.cleanup": "策略清理快照",
  "snapshot.rollback": "回退快照",
  "snapshot.rollback_rebuild": "回退重建索引",
  "snapshot.delete": "删除快照",
  "snapshot.index_activate": "激活索引版本",
  "kb.create": "创建知识库",
  "kb.update": "更新知识库",
  "kb.delete": "删除知识库",
  "doc.upload": "上传文档",
  "doc.delete": "删除文档",
  "doc.pipeline_error": "文档处理失败",
  "doc.upload_failed_cleaned": "失败上传已清理",
  "doc.normalize": "规范化文档",
  "doc.resegment": "重分段",
  "role.create": "创建角色",
  "role.update": "更新角色",
  "role.delete": "删除角色",
  "role.permissions": "变更角色权限",
  "user.create": "创建用户",
  "user.update": "更新用户",
  "user.status": "变更用户状态",
  "user.roles": "变更用户角色",
  "auth.login": "登录",
  "auth.logout": "登出",
  "model.create": "创建模型配置",
  "model.update": "更新模型配置",
};

const AUDIT_RESOURCE_LABELS = {
  snapshot: "快照",
  kb: "知识库",
  knowledge_base: "知识库",
  document: "文档",
  user: "用户",
  role: "角色",
};

/* ========== RAGAS 评估 /admin/ragas ========== */
const RAGAS_METRIC_LABELS = {
  faithfulness: "忠实度",
  answer_relevancy: "答案相关性",
  context_precision: "上下文精确率",
  context_recall: "上下文召回率",
};

const RAGAS_SOURCE_LABELS = {
  history: "历史",
  generated: "生成",
  manual: "手动",
};

/** 把 RAGAS 的 0-1 分数渲染为百分比；缺少标准答案的指标显示未评估。 */
function ragasScore(value) {
  return value == null || Number.isNaN(Number(value)) ? "未评估" : `${(Number(value) * 100).toFixed(1)}%`;
}

/** 粗估评估耗时：约每样本 4 分钟（含评分 LLM 多次调用）。 */
function ragasEtaText(count) {
  const n = Math.max(0, Number(count) || 0);
  if (!n) return "请先准备样本";
  const minutes = Math.max(1, Math.round(n * 4));
  return `约 ${minutes} 分钟（${n} 条样本）`;
}

function createRagasDraft(partial = {}) {
  return {
    id: `draft-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    question: "",
    reference: "",
    qa_message_id: null,
    source: "manual",
    response_preview: "",
    context_count: 0,
    ...partial,
  };
}

async function pageRagas() {
  if (!requirePerm("system:read", "RAGAS 评估")) return;
  const root = document.getElementById("pageRoot");
  root.innerHTML = `<div class="loading">加载 RAGAS 评估记录…</div>`;
  try {
    const [kbData, runData] = await Promise.all([
      api.get("/knowledge-bases?page=1&page_size=100"),
      api.get("/ragas/runs?page=1&page_size=50"),
    ]);
    const knowledgeBases = kbData.items || [];
    const runs = runData.items || [];
    const kbOptions = knowledgeBases
      .map((kb) => `<option value="${escapeHtml(kb.id)}">${escapeHtml(kb.name)}</option>`)
      .join("");
    /** @type {ReturnType<typeof createRagasDraft>[]} */
    let drafts = [];

    const renderDrafts = () => {
      const list = document.getElementById("ragasDraftList");
      const meta = document.getElementById("ragasDraftMeta");
      const eta = document.getElementById("ragasEta");
      if (!list || !meta || !eta) return;
      meta.textContent = `当前 ${drafts.length} 条样本`;
      eta.textContent = ragasEtaText(drafts.length);
      if (!drafts.length) {
        list.innerHTML = `<div class="empty-state" style="padding:24px">尚未准备样本。可「从历史加载」「自动生成」或「添加问题」。</div>`;
        return;
      }
      list.innerHTML = drafts
        .map((draft, index) => {
          const sourceLabel = RAGAS_SOURCE_LABELS[draft.source] || draft.source || "手动";
          const preview = draft.response_preview
            ? `<p class="text-muted" style="margin:6px 0 0;font-size:12px">历史回答预览：${escapeHtml(draft.response_preview)}</p>`
            : "";
          const contextHint =
            draft.source === "history"
              ? `<span class="badge">${escapeHtml(draft.context_count || 0)} 段引用</span>`
              : draft.source === "generated"
                ? `<span class="badge">将现问现答后评分</span>`
                : `<span class="badge">将检索并生成回答</span>`;
          return `<div class="card" data-draft-id="${escapeHtml(draft.id)}" style="margin-bottom:10px;padding:12px;background:var(--color-bg-tint,#f8f9fa)">
            <div style="display:flex;gap:10px;align-items:flex-start;justify-content:space-between;flex-wrap:wrap">
              <div style="display:flex;gap:8px;align-items:center">
                <strong>样本 ${index + 1}</strong>
                <span class="badge">${escapeHtml(sourceLabel)}</span>
                ${contextHint}
              </div>
              <button type="button" class="btn btn-text btn-sm text-danger" data-remove-draft="${escapeHtml(draft.id)}">移除</button>
            </div>
            <label class="form-label" style="margin-top:10px">问题</label>
            <textarea class="form-control" rows="2" data-draft-question="${escapeHtml(draft.id)}">${escapeHtml(draft.question)}</textarea>
            <label class="form-label" style="margin-top:10px">标准答案（可选，填写后可评估上下文召回率）</label>
            <textarea class="form-control" rows="2" data-draft-reference="${escapeHtml(draft.id)}" placeholder="可留空">${escapeHtml(draft.reference || "")}</textarea>
            ${preview}
          </div>`;
        })
        .join("");

      list.querySelectorAll("[data-remove-draft]").forEach((button) => {
        button.onclick = () => {
          const id = button.getAttribute("data-remove-draft");
          drafts = drafts.filter((item) => item.id !== id);
          renderDrafts();
        };
      });
      list.querySelectorAll("[data-draft-question]").forEach((input) => {
        input.oninput = () => {
          const id = input.getAttribute("data-draft-question");
          const draft = drafts.find((item) => item.id === id);
          if (draft) draft.question = input.value;
        };
      });
      list.querySelectorAll("[data-draft-reference]").forEach((input) => {
        input.oninput = () => {
          const id = input.getAttribute("data-draft-reference");
          const draft = drafts.find((item) => item.id === id);
          if (draft) draft.reference = input.value;
        };
      });
    };

    const syncDraftsFromDom = () => {
      drafts = drafts.map((draft) => {
        const questionEl = root.querySelector(`[data-draft-question="${draft.id}"]`);
        const referenceEl = root.querySelector(`[data-draft-reference="${draft.id}"]`);
        return {
          ...draft,
          question: questionEl ? questionEl.value : draft.question,
          reference: referenceEl ? referenceEl.value : draft.reference,
        };
      });
    };

    const readLimit = () => {
      const value = Number(document.getElementById("ragasLimit").value);
      return Number.isInteger(value) ? value : NaN;
    };

    root.innerHTML = `
      ${pageHead({
        title: "RAGAS 评估",
        desc: "可从历史问答挑选、自动生成或手动填写样本问题，再评估忠实度、答案相关性与上下文指标。",
      })}
      <div class="page-grid">
      <div class="card span-12">
        <div class="card-header">
          <div class="card-header-text">
            <h3 class="card-title">发起评估</h3>
            <p class="card-sub">有标准答案时才会计算上下文召回率；自定义/生成问题会先检索并生成回答再评分。</p>
          </div>
        </div>
        <div style="display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end;padding:0 4px 12px">
          <label><span class="form-label">知识库</span><select class="form-control" id="ragasKb" style="min-width:220px">${kbOptions || `<option value="">暂无知识库</option>`}</select></label>
          <label><span class="form-label">目标样本数</span><input class="form-control" id="ragasLimit" type="number" min="1" max="50" value="5" style="width:90px" title="用于加载历史/自动生成的数量建议" /></label>
          <button type="button" class="btn btn-secondary" id="btnLoadHistory" ${knowledgeBases.length ? "" : "disabled"}>从历史加载</button>
          <button type="button" class="btn btn-secondary" id="btnGenerateQuestions" ${knowledgeBases.length ? "" : "disabled"}>自动生成问题</button>
          <button type="button" class="btn btn-secondary" id="btnAddQuestion" ${knowledgeBases.length ? "" : "disabled"}>添加问题</button>
          <button type="button" class="btn btn-text" id="btnClearDrafts" ${knowledgeBases.length ? "" : "disabled"}>清空样本</button>
          <button type="button" class="btn btn-primary" id="btnRunRagas" ${knowledgeBases.length ? "" : "disabled"}>开始评估</button>
        </div>
        <div style="display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;padding:0 4px 8px">
          <span class="text-muted" id="ragasDraftMeta">当前 0 条样本</span>
          <span class="text-muted" id="ragasEta">${ragasEtaText(0)}</span>
        </div>
        <div id="ragasDraftList"></div>
      </div>
      <div class="card panel-fill span-12">
        <div class="card-header">
          <div class="card-header-text"><h3 class="card-title">评估记录</h3></div>
          <span class="badge">共 ${escapeHtml(runData.total ?? runs.length)} 次</span>
        </div>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>知识库</th><th>状态</th><th>样本</th><th>忠实度</th><th>答案相关性</th><th>上下文精确率</th><th>上下文召回率</th><th class="col-time">完成时间</th><th></th></tr></thead>
          <tbody>
            ${
              runs.length
                ? runs
                    .map(
                      (run) => `<tr>
                        <td>${escapeHtml(run.kb_name || run.kb_id)}</td>
                        <td class="col-status"><span class="badge ${
                          run.status === "completed"
                            ? "badge-success"
                            : run.status === "failed"
                              ? "badge-danger"
                              : "badge-info"
                        }">${run.status === "completed" ? "已完成" : run.status === "failed" ? "失败" : "运行中"}</span>${run.error_message ? `<div class="text-danger" style="max-width:220px">${escapeHtml(run.error_message)}</div>` : ""}</td>
                        <td>${escapeHtml(run.sample_count ?? 0)}</td>
                        <td>${ragasScore(run.metric_scores?.faithfulness)}</td>
                        <td>${ragasScore(run.metric_scores?.answer_relevancy)}</td>
                        <td>${ragasScore(run.metric_scores?.context_precision)}</td>
                        <td>${ragasScore(run.metric_scores?.context_recall)}</td>
                        <td class="col-time">${formatDateTimeHtml(run.completed_at || run.created_at)}</td>
                        <td><button type="button" class="btn btn-text btn-sm" data-ragas-detail="${escapeHtml(run.id)}">详细结果</button></td>
                      </tr>`
                    )
                    .join("")
                : `<tr><td colspan="9" class="text-muted">暂无评估记录，请准备样本后开始评估</td></tr>`
            }
          </tbody>
        </table></div>
      </div>
      </div>`;

    renderDrafts();

    document.getElementById("ragasKb").onchange = () => {
      drafts = [];
      renderDrafts();
    };

    document.getElementById("btnClearDrafts").onclick = () => {
      drafts = [];
      renderDrafts();
    };

    document.getElementById("btnAddQuestion").onclick = () => {
      if (drafts.length >= 50) {
        toast("最多 50 条样本", "error");
        return;
      }
      syncDraftsFromDom();
      drafts.push(createRagasDraft({ source: "manual" }));
      renderDrafts();
    };

    document.getElementById("btnLoadHistory").onclick = async () => {
      const kbId = document.getElementById("ragasKb").value;
      const sampleLimit = readLimit();
      if (!kbId) {
        toast("请选择知识库", "error");
        return;
      }
      if (!Number.isInteger(sampleLimit) || sampleLimit < 1 || sampleLimit > 50) {
        toast("目标样本数必须是 1-50 的整数", "error");
        return;
      }
      const button = document.getElementById("btnLoadHistory");
      button.disabled = true;
      button.textContent = "加载中…";
      try {
        const data = await api.get(`/ragas/samples?kb_id=${encodeURIComponent(kbId)}&limit=${sampleLimit}`);
        const items = data.items || [];
        if (!items.length) {
          toast("该知识库暂无带引用的历史问答，可改用自动生成或手动添加", "error");
          return;
        }
        drafts = items.map((item) =>
          createRagasDraft({
            question: item.question || "",
            reference: item.reference || "",
            qa_message_id: item.qa_message_id || null,
            source: "history",
            response_preview: item.response_preview || "",
            context_count: item.context_count || 0,
          })
        );
        if (data.suggested_limit) {
          document.getElementById("ragasLimit").value = String(data.suggested_limit);
        }
        renderDrafts();
        toast(`已加载 ${drafts.length} 条历史样本，可继续编辑问题或标准答案`);
      } catch (error) {
        toast(`加载历史样本失败：${error.message}`, "error");
      } finally {
        button.disabled = false;
        button.textContent = "从历史加载";
      }
    };

    document.getElementById("btnGenerateQuestions").onclick = async () => {
      const kbId = document.getElementById("ragasKb").value;
      const sampleLimit = readLimit();
      if (!kbId) {
        toast("请选择知识库", "error");
        return;
      }
      if (!Number.isInteger(sampleLimit) || sampleLimit < 1 || sampleLimit > 20) {
        toast("自动生成数量请设为 1-20", "error");
        return;
      }
      const button = document.getElementById("btnGenerateQuestions");
      button.disabled = true;
      button.textContent = "生成中…";
      try {
        const data = await api.post("/ragas/generate-questions", {
          kb_id: kbId,
          count: Math.min(sampleLimit, 20),
        });
        const items = data.items || [];
        if (!items.length) {
          toast("未能生成问题，请检查知识库是否有就绪文档", "error");
          return;
        }
        drafts = items.map((item) =>
          createRagasDraft({
            question: item.question || "",
            reference: item.reference || "",
            source: "generated",
          })
        );
        renderDrafts();
        toast(`已生成 ${drafts.length} 个问题草稿，可编辑后开始评估`);
      } catch (error) {
        toast(`自动生成失败：${error.message}`, "error");
      } finally {
        button.disabled = false;
        button.textContent = "自动生成问题";
      }
    };

    document.getElementById("btnRunRagas").onclick = async () => {
      const kbId = document.getElementById("ragasKb").value;
      if (!kbId) {
        toast("请选择知识库", "error");
        return;
      }
      syncDraftsFromDom();
      const samples = drafts
        .map((draft) => ({
          question: (draft.question || "").trim(),
          reference: (draft.reference || "").trim() || null,
          qa_message_id: draft.qa_message_id || null,
        }))
        .filter((item) => item.question);
      if (!samples.length) {
        toast("请先加载、生成或添加至少一条样本问题", "error");
        return;
      }
      if (samples.length > 50) {
        toast("一次最多评估 50 条样本", "error");
        return;
      }
      const button = document.getElementById("btnRunRagas");
      button.disabled = true;
      button.textContent = "评估中…";
      toast(`RAGAS 评估已开始（${ragasEtaText(samples.length)}），请等待完成`);
      try {
        const result = await api.post("/ragas/runs", {
          kb_id: kbId,
          sample_limit: samples.length,
          samples,
        });
        toast(`RAGAS 评估完成，共处理 ${result.sample_count || 0} 个样本`);
        await pageRagas();
      } catch (error) {
        toast(`RAGAS 评估失败：${error.message}`, "error");
        button.disabled = false;
        button.textContent = "开始评估";
      }
    };
    root.querySelectorAll("[data-ragas-detail]").forEach((button) => {
      button.onclick = () => openRagasRunDetail(button.getAttribute("data-ragas-detail"));
    });
  } catch (error) {
    root.innerHTML = `<div class="card empty-state">加载 RAGAS 评估失败：${escapeHtml(error.message)}</div>`;
  }
}

/** 展示每个真实问答样本的指标分数、RAGAS 原因和检索上下文。 */
async function openRagasRunDetail(runId) {
  try {
    const data = await api.get(`/ragas/runs/${runId}`);
    const run = data.run || {};
    const items = data.items || [];
    const itemHtml = items.length
      ? items
          .map((item, index) => {
            const metricRows = Object.keys(RAGAS_METRIC_LABELS)
              .map((name) => {
                const score = item.metric_scores?.[name];
                const reason = item.metric_reasons?.[name];
                const error = item.metric_errors?.[name];
                return `<tr>
                  <td>${RAGAS_METRIC_LABELS[name]}</td>
                  <td><strong>${ragasScore(score)}</strong></td>
                  <td>${reason ? escapeHtml(reason) : error ? `<span class="text-danger">${escapeHtml(error)}</span>` : "未运行"}</td>
                </tr>`;
              })
              .join("");
            return `<div class="card" style="margin-bottom:12px;background:var(--color-bg-tint,#f8f9fa)">
              <h4 style="margin-top:0">样本 ${index + 1}</h4>
              <p><strong>用户问题：</strong>${escapeHtml(item.user_input)}</p>
              <p style="white-space:pre-wrap"><strong>系统回答：</strong>${escapeHtml(item.response)}</p>
              <details><summary>检索上下文（${item.retrieved_contexts?.length || 0} 段）</summary>
                ${(item.retrieved_contexts || []).map((context) => `<pre style="white-space:pre-wrap">${escapeHtml(context)}</pre>`).join("")}
              </details>
              <div class="table-wrap" style="margin-top:10px"><table class="table"><thead><tr><th>指标</th><th>分数</th><th>RAGAS 原因或错误</th></tr></thead><tbody>${metricRows}</tbody></table></div>
            </div>`;
          })
          .join("")
      : `<div class="empty-state">该运行没有可展示的样本明细</div>`;

    const mask = document.createElement("div");
    mask.className = "modal-mask";
    mask.innerHTML = `
      <div class="modal" role="dialog" aria-modal="true" style="width:min(1050px,calc(100vw - 24px));max-height:92vh;overflow:auto">
        <div class="modal-header"><h3>RAGAS 详细结果 · ${escapeHtml(run.kb_name || "知识库")}</h3></div>
        <div class="modal-body">
          <p class="text-muted" style="margin-top:0">状态：${escapeHtml(run.status)} · 样本 ${escapeHtml(run.sample_count ?? 0)} 个 · 完成时间 ${formatDateTime(run.completed_at)}</p>
          ${itemHtml}
        </div>
        <div class="modal-footer"><button type="button" class="btn btn-secondary" data-close>关闭</button></div>
      </div>`;
    document.body.appendChild(mask);
    mask.querySelector("[data-close]").onclick = () => mask.remove();
    mask.addEventListener("click", (event) => {
      if (event.target === mask) mask.remove();
    });
  } catch (error) {
    toast(`加载 RAGAS 详细结果失败：${error.message}`, "error");
  }
}

/* ========== 会话分析 /admin/qa-sessions ========== */
async function pageQaSessions() {
  if (!requirePerm("system:read", "会话分析")) return;
  const root = document.getElementById("pageRoot");
  root.innerHTML = `<div class="loading">加载会话与 Query 预处理记录…</div>`;

  try {
    // 配置与会话记录彼此独立，并行加载可以缩短管理页首屏等待时间。
    const [data, queryConfig] = await Promise.all([
      api.get("/qa/admin/sessions?page=1&page_size=50"),
      api.get("/query-processing"),
    ]);
    const sessions = data.items || [];
    const canWrite = hasPermission("kb:write");
    root.innerHTML = `
      ${pageHead({
        title: "会话分析",
        desc: "Query 预处理策略与会话审计。HyDE 只用于向量召回，不作为回答依据。",
      })}
      <div class="page-grid">
      <div class="card span-12">
        <div class="card-header">
          <div class="card-header-text">
            <h3 class="card-title">Query 预处理策略</h3>
            <p class="card-sub">默认仅开启 Query 改写；扩展与 HyDE 会增加模型开销</p>
          </div>
          ${canWrite ? `<div class="card-header-actions"><button type="button" class="btn btn-primary btn-sm" data-query-config-save>保存策略</button></div>` : ""}
        </div>
        <div style="display:flex;gap:24px;align-items:center;flex-wrap:wrap">
          <label style="display:flex;align-items:center;gap:8px">
            <input type="checkbox" data-query-rewrite ${queryConfig.rewrite_enabled ? "checked" : ""} ${canWrite ? "" : "disabled"} />
            启用 Query 改写
          </label>
          <label style="display:flex;align-items:center;gap:8px">
            <input type="checkbox" data-query-expansion ${queryConfig.expansion_enabled ? "checked" : ""} ${canWrite ? "" : "disabled"} />
            启用 Query 扩展
          </label>
          <label style="display:flex;align-items:center;gap:8px">
            扩展数量
            <input class="form-control" style="width:72px" type="number" min="0" max="5" value="${escapeHtml(queryConfig.expansion_count ?? 1)}" data-query-expansion-count ${canWrite && queryConfig.expansion_enabled ? "" : "disabled"} />
          </label>
          <label style="display:flex;align-items:center;gap:8px">
            <input type="checkbox" data-query-hyde ${queryConfig.hyde_enabled ? "checked" : ""} ${canWrite ? "" : "disabled"} />
            启用 HyDE 假设文档
          </label>
        </div>
      </div>
      <div class="card panel-fill span-12">
        <div class="card-header">
          <div class="card-header-text">
            <h3 class="card-title">Query 预处理审计</h3>
            <p class="card-sub">原始 Query、改写、扩展与 HyDE</p>
          </div>
          <span class="badge">共 ${escapeHtml(data.total ?? sessions.length)} 个会话</span>
        </div>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>会话</th><th>用户</th><th>类型</th><th>消息数</th><th class="col-time">最后活跃</th><th></th></tr></thead>
          <tbody>
            ${
              sessions.length
                ? sessions
                    .map(
                      (session) => `<tr>
                        <td>${escapeHtml(session.title || "未命名会话")}</td>
                        <td>${escapeHtml(session.owner || "-")}</td>
                        <td>${session.owner_type === "guest" ? "访客" : "注册用户"}</td>
                        <td>${escapeHtml(session.message_count ?? 0)}</td>
                        <td class="col-time">${formatDateTimeHtml(session.last_active_at)}</td>
                        <td><button type="button" class="btn btn-text btn-sm" data-session-detail="${escapeHtml(session.id)}">查看处理结果</button></td>
                      </tr>`
                    )
                    .join("")
                : `<tr><td colspan="6" class="text-muted">暂无会话记录</td></tr>`
            }
          </tbody>
        </table></div>
      </div>
      </div>`;

    if (canWrite) {
      const expansionToggle = root.querySelector("[data-query-expansion]");
      const expansionCount = root.querySelector("[data-query-expansion-count]");
      // 扩展关闭时禁用数量输入，防止管理员误以为数量仍会生效。
      expansionToggle.onchange = () => {
        expansionCount.disabled = !expansionToggle.checked;
      };
      root.querySelector("[data-query-config-save]").onclick = async () => {
        const count = Number(expansionCount.value);
        if (!Number.isInteger(count) || count < 0 || count > 5) {
          toast("Query 扩展数量必须是 0-5 的整数", "error");
          return;
        }
        try {
          await api.put("/query-processing", {
            rewrite_enabled: root.querySelector("[data-query-rewrite]").checked,
            expansion_enabled: expansionToggle.checked,
            expansion_count: count,
            hyde_enabled: root.querySelector("[data-query-hyde]").checked,
          });
          toast("Query 预处理策略已保存");
          await pageQaSessions();
        } catch (error) {
          toast(`保存 Query 预处理策略失败：${error.message}`, "error");
        }
      };
    }

    root.querySelectorAll("[data-session-detail]").forEach((button) => {
      button.onclick = () => openQaSessionDetail(button.getAttribute("data-session-detail"));
    });
  } catch (error) {
    root.innerHTML = `<div class="card empty-state">加载会话分析失败：${escapeHtml(error.message)}</div>`;
  }
}

/* ========== 角色缓存 /admin/role-caches ========== */
async function pageRoleCaches() {
  if (!requirePerm("system:read", "角色缓存知识库")) return;
  const root = document.getElementById("pageRoot");
  root.innerHTML = `<div class="loading">加载角色缓存配置…</div>`;
  const canWrite = hasPermission("kb:write");

  try {
    const caches = await api.get("/role-caches");
    root.innerHTML = `
      ${pageHead({
        title: "角色缓存",
        desc: "按角色隔离的缓存知识库；默认定时分析文档与历史高频问题。",
      })}
      <div class="card panel-fill">
        <div class="card-header">
          <div class="card-header-text">
            <h3 class="card-title">缓存配置</h3>
            <p class="card-sub">完全相同且来源库仍有权限的问题才会命中</p>
          </div>
        </div>
        <div class="table-wrap"><table class="table table-role-caches">
          <colgroup>
            <col class="rc-col-kb" />
            <col class="rc-col-role" />
            <col class="rc-col-count" />
            <col class="rc-col-cycle" />
            <col class="rc-col-time" />
            <col class="rc-col-time" />
            <col class="rc-col-status" />
            <col class="rc-col-actions" />
          </colgroup>
          <thead><tr>
            <th class="col-name">缓存知识库</th>
            <th class="col-role">角色</th>
            <th class="col-num">缓存数</th>
            <th class="col-cycle">检测周期</th>
            <th class="col-time">文档分析</th>
            <th class="col-time">历史分析</th>
            <th class="col-status">状态</th>
            <th class="col-actions">操作</th>
          </tr></thead>
          <tbody>
            ${
              caches.length
                ? caches
                    .map(
                      (cache) => `<tr data-role-cache-row="${escapeHtml(cache.role_id)}">
                        <td class="col-name" title="${escapeHtml(cache.name)}"><strong class="cell-primary">${escapeHtml(cache.name)}</strong></td>
                        <td class="col-role" title="${escapeHtml(cache.role_description || cache.role_name || "")}">${escapeHtml(cache.role_description || cache.role_name)}</td>
                        <td class="col-num">${escapeHtml(cache.question_count ?? 0)}</td>
                        <td class="col-cycle">
                          <label class="cell-inline-control">
                            <input class="form-control" style="width:64px" type="number" min="1" max="365" value="${escapeHtml(cache.interval_days)}" data-cache-interval ${canWrite ? "" : "disabled"} /> 天
                          </label>
                        </td>
                        <td class="col-time">${cache.last_document_analysis_at ? formatDateTimeHtml(cache.last_document_analysis_at) : `<span class="cell-time">尚未执行</span>`}</td>
                        <td class="col-time">${cache.last_history_analysis_at ? formatDateTimeHtml(cache.last_history_analysis_at) : `<span class="cell-time">尚未执行</span>`}</td>
                        <td class="col-status"><span class="badge ${cache.enabled ? "badge-success" : "badge-danger"}">${cache.enabled ? "已启用" : "已停用"}</span></td>
                        <td class="col-actions">
                          <div class="table-actions table-actions-wrap">
                            <button type="button" class="btn btn-text btn-sm" data-cache-detail>查看问题</button>
                            ${
                              canWrite
                                ? `<button type="button" class="btn btn-text btn-sm" data-cache-save>保存设置</button>
                                   <button type="button" class="btn btn-text btn-sm" data-cache-doc>分析文档</button>
                                   <button type="button" class="btn ${cache.enabled ? "btn-danger" : "btn-success"} btn-sm" data-cache-toggle>${cache.enabled ? "停用" : "启用"}</button>`
                                : ""
                            }
                          </div>
                        </td>
                      </tr>`
                    )
                    .join("")
                : `<tr><td colspan="8" class="text-muted">暂无角色缓存配置</td></tr>`
            }
          </tbody>
        </table></div>
      </div>`;

    root.querySelectorAll("[data-role-cache-row]").forEach((row) => {
      const roleId = row.getAttribute("data-role-cache-row");
      const current = caches.find((item) => item.role_id === roleId) || {};
      row.querySelector("[data-cache-detail]").onclick = () =>
        openRoleCacheQuestions(roleId, current.name, { canWrite });
      if (!canWrite) return;

      const save = async (patch) => {
        await api.patch(`/role-caches/${roleId}`, patch);
        toast("缓存配置已保存");
        await pageRoleCaches();
      };
      row.querySelector("[data-cache-save]").onclick = async () => {
        const intervalDays = Number(row.querySelector("[data-cache-interval]").value);
        if (!Number.isInteger(intervalDays) || intervalDays < 1 || intervalDays > 365) {
          toast("检测周期必须是 1-365 天的整数", "error");
          return;
        }
        try {
          await save({ interval_days: intervalDays });
        } catch (error) {
          toast(error.message, "error");
        }
      };
      row.querySelector("[data-cache-toggle]").onclick = async () => {
        try {
          await save({ enabled: !current.enabled });
        } catch (error) {
          toast(error.message, "error");
        }
      };
      row.querySelector("[data-cache-doc]").onclick = () => runRoleCacheAnalysis(roleId, "documents");
    });
  } catch (error) {
    root.innerHTML = `<div class="card empty-state">加载角色缓存失败：${escapeHtml(error.message)}</div>`;
  }
}

/** 管理员手动触发文档或历史分析；请求完成后自动刷新统计。 */
async function runRoleCacheAnalysis(roleId, type) {
  const label = type === "documents" ? "文档分析" : "检测文档";
  toast(`${label}已开始，请等待模型处理完成`);
  try {
    const result = await api.post(`/role-caches/${roleId}/analyze-${type}`, {});
    toast(result.message || `${label}已完成`);
    await pageRoleCaches();
  } catch (error) {
    toast(`${label}失败：${error.message}`, "error");
  }
}

/** 弹窗查看角色缓存中的问题、来源及实际命中次数。 */
async function openRoleCacheQuestions(roleId, cacheName, options = {}) {
  const canWrite = Boolean(options.canWrite);
  try {
    const data = await api.get(`/role-caches/${roleId}/questions?page=1&page_size=100`);
    const items = data.items || [];
    const mask = document.createElement("div");
    mask.className = "modal-mask";
    mask.innerHTML = `
      <div class="modal" role="dialog" aria-modal="true" style="width:min(1000px,calc(100vw - 24px));max-height:90vh;overflow:auto">
        <div class="modal-header" style="display:flex;align-items:center;justify-content:space-between;gap:12px">
          <h3 style="margin:0;min-width:0">${escapeHtml(cacheName || "缓存问题明细")}</h3>
          ${
            canWrite
              ? `<button type="button" class="btn btn-secondary btn-sm" data-cache-detect-doc style="flex-shrink:0;white-space:nowrap">检测文档</button>`
              : ""
          }
        </div>
        <div class="modal-body">
          <p class="text-muted" style="margin-top:0">共 ${escapeHtml(data.total ?? items.length)} 个缓存问题。文档生成与历史高频问题都必须携带知识库来源范围才能被问答链路命中。</p>
          <div class="table-wrap"><table class="table">
            <thead><tr><th>问题</th><th>答案摘要</th><th>来源</th><th>历史频次</th><th>缓存命中</th><th class="col-time">更新时间</th></tr></thead>
            <tbody>
              ${
                items.length
                  ? items
                      .map(
                        (item) => `<tr>
                          <td>${escapeHtml(item.question)}</td>
                          <td style="max-width:320px">${escapeHtml((item.answer || "").slice(0, 160))}${(item.answer || "").length > 160 ? "…" : ""}</td>
                          <td>${item.source === "history_frequent" ? "历史高频" : "文档生成"}</td>
                          <td>${escapeHtml(item.occurrence_count ?? 1)}</td>
                          <td>${escapeHtml(item.hit_count ?? 0)}</td>
                          <td class="col-time">${formatDateTimeHtml(item.updated_at)}</td>
                        </tr>`
                      )
                      .join("")
                  : `<tr><td colspan="6" class="text-muted">尚未生成缓存问题</td></tr>`
              }
            </tbody>
          </table></div>
        </div>
        <div class="modal-footer"><button type="button" class="btn btn-secondary" data-close>关闭</button></div>
      </div>`;
    document.body.appendChild(mask);
    mask.querySelector("[data-close]").onclick = () => mask.remove();
    const detectBtn = mask.querySelector("[data-cache-detect-doc]");
    if (detectBtn) {
      detectBtn.onclick = async () => {
        detectBtn.disabled = true;
        try {
          await runRoleCacheAnalysis(roleId, "history");
        } finally {
          detectBtn.disabled = false;
        }
      };
    }
    mask.addEventListener("click", (event) => {
      if (event.target === mask) mask.remove();
    });
  } catch (error) {
    toast(`加载缓存问题失败：${error.message}`, "error");
  }
}

/** 加载并弹窗展示单个会话中每一轮的 Query 预处理结果。 */
async function openQaSessionDetail(sessionId) {
  try {
    const data = await api.get(`/qa/admin/sessions/${sessionId}`);
    const session = data.session || {};
    const messages = data.messages || [];
    const turns = [];
    let pendingQuestion = null;
    messages.forEach((message) => {
      if (message.role === "user") {
        pendingQuestion = message;
        return;
      }
      if (message.role === "assistant") {
        turns.push({ question: pendingQuestion, answer: message });
        pendingQuestion = null;
      }
    });

    const turnHtml = turns.length
      ? turns
          .map((turn, index) => {
            const meta = turn.answer?.retrieval_meta || {};
            const processing = meta.query_processing || {};
            const original = processing.original_query || meta.original_query || turn.question?.content || "-";
            const rewritten = processing.rewritten_query || meta.rewritten_query || original;
            const expansions = Array.isArray(processing.expanded_queries) ? processing.expanded_queries : [];
            const hyde = processing.hyde_document || "";
            const rerank = meta.rerank || {};
            const intent = meta.intent || {};
            return `
              <div class="card" style="margin-bottom:12px;background:var(--color-bg-tint,#f8f9fa)">
                <div style="display:flex;justify-content:space-between;gap:12px;align-items:center">
                  <strong>第 ${index + 1} 轮</strong>
                  <span class="badge">${processing.applied ? "已执行预处理" : processing.error ? "已回退原 Query" : "历史记录未包含预处理"}</span>
                </div>
                <div style="display:grid;grid-template-columns:120px minmax(0,1fr);gap:8px 12px;margin-top:12px;line-height:1.65">
                  <span class="text-muted">原始 Query</span><div>${escapeHtml(original)}</div>
                  <span class="text-muted">识别意图</span><div>${intent.name ? escapeHtml(guardIntentLabel(intent.name)) : "历史记录未包含意图"} ${formatPercentSafe(intent.confidence, intent.detector === "llm" ? "LLM 分类器" : "本地规则")}</div>
                  <span class="text-muted">改写 Query</span><div>${escapeHtml(rewritten)}</div>
                  <span class="text-muted">扩展 Query</span><div>${expansions.length ? expansions.map((item) => `<code style="display:inline-block;margin:0 6px 6px 0">${escapeHtml(item)}</code>`).join("") : "-"}</div>
                  <span class="text-muted">HyDE 假设文档</span><div style="white-space:pre-wrap">${hyde ? escapeHtml(hyde) : "-"}</div>
                  <span class="text-muted">检索结果</span><div>命中 ${escapeHtml(meta.hit_count ?? 0)} 段；扩展 Query ${escapeHtml(meta.expanded_query_count ?? expansions.length)} 条；HyDE ${meta.hyde_used ? "已参与向量检索" : "未参与"}</div>
                  <span class="text-muted">Rerank</span><div>${rerank.applied ? `${escapeHtml(rerank.provider || "-")} / ${escapeHtml(rerank.model || "-")}` : `未应用${rerank.error ? `（${escapeHtml(rerank.error)}）` : ""}`}</div>
                  <span class="text-muted">最终回答</span><div style="white-space:pre-wrap">${escapeHtml(turn.answer?.content || "-")}</div>
                </div>
              </div>`;
          })
          .join("")
      : `<div class="empty-state">该会话暂无完整问答轮次</div>`;

    const mask = document.createElement("div");
    mask.className = "modal-mask";
    mask.innerHTML = `
      <div class="modal" role="dialog" aria-modal="true" style="width:min(960px,calc(100vw - 24px));max-height:90vh;overflow:auto">
        <div class="modal-header"><h3>${escapeHtml(session.title || "会话详情")}</h3></div>
        <div class="modal-body">
          <p class="text-muted" style="margin-top:0">用户：${escapeHtml(session.owner || "-")} · 消息 ${escapeHtml(session.message_count ?? messages.length)} 条 · 最后活跃 ${formatDateTime(session.last_active_at)}</p>
          ${turnHtml}
        </div>
        <div class="modal-footer"><button type="button" class="btn btn-secondary" data-close>关闭</button></div>
      </div>`;
    document.body.appendChild(mask);
    mask.querySelector("[data-close]").onclick = () => mask.remove();
    mask.addEventListener("click", (event) => {
      if (event.target === mask) mask.remove();
    });
  } catch (error) {
    toast(`加载会话详情失败：${error.message}`, "error");
  }
}

async function pageAudit() {
  if (!requirePerm("audit:read", "审计日志")) return;
  document.getElementById("pageRoot").innerHTML = `<div class="loading">加载审计…</div>`;

  const AUDIT_PAGE_SIZE = 15;
  let listPage = 1;
  let auditTotalPages = 1;
  let filters = { action: "", resource_type: "", result: "" };
  /** @type {Map<string, object>} */
  let pageItemMap = new Map();

  /** 解析「1-5、8、11-13」为页码列表（1-based，受 maxPage 约束） */
  const parsePageSpec = (spec, maxPage) => {
    const max = Math.max(1, Number(maxPage) || 1);
    const pages = new Set();
    const parts = String(spec || "")
      .split(/[,，、;\s]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    for (const part of parts) {
      const range = part.match(/^(\d+)\s*[-~～—–到至]\s*(\d+)$/);
      if (range) {
        let a = Number(range[1]);
        let b = Number(range[2]);
        if (!Number.isFinite(a) || !Number.isFinite(b)) continue;
        if (a > b) [a, b] = [b, a];
        for (let p = a; p <= b; p += 1) {
          if (p >= 1 && p <= max) pages.add(p);
        }
        continue;
      }
      const single = part.match(/^(\d+)$/);
      if (single) {
        const p = Number(single[1]);
        if (p >= 1 && p <= max) pages.add(p);
      }
    }
    return Array.from(pages).sort((a, b) => a - b);
  };

  const actionLabel = (code) => AUDIT_ACTION_LABELS[code] || code || "-";
  const resourceLabel = (code) => AUDIT_RESOURCE_LABELS[code] || code || "-";

  const actorName = (a) => a.user_name || (a.user_id ? String(a.user_id).slice(0, 8) + "…" : "系统");

  const csvEscape = (value) => {
    const s = String(value ?? "");
    if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
    return s;
  };

  const downloadCsv = (filename, header, rows) => {
    const lines = [header, ...rows].map((cols) => cols.map(csvEscape).join(","));
    const blob = new Blob(["\uFEFF" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  const auditToCsvRow = (a) => [
    actorName(a),
    actionLabel(a.action),
    a.action || "",
    resourceLabel(a.resource_type),
    a.resource_id || "",
    a.request_id || "",
    a.result === "success" ? "成功" : a.result || "失败",
    formatDateTime(a.created_at),
    a.ip_address || "",
    a.error_message || "",
  ];

  const CSV_HEADER = [
    "操作者",
    "动作",
    "动作代码",
    "资源",
    "资源ID",
    "请求标识",
    "结果",
    "时间",
    "IP",
    "错误信息",
  ];

  const fetchAuditPage = async (page, pageSize, filterOverride = null) => {
    const f = filterOverride === null ? filters : filterOverride;
    const qs = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
    });
    if (f.action) qs.set("action", f.action);
    if (f.resource_type) qs.set("resource_type", f.resource_type);
    if (f.result) qs.set("result", f.result);
    return api.get(`/audit/logs?${qs.toString()}`);
  };

  const fetchAuditAll = async (filterOverride = null) => {
    const all = [];
    let page = 1;
    let total = Infinity;
    const pageSize = 100;
    while (all.length < total) {
      const data = await fetchAuditPage(page, pageSize, filterOverride);
      const chunk = data.items || [];
      total = Number(data.total ?? all.length + chunk.length) || 0;
      all.push(...chunk);
      if (!chunk.length || all.length >= total || page > 500) break;
      page += 1;
    }
    return all;
  };

  const fetchAuditPages = async (pageNumbers) => {
    const all = [];
    const seen = new Set();
    for (const p of pageNumbers) {
      const data = await fetchAuditPage(p, AUDIT_PAGE_SIZE);
      for (const item of data.items || []) {
        const id = String(item.id);
        if (seen.has(id)) continue;
        seen.add(id);
        all.push(item);
      }
    }
    return all;
  };

  const runAuditExport = async (mode, pageSpec = "") => {
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
    try {
      if (mode === "selected") {
        const ids = Array.from(document.querySelectorAll(".audit-row-check:checked")).map((el) => el.value);
        if (!ids.length) return toast("请先勾选要导出的记录", "error");
        const rows = ids.map((id) => pageItemMap.get(id)).filter(Boolean);
        if (!rows.length) return toast("未找到可导出的记录", "error");
        downloadCsv(`audit-selected-${stamp}.csv`, CSV_HEADER, rows.map(auditToCsvRow));
        toast(`已导出勾选 ${rows.length} 条`, "success");
        return;
      }
      if (mode === "pages") {
        const pages = parsePageSpec(pageSpec, auditTotalPages);
        if (!pages.length) {
          return toast(`请输入有效页码（1-${auditTotalPages}），例如1-5、 8、 11-13`, "error");
        }
        toast(`正在导出第 ${pages.join("、")} 页…`);
        const rows = await fetchAuditPages(pages);
        if (!rows.length) return toast("指定页没有可导出的记录", "error");
        downloadCsv(`audit-pages-${stamp}.csv`, CSV_HEADER, rows.map(auditToCsvRow));
        toast(`已导出 ${pages.length} 页共 ${rows.length} 条`, "success");
        return;
      }
      if (mode === "all") {
        toast("正在全库导出，请稍候…");
        const rows = await fetchAuditAll({ action: "", resource_type: "", result: "" });
        downloadCsv(`audit-all-${stamp}.csv`, CSV_HEADER, rows.map(auditToCsvRow));
        toast(`已全库导出 ${rows.length} 条`, "success");
        return;
      }
      toast("未知导出方式", "error");
    } catch (e) {
      toast(e.message || "导出失败", "error");
    }
  };

  const chooseAuditExport = async () => {
    const selectedCount = document.querySelectorAll(".audit-row-check:checked").length;
    const result = await openWideModal({
      title: "导出 CSV",
      width: "min(400px, calc(100vw - 32px))",
      panelClass: "audit-export-modal",
      bodyHtml: `
        <div class="audit-export-options">
          <div class="audit-export-pages">
            <div class="audit-export-section-title">页面</div>
            <label class="audit-export-option">
              <input type="radio" name="auditExportMode" value="all" checked />
              <span class="audit-export-label">全部</span>
            </label>
            <div class="audit-export-option audit-export-option-pages">
              <input type="radio" name="auditExportMode" value="pages" id="auditExportModePages" />
              <input
                type="text"
                id="auditExportPageSpec"
                class="audit-export-page-input"
                placeholder="例如1-5、 8、 11-13"
                value=""
                autocomplete="off"
                inputmode="text"
                aria-label="导出页码"
              />
            </div>
          </div>
          <label class="audit-export-option${selectedCount ? "" : " is-disabled"}" style="cursor:${selectedCount ? "pointer" : "not-allowed"}">
            <input type="radio" name="auditExportMode" value="selected" ${selectedCount ? "" : "disabled"} />
            <span class="audit-export-label">已选数据（${selectedCount} 条）</span>
          </label>
        </div>`,
      actionsHtml: `
        <button type="button" class="btn btn-secondary" data-act="cancel">取消</button>
        <button type="button" class="btn" data-act="ok">开始导出</button>`,
      onReady: (root) => {
        const input = root.querySelector("#auditExportPageSpec");
        const pagesRadio = root.querySelector("#auditExportModePages");
        const activatePages = () => {
          if (pagesRadio && !pagesRadio.disabled) pagesRadio.checked = true;
        };
        input?.addEventListener("focus", activatePages);
        input?.addEventListener("input", activatePages);
        input?.addEventListener("click", activatePages);
      },
    });
    if (!result?.ok) return;
    const root = result.root;
    const mode = root.querySelector('input[name="auditExportMode"]:checked')?.value || "all";
    const pageSpec = root.querySelector("#auditExportPageSpec")?.value?.trim() || "";
    root.remove();
    await runAuditExport(mode, pageSpec);
  };

  const openAuditDetail = async (id) => {
    try {
      const d = await api.get(`/audit/logs/${id}`);
      const detail = d.detail || {};
      await openWideModal({
        title: "审计详情",
        bodyHtml: `
          <p><span class="text-muted">动作：</span>${escapeHtml(actionLabel(d.action))}
            <code style="margin-left:8px">${escapeHtml(d.action)}</code></p>
          <p><span class="text-muted">操作者：</span>${escapeHtml(d.user_name || d.user_id || "系统")}</p>
          <p><span class="text-muted">资源：</span>${escapeHtml(resourceLabel(d.resource_type))}
            · ${escapeHtml(d.resource_id || "—")}</p>
          <p><span class="text-muted">请求标识：</span>${escapeHtml(d.request_id || "—")}</p>
          <p><span class="text-muted">IP / UA：</span>${escapeHtml(d.ip_address || "—")}
            · ${escapeHtml((d.user_agent || "—").slice(0, 80))}</p>
          <p><span class="text-muted">结果：</span>${
            d.result === "success"
              ? `<span class="badge badge-success">成功</span>`
              : `<span class="badge badge-danger">${escapeHtml(
                  d.result === "failure" ? "失败" : d.result || "失败"
                )}</span>`
          }
            ${d.error_message ? ` · ${escapeHtml(d.error_message)}` : ""}</p>
          <p><span class="text-muted">时间：</span>${formatDateTime(d.created_at)}</p>
          ${
            detail.before_version || detail.after_version
              ? `<p><span class="text-muted">索引版本：</span>
                <code>${escapeHtml(detail.before_version || "—")}</code>
                → <code>${escapeHtml(detail.after_version || "—")}</code></p>`
              : ""
          }
          <h4 style="margin:12px 0 8px;font-size:14px">变更明细</h4>
          <pre style="background:var(--color-bg-tint);padding:12px;border-radius:8px;overflow:auto;max-height:240px;font-size:12px">${escapeHtml(
            JSON.stringify(detail, null, 2) || "{}"
          )}</pre>`,
        actionsHtml: `<button type="button" class="btn btn-secondary" data-act="cancel">关闭</button>`,
      });
    } catch (e) {
      toast(e.message || "加载详情失败", "error");
    }
  };

  const load = async () => {
    const data = await fetchAuditPage(listPage, AUDIT_PAGE_SIZE);
    const items = data.items || [];
    const total = Number(data.total ?? items.length) || 0;
    const totalPages = Math.max(1, Math.ceil(total / AUDIT_PAGE_SIZE) || 1);
    auditTotalPages = totalPages;
    if (listPage > totalPages) {
      listPage = totalPages;
      return load();
    }
    pageItemMap = new Map(items.map((a) => [String(a.id), a]));

    const { buttons: pageButtons, jump: pageJump } = renderCompactPagerParts(listPage, totalPages);

    document.getElementById("pageRoot").innerHTML = `
      ${pageHead({
        title: "审计日志",
        desc: "记录操作者、时间、对象、请求标识与结果。可按全部页面 / 指定页码 / 已选数据导出 CSV。",
      })}
      <div class="card panel-fill">
        <div class="card-header">
          <div class="card-header-text">
            <h3 class="card-title">操作审计</h3>
            <p class="card-sub" id="auditListSub">共 ${escapeHtml(total)} 条 · 第 ${listPage}/${totalPages} 页 · 每页 ${AUDIT_PAGE_SIZE} 条 · 已选 0 条</p>
          </div>
          <div class="card-header-actions">
            <select class="form-control" id="auditAction" style="width:160px;height:32px">
              <option value="">全部动作</option>
              <option value="snapshot.">快照相关</option>
              <option value="doc.">文档相关</option>
              <option value="kb.">知识库相关</option>
              <option value="user.">用户相关</option>
              <option value="role.">角色相关</option>
            </select>
            <select class="form-control" id="auditResource" style="width:140px;height:32px">
              <option value="">全部资源</option>
              <option value="snapshot">快照</option>
              <option value="kb">知识库</option>
              <option value="document">文档</option>
              <option value="user">用户</option>
              <option value="role">角色</option>
            </select>
            <select class="form-control" id="auditResult" style="width:120px;height:32px">
              <option value="">全部结果</option>
              <option value="success">成功</option>
              <option value="failure">失败</option>
            </select>
            <button type="button" class="btn btn-danger btn-sm" id="btnAuditBatchDelete" disabled>批量删除</button>
            <button type="button" class="btn btn-sm" id="btnAuditBatchExport">批量导出 CSV</button>
          </div>
        </div>
        <div class="table-wrap"><table class="table table-audit">
          <colgroup>
            <col class="audit-col-check" />
            <col class="audit-col-index" />
            <col class="audit-col-actor" />
            <col class="audit-col-action" />
            <col class="audit-col-resource" />
            <col class="audit-col-rid" />
            <col class="audit-col-req" />
            <col class="audit-col-result" />
            <col class="audit-col-time" />
            <col class="audit-col-actions" />
          </colgroup>
          <thead><tr>
            <th class="col-check"><input type="checkbox" id="auditSelectAll" title="全选当前页" aria-label="全选当前页" ${items.length ? "" : "disabled"} /></th>
            <th class="col-index">序号</th>
            <th class="col-name">操作者</th>
            <th class="col-action">动作</th>
            <th class="col-resource">资源</th>
            <th class="col-id">资源 ID</th>
            <th class="col-id">请求标识</th>
            <th class="col-status">结果</th>
            <th class="col-time">时间</th>
            <th class="col-actions col-actions-detail">操作</th>
          </tr></thead>
          <tbody>${
            items.length
              ? items
                  .map((a, i) => {
                    const seq = (listPage - 1) * AUDIT_PAGE_SIZE + i + 1;
                    return `<tr>
                <td class="col-check"><input type="checkbox" class="audit-row-check" value="${escapeHtml(a.id)}" aria-label="选择第 ${seq} 条" /></td>
                <td class="col-index">${seq}</td>
                <td class="col-name" title="${escapeHtml(actorName(a))}">${escapeHtml(actorName(a))}</td>
                <td class="col-action" title="${escapeHtml(a.action)}">${escapeHtml(actionLabel(a.action))}</td>
                <td class="col-resource" title="${escapeHtml(resourceLabel(a.resource_type))}">${escapeHtml(resourceLabel(a.resource_type))}</td>
                <td class="col-id text-muted" title="${escapeHtml(a.resource_id || "")}">${escapeHtml(a.resource_id || "—")}</td>
                <td class="col-id text-muted" title="${escapeHtml(a.request_id || "")}">${escapeHtml(a.request_id || "—")}</td>
                <td class="col-status">${
                  a.result === "success"
                    ? `<span class="badge badge-success">成功</span>`
                    : `<span class="badge badge-danger">${escapeHtml(
                        a.result === "failure" ? "失败" : a.result || "失败"
                      )}</span>`
                }</td>
                <td class="col-time">${formatDateTimeHtml(a.created_at)}</td>
                <td class="col-actions col-actions-detail"><button type="button" class="btn btn-text btn-sm" data-audit="${escapeHtml(a.id)}">详情</button></td>
              </tr>`;
                  })
                  .join("")
              : `<tr><td colspan="10" class="text-muted">暂无符合条件的审计记录</td></tr>`
          }</tbody>
        </table></div>
        ${
          total > 0
            ? `<div class="table-card-footer">
                <div class="table-card-footer-start"></div>
                <div class="pager pager-center" id="auditPager">
                  <button type="button" class="btn btn-secondary btn-sm" data-page-prev ${listPage <= 1 ? "disabled" : ""}>上一页</button>
                  ${pageButtons}
                  <button type="button" class="btn btn-secondary btn-sm" data-page-next ${listPage >= totalPages ? "disabled" : ""}>下一页</button>
                  ${pageJump}
                </div>
              </div>`
            : ""
        }
      </div>`;

    const actionEl = document.getElementById("auditAction");
    const resourceEl = document.getElementById("auditResource");
    const resultEl = document.getElementById("auditResult");
    if (actionEl) actionEl.value = filters.action || "";
    if (resourceEl) resourceEl.value = filters.resource_type || "";
    if (resultEl) resultEl.value = filters.result || "";

    const readFilters = () => ({
      action: (actionEl && actionEl.value) || "",
      resource_type: (resourceEl && resourceEl.value) || "",
      result: (resultEl && resultEl.value) || "",
    });

    const applyFilters = async () => {
      filters = readFilters();
      listPage = 1;
      try {
        await load();
      } catch (e) {
        toast(e.message || "筛选失败", "error");
      }
    };

    [actionEl, resourceEl, resultEl].forEach((el) => {
      if (el) el.onchange = applyFilters;
    });

    const syncBatchState = () => {
      const selectAll = document.getElementById("auditSelectAll");
      const sub = document.getElementById("auditListSub");
      const btnDel = document.getElementById("btnAuditBatchDelete");
      const checks = Array.from(document.querySelectorAll(".audit-row-check"));
      const selected = checks.filter((c) => c.checked);
      if (selectAll && checks.length) {
        selectAll.checked = selected.length === checks.length;
        selectAll.indeterminate = selected.length > 0 && selected.length < checks.length;
      } else if (selectAll) {
        selectAll.checked = false;
        selectAll.indeterminate = false;
      }
      if (btnDel) btnDel.disabled = selected.length === 0;
      if (sub) {
        sub.textContent = `共 ${total} 条 · 第 ${listPage}/${totalPages} 页 · 每页 ${AUDIT_PAGE_SIZE} 条 · 已选 ${selected.length} 条`;
      }
    };

    const selectAll = document.getElementById("auditSelectAll");
    if (selectAll) {
      selectAll.onchange = () => {
        document.querySelectorAll(".audit-row-check").forEach((cb) => {
          cb.checked = selectAll.checked;
        });
        syncBatchState();
      };
    }
    document.querySelectorAll(".audit-row-check").forEach((cb) => {
      cb.onchange = () => syncBatchState();
    });
    syncBatchState();

    document.getElementById("btnAuditBatchExport")?.addEventListener("click", chooseAuditExport);

    const btnBatchDelete = document.getElementById("btnAuditBatchDelete");
    if (btnBatchDelete) {
      btnBatchDelete.onclick = async () => {
        const ids = Array.from(document.querySelectorAll(".audit-row-check:checked")).map((el) => el.value);
        if (!ids.length) return toast("请先勾选要删除的审计记录", "error");
        const ok = await confirmDialog({
          title: "批量删除",
          message: `将删除已勾选的 ${ids.length} 条审计记录，删除后不可恢复，确定？`,
          confirmText: "批量删除",
          danger: true,
        });
        if (!ok) return;
        try {
          const res = await api.post("/audit/logs/batch-delete", { ids });
          const deleted = Number(res?.deleted ?? ids.length) || 0;
          toast(`已删除 ${deleted} 条`, "success");
          await load();
        } catch (e) {
          toast(e.message || "批量删除失败", "error");
        }
      };
    }

    const pager = document.getElementById("auditPager");
    if (pager) {
      bindCompactPager(pager, {
        page: listPage,
        totalPages,
        onGo: async (p) => {
          listPage = p;
          await load();
        },
      });
    }

    document.querySelectorAll("[data-audit]").forEach((btn) => {
      btn.onclick = () => openAuditDetail(btn.getAttribute("data-audit"));
    });
  };

  try {
    await load();
  } catch (e) {
    document.getElementById("pageRoot").innerHTML = `<div class="card text-danger">${escapeHtml(e.message)}</div>`;
  }
}

/* ========== 系统监控（Grafana 嵌入） ========== */
let monitorHealthTimer = null;

async function pageMonitor() {
  if (!requirePerm("system:read", "系统监控")) return;
  if (monitorHealthTimer) {
    clearInterval(monitorHealthTimer);
    monitorHealthTimer = null;
  }

  const HEALTH_LABELS = {
    postgres: "PostgreSQL",
    redis: "Redis",
    chroma: "Chroma",
    langfuse: "Langfuse",
    minio: "MinIO",
  };

  const healthLampClass = (status) => {
    const s = String(status || "").toLowerCase();
    if (s === "healthy" || s === "ok") return "is-healthy";
    if (s === "degraded") return "is-degraded";
    return "is-unhealthy";
  };

  const renderHealthChecks = (health) => {
    const badge = document.getElementById("monitorHealthBadge");
    const uptime = document.getElementById("monitorHealthUptime");
    const list = document.getElementById("monitorHealthList");
    if (!list) return;
    const status = health?.status || "unknown";
    if (badge) {
      const lamp = healthLampClass(status);
      badge.className = `monitor-live-badge ${lamp}`;
      badge.innerHTML = `<span class="health-lamp ${lamp}" aria-hidden="true"></span><span>实时刷新中</span>`;
      badge.title = `整体状态：${status}`;
    }
    if (uptime) {
      uptime.textContent =
        health?.uptime_seconds != null ? `Uptime ${health.uptime_seconds}s · 每 10 秒自动刷新` : "组件状态一览 · 每 10 秒自动刷新";
    }
    const entries = Object.entries(health?.checks || {});
    list.innerHTML = entries.length
      ? entries
          .map(([k, v]) => {
            const st = typeof v === "object" ? v.status : v;
            const latency =
              typeof v === "object" && v.latency_ms != null
                ? `延迟（${v.latency_ms}ms）`
                : st && String(st).toLowerCase() !== "healthy"
                  ? escapeHtml(String(st))
                  : "";
            const label = HEALTH_LABELS[k] || k;
            return `<li class="health-check-item">
              <span class="health-lamp ${healthLampClass(st)}" title="${escapeHtml(String(st))}" aria-hidden="true"></span>
              <span class="health-check-name">${escapeHtml(label)}</span>
              <span class="health-check-meta">${latency}</span>
            </li>`;
          })
          .join("")
      : `<li class="text-muted">无组件检查数据</li>`;
  };

  const refreshHealth = async () => {
    if (!currentPath().includes("/admin/monitor")) {
      if (monitorHealthTimer) {
        clearInterval(monitorHealthTimer);
        monitorHealthTimer = null;
      }
      return;
    }
    try {
      const health = await api.get("/monitor/health");
      renderHealthChecks(health);
    } catch {
      const list = document.getElementById("monitorHealthList");
      if (list) {
        list.innerHTML = `<li class="health-check-item">
          <span class="health-lamp is-unhealthy" aria-hidden="true"></span>
          <span class="health-check-name">健康检查</span>
          <span class="health-check-meta text-danger">刷新失败</span>
        </li>`;
      }
    }
  };

  let health = { status: "unknown", checks: {} };
  let stats = null;
  try {
    health = await api.get("/monitor/health");
  } catch {
    /* ignore */
  }
  try {
    stats = await api.get("/monitor/stats");
  } catch (e) {
    stats = { error: e.message };
  }
  const statsHtml =
    stats && !stats.error
      ? `<ul class="list-plain monitor-stats-list">
        <li><span class="monitor-stat-label">用户数</span><span class="monitor-stat-value">${stats.user_count ?? 0}</span></li>
        <li><span class="monitor-stat-label">知识库</span><span class="monitor-stat-value">${stats.kb_count ?? 0}</span></li>
        <li><span class="monitor-stat-label">文档数</span><span class="monitor-stat-value">${stats.doc_count ?? 0}</span></li>
        <li><span class="monitor-stat-label">活跃会话</span><span class="monitor-stat-value">${stats.active_sessions ?? 0}</span></li>
        <li><span class="monitor-stat-label">任务队列</span><span class="monitor-stat-value">${stats.task_queue_size ?? 0}</span></li>
        <li><span class="monitor-stat-label">LLM Guard 近 24 小时阻拦</span><span class="monitor-stat-value">${stats.guard_blocked_24h ?? 0}</span></li>
        <li><span class="monitor-stat-label">LLM Guard 近 7 天阻拦</span><span class="monitor-stat-value">${stats.guard_blocked_7d ?? 0}</span></li>
      </ul>`
      : `<p class="text-muted">${escapeHtml(stats?.error || "暂无统计")}</p>`;
  document.getElementById("pageRoot").innerHTML = `
    ${pageHead({
      title: "系统监控",
      desc: "健康检查、运行统计与 Grafana 面板。",
    })}
    <div class="page-grid monitor-page-grid">
    <div class="card span-6 monitor-equal-card">
      <div class="card-header">
        <div class="card-header-text"><h3 class="card-title">健康检查</h3></div>
        <span class="monitor-live-badge is-healthy" id="monitorHealthBadge" title="整体状态加载中">
          <span class="health-lamp is-healthy" aria-hidden="true"></span><span>实时刷新中</span>
        </span>
      </div>
      <p class="page-desc" id="monitorHealthUptime" style="margin-bottom:12px">${
        health.uptime_seconds != null ? `Uptime ${health.uptime_seconds}s · 每 10 秒自动刷新` : "组件状态一览 · 每 10 秒自动刷新"
      }</p>
      <ul class="list-plain health-check-list" id="monitorHealthList"></ul>
    </div>
    <div class="card span-6 monitor-equal-card">
      <div class="card-header">
        <div class="card-header-text"><h3 class="card-title">系统统计</h3></div>
      </div>
      <div class="monitor-stats-body">${statsHtml}</div>
    </div>
    <div class="card span-12">
      <div class="card-header">
        <div class="card-header-text">
          <h3 class="card-title">Grafana 面板</h3>
          <p class="card-sub">经 Nginx 反代嵌入本地 Grafana（匿名只读）</p>
        </div>
        <div class="card-header-actions">
          <a class="btn btn-secondary btn-sm" href="/grafana/d/rag-overview/overview?orgId=1&kiosk&theme=dark" target="_blank" rel="noopener">打开 Overview</a>
          <a class="btn btn-text btn-sm" href="/grafana/" target="_blank" rel="noopener">Grafana</a>
        </div>
      </div>
      <div class="embed-frame" style="padding:0;min-height:520px">
        <iframe
          title="Grafana"
          src="/grafana/d/rag-overview/overview?orgId=1&kiosk&theme=dark"
          style="width:100%;height:520px;border:0;border-radius:16px;background:#0b0f19"
          loading="lazy"
          referrerpolicy="same-origin"
          allow="fullscreen"
        ></iframe>
      </div>
    </div>
    </div>`;

  renderHealthChecks(health);
  monitorHealthTimer = setInterval(refreshHealth, 10000);
}

/* ========== LLM Guard 拦截详情 ========== */
async function pageGuardEvents() {
  if (!requirePerm("system:read", "LLM Guard 拦截")) return;
  const canOpenUsers = hasPermission("user:read");
  document.getElementById("pageRoot").innerHTML = `<div class="loading">加载拦截记录…</div>`;
  let data = { items: [], total: 0, blocked_24h: 0, blocked_7d: 0 };
  try {
    data = (await api.get("/monitor/guard-events?page=1&page_size=50")) || data;
  } catch (e) {
    document.getElementById("pageRoot").innerHTML = `<div class="card text-danger">${escapeHtml(e.message || "加载失败")}</div>`;
    return;
  }
  const items = data.items || [];
  document.getElementById("pageRoot").innerHTML = `
    ${pageHead({
      title: "LLM Guard 拦截",
      desc: "恶意访问阻拦审计：账号、来源 IP、意图与原因码。不含用户完整问题原文。",
      actions: `<button type="button" class="btn btn-secondary btn-sm" id="btnGuardRefresh">刷新</button>`,
    })}
    <div class="page-grid">
      <div class="card span-6">
        <div class="card-header"><div class="card-header-text"><h3 class="card-title">近 24 小时</h3></div></div>
        <div class="value" style="font-size:28px;font-weight:700">${escapeHtml(data.blocked_24h ?? 0)}</div>
      </div>
      <div class="card span-6">
        <div class="card-header"><div class="card-header-text"><h3 class="card-title">近 7 天</h3></div></div>
        <div class="value" style="font-size:28px;font-weight:700">${escapeHtml(data.blocked_7d ?? 0)}</div>
      </div>
      <div class="card span-12">
        <div class="card-header">
          <div class="card-header-text">
            <h3 class="card-title">阻拦记录</h3>
            <p class="card-sub">共 ${escapeHtml(data.total ?? items.length)} 条，展示最近 ${items.length} 条</p>
          </div>
        </div>
        <div class="table-wrap"><table class="table">
          <thead><tr>
            <th class="col-time">时间</th><th>账号</th><th>来源 IP</th><th>意图</th><th>原因码</th><th>检测层</th><th>置信度</th><th>摘要</th><th></th>
          </tr></thead>
          <tbody>
            ${
              items.length
                ? items
                    .map((event) => {
                      const registered = event.is_registered && event.user_id;
                      const userBtn =
                        registered && canOpenUsers
                          ? `<button type="button" class="btn btn-secondary btn-sm" data-goto-user="${escapeHtml(String(event.user_id))}">用户管理</button>`
                          : registered
                            ? `<span class="cell-muted">已注册</span>`
                            : `<span class="cell-muted">—</span>`;
                      return `<tr>
                        <td class="col-time">${formatDateTimeHtml(event.created_at)}</td>
                        <td><strong>${escapeHtml(event.actor_label || "访客")}</strong></td>
                        <td><code>${escapeHtml(event.client_ip || "-")}</code></td>
                        <td>${escapeHtml(guardIntentLabel(event.intent))}</td>
                        <td><code>${escapeHtml(event.reason_code)}</code></td>
                        <td>${event.detector === "llm" ? "LLM 分类器" : "本地规则"}</td>
                        <td>${formatPercentCell(event.confidence)}</td>
                        <td class="text-muted" style="max-width:220px;font-size:12px">${escapeHtml(event.question_preview || "-")}</td>
                        <td class="col-actions"><div class="table-actions">${userBtn}</div></td>
                      </tr>`;
                    })
                    .join("")
                : `<tr><td colspan="9" class="text-muted">最近没有恶意访问阻拦记录</td></tr>`
            }
          </tbody>
        </table></div>
      </div>
    </div>`;

  document.getElementById("btnGuardRefresh")?.addEventListener("click", () => pageGuardEvents());
  document.querySelectorAll("[data-goto-user]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const uid = btn.getAttribute("data-goto-user");
      if (uid) navigate(`/admin/users?user=${encodeURIComponent(uid)}`);
    });
  });
}

/** 简易 Markdown → HTML（接入指南展示用；覆盖标题/列表/表格/代码块） */
function renderSimpleMarkdown(md) {
  const src = String(md || "").replace(/\r\n/g, "\n");
  const lines = src.split("\n");
  const html = [];
  let i = 0;
  let inCode = false;
  let codeLang = "";
  let codeBuf = [];
  let inTable = false;
  let tableRows = [];

  const flushCode = () => {
    if (!inCode) return;
    html.push(
      `<pre class="md-pre"><code class="language-${escapeHtml(codeLang)}">${escapeHtml(codeBuf.join("\n"))}</code></pre>`
    );
    inCode = false;
    codeLang = "";
    codeBuf = [];
  };

  const flushTable = () => {
    if (!inTable) return;
    const rows = tableRows.filter((r) => r.length);
    tableRows = [];
    inTable = false;
    if (!rows.length) return;
    const isSep = (cells) => cells.every((c) => /^:?-{3,}:?$/.test(c.trim()));
    let head = rows[0];
    let body = rows.slice(1);
    if (body.length && isSep(body[0])) body = body.slice(1);
    const th = head.map((c) => `<th>${inlineMd(c)}</th>`).join("");
    const tr = body
      .map((r) => `<tr>${r.map((c) => `<td>${inlineMd(c)}</td>`).join("")}</tr>`)
      .join("");
    html.push(`<div class="table-wrap"><table class="table md-table"><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table></div>`);
  };

  const inlineMd = (text) => {
    let t = escapeHtml(text);
    t = t.replace(/`([^`]+)`/g, "<code>$1</code>");
    t = t.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    t = t.replace(
      /\[([^\]]+)\]\(([^)]+)\)/g,
      (_, label, href) =>
        `<a href="${escapeHtml(href)}" target="_blank" rel="noopener">${label}</a>`
    );
    return t;
  };

  while (i < lines.length) {
    const line = lines[i];
    if (line.startsWith("```")) {
      flushTable();
      if (inCode) flushCode();
      else {
        inCode = true;
        codeLang = line.slice(3).trim();
        codeBuf = [];
      }
      i += 1;
      continue;
    }
    if (inCode) {
      codeBuf.push(line);
      i += 1;
      continue;
    }
    if (/^\|(.+)\|$/.test(line.trim()) || (line.includes("|") && /^\s*\|/.test(line))) {
      const cells = line
        .trim()
        .replace(/^\|/, "")
        .replace(/\|$/, "")
        .split("|")
        .map((c) => c.trim());
      if (!inTable) inTable = true;
      tableRows.push(cells);
      i += 1;
      continue;
    }
    flushTable();
    if (!line.trim()) {
      i += 1;
      continue;
    }
    if (line.startsWith("#### ")) {
      html.push(`<h4>${inlineMd(line.slice(5))}</h4>`);
    } else if (line.startsWith("### ")) {
      html.push(`<h3>${inlineMd(line.slice(4))}</h3>`);
    } else if (line.startsWith("## ")) {
      html.push(`<h2>${inlineMd(line.slice(3))}</h2>`);
    } else if (line.startsWith("# ")) {
      html.push(`<h1>${inlineMd(line.slice(2))}</h1>`);
    } else if (/^>\s?/.test(line)) {
      html.push(`<blockquote class="md-quote">${inlineMd(line.replace(/^>\s?/, ""))}</blockquote>`);
    } else if (/^[-*]\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^[-*]\s+/.test(lines[i])) {
        items.push(`<li>${inlineMd(lines[i].replace(/^[-*]\s+/, ""))}</li>`);
        i += 1;
      }
      html.push(`<ul>${items.join("")}</ul>`);
      continue;
    } else if (/^\d+\.\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i])) {
        items.push(`<li>${inlineMd(lines[i].replace(/^\d+\.\s+/, ""))}</li>`);
        i += 1;
      }
      html.push(`<ol>${items.join("")}</ol>`);
      continue;
    } else if (/^---+$/.test(line.trim())) {
      html.push("<hr />");
    } else {
      html.push(`<p>${inlineMd(line)}</p>`);
    }
    i += 1;
  }
  flushCode();
  flushTable();
  return html.join("\n");
}

/** 按管理端主题给同源 Swagger iframe 注入日间/夜间样式 */
function swaggerThemeCss(theme) {
  if (theme === "dark") {
    return `
html, body { background:#0b0f19 !important; color:#e6eaf2 !important; color-scheme:dark !important; }
.swagger-ui { background:#0b0f19 !important; color:#e6eaf2 !important; }
.swagger-ui .topbar { background:#111827 !important; }
.swagger-ui .info .title { color:#f3f4f6 !important; }
.swagger-ui .info p, .swagger-ui .info li, .swagger-ui .info table,
.swagger-ui .info .base-url, .swagger-ui .markdown p, .swagger-ui .markdown li,
.swagger-ui .renderedMarkdown p { color:#c5cad3 !important; }
.swagger-ui .scheme-container { background:#111827 !important; box-shadow:none !important; }
.swagger-ui .opblock-tag { color:#e6eaf2 !important; border-color:#30363d !important; }
.swagger-ui .opblock { background:#161b22 !important; border-color:#30363d !important; box-shadow:none !important; }
.swagger-ui .opblock .opblock-summary-path,
.swagger-ui .opblock .opblock-summary-description { color:#d1d5db !important; }
.swagger-ui .opblock .opblock-summary { border-color:#30363d !important; }
.swagger-ui section.models { border-color:#30363d !important; background:transparent !important; }
.swagger-ui section.models h4,
.swagger-ui .model-title,
.swagger-ui .model,
.swagger-ui table thead tr td,
.swagger-ui .response-col_status,
.swagger-ui .tab li { color:#d1d5db !important; }
.swagger-ui .model-box, .swagger-ui .model-container { background:#161b22 !important; }
.swagger-ui .opblock-body pre.microlight { background:#0d1117 !important; color:#e6eaf2 !important; }
.swagger-ui .btn { color:#e6eaf2 !important; }
.swagger-ui select { background:#161b22 !important; color:#e6eaf2 !important; }
.swagger-ui input[type=text], .swagger-ui textarea {
  background:#0d1117 !important; color:#e6eaf2 !important; border-color:#30363d !important;
}`;
  }
  return `
html, body { background:#ffffff !important; color:#1f2937 !important; color-scheme:light !important; }
.swagger-ui { background:#ffffff !important; color:#1f2937 !important; }
.swagger-ui .topbar { background:#f8fafc !important; }
.swagger-ui .info .title { color:#111827 !important; }
.swagger-ui .info p, .swagger-ui .info li, .swagger-ui .info table,
.swagger-ui .info .base-url, .swagger-ui .markdown p, .swagger-ui .markdown li,
.swagger-ui .renderedMarkdown p { color:#374151 !important; }
.swagger-ui .scheme-container { background:#ffffff !important; }
.swagger-ui .opblock-tag { color:#111827 !important; }
.swagger-ui .opblock { background:#ffffff !important; }
.swagger-ui .opblock .opblock-summary-path,
.swagger-ui .opblock .opblock-summary-description { color:#1f2937 !important; }
.swagger-ui section.models h4,
.swagger-ui .model-title { color:#111827 !important; }
.swagger-ui .model-box, .swagger-ui .model-container { background:#f8fafc !important; }`;
}

let swaggerThemeObserver = null;
let swaggerThemeRetryTimer = null;

function applySwaggerIframeTheme(iframe) {
  if (!iframe) return false;
  try {
    const doc = iframe.contentDocument;
    if (!doc?.head) return false;
    let el = doc.getElementById("kb-swagger-theme");
    if (!el) {
      el = doc.createElement("style");
      el.id = "kb-swagger-theme";
      doc.head.appendChild(el);
    }
    const theme = getTheme();
    el.textContent = swaggerThemeCss(theme);
    doc.documentElement.style.colorScheme = theme === "dark" ? "dark" : "light";
    if (doc.body) doc.body.style.background = theme === "dark" ? "#0b0f19" : "#ffffff";
    return true;
  } catch {
    return false;
  }
}

function bindSwaggerThemeSync(iframe) {
  if (swaggerThemeObserver) {
    swaggerThemeObserver.disconnect();
    swaggerThemeObserver = null;
  }
  if (swaggerThemeRetryTimer) {
    clearInterval(swaggerThemeRetryTimer);
    swaggerThemeRetryTimer = null;
  }
  if (!iframe) return;

  const paint = () => applySwaggerIframeTheme(iframe);
  iframe.addEventListener("load", () => {
    paint();
    let n = 0;
    if (swaggerThemeRetryTimer) clearInterval(swaggerThemeRetryTimer);
    swaggerThemeRetryTimer = setInterval(() => {
      paint();
      n += 1;
      if (n >= 12) {
        clearInterval(swaggerThemeRetryTimer);
        swaggerThemeRetryTimer = null;
      }
    }, 400);
  });
  paint();
  swaggerThemeObserver = new MutationObserver(paint);
  swaggerThemeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
}

function getApiGuideTab() {
  const q = location.hash.split("?")[1] || "";
  return new URLSearchParams(q).get("tab") === "guide" ? "guide" : "fastapi";
}

function apiGuidePath(tab) {
  return tab === "guide" ? "/admin/fastapi?tab=guide" : "/admin/fastapi";
}

/** API 接入指南：FastAPI 页（Swagger）+ 第三方接入说明 */
async function pageFastApi() {
  if (!requirePerm("system:read", "API 接入指南")) return;
  const tab = getApiGuideTab();
  document.getElementById("pageRoot").innerHTML = `
    ${pageHead({
      title: "API 接入指南",
      desc: "FastAPI 接口浏览与第三方业务系统联调说明。",
      actions: `
        <a class="btn btn-secondary btn-sm" href="/assets/vendor/swagger-ui/index.html" target="_blank" rel="noopener">新窗口打开 Swagger</a>
        <a class="btn btn-text btn-sm" href="/openapi.json" target="_blank" rel="noopener">OpenAPI JSON</a>
        <a class="btn btn-text btn-sm" href="/assets/docs/API_INTEGRATION_GUIDE.md" target="_blank" rel="noopener">打开 Markdown</a>
      `,
    })}
    <nav class="api-guide-bar" aria-label="API 接入指南">
      <div class="kb-ws-tabs" role="tablist">
        <button type="button" class="kb-ws-tab ${tab === "fastapi" ? "is-active" : ""}" data-api-tab="fastapi">FastAPI</button>
        <button type="button" class="kb-ws-tab ${tab === "guide" ? "is-active" : ""}" data-api-tab="guide">接入说明</button>
      </div>
    </nav>
    <div id="apiGuidePanel"></div>`;

  document.querySelectorAll("[data-api-tab]").forEach((btn) => {
    btn.onclick = () => {
      const next = btn.getAttribute("data-api-tab");
      if (next !== tab) navigate(apiGuidePath(next));
    };
  });

  const panel = document.getElementById("apiGuidePanel");
  if (tab === "fastapi") {
    panel.innerHTML = `
      <div class="card panel-fill fastapi-swagger-card">
        <div class="card-header">
          <div class="card-header-text">
            <h3 class="card-title">FastAPI 接口界面</h3>
          </div>
          <div class="card-header-actions">
            <a class="btn btn-secondary btn-sm" href="/assets/vendor/swagger-ui/index.html" target="_blank" rel="noopener">新窗口打开</a>
            <a class="btn btn-text btn-sm" href="/docs" target="_blank" rel="noopener">官方 /docs</a>
          </div>
        </div>
        <div class="fastapi-swagger-frame">
          <iframe
            id="fastapiSwaggerFrame"
            title="FastAPI Swagger UI"
            src="/assets/vendor/swagger-ui/index.html"
            class="fastapi-swagger-iframe"
            loading="eager"
            referrerpolicy="same-origin"
            allow="fullscreen"
          ></iframe>
        </div>
      </div>`;
    bindSwaggerThemeSync(document.getElementById("fastapiSwaggerFrame"));
    return;
  }

  panel.innerHTML = `
    <div class="card panel-fill fastapi-docs-card">
      <div class="card-header">
        <div class="card-header-text">
          <h3 class="card-title">第三方应用接入说明</h3>
          <p class="card-sub">仓库文档：docs/API_INTEGRATION_GUIDE.md · 字段级契约见 docs/API.md</p>
        </div>
      </div>
      <div class="md-doc-body" id="apiGuideBody"><div class="loading">加载文档…</div></div>
    </div>`;

  const bodyEl = document.getElementById("apiGuideBody");
  try {
    const res = await fetch(`/assets/docs/API_INTEGRATION_GUIDE.md?v=gap-opt-0721s`, { cache: "no-store" });
    if (!res.ok) throw new Error(`无法加载文档（HTTP ${res.status}）`);
    const md = await res.text();
    bodyEl.innerHTML = `<div class="md-doc">${renderSimpleMarkdown(md)}</div>`;
  } catch (e) {
    bodyEl.innerHTML = `<p class="text-danger">${escapeHtml(e.message || "加载失败")}</p>
      <p class="text-muted">也可直接查看仓库文件 <code>docs/API_INTEGRATION_GUIDE.md</code>。</p>`;
  }
}

/* ========== 启动 ========== */
[
  "/admin",
  "/admin/users",
  "/admin/roles",
  "/admin/departments",
  "/admin/departments/:id",
  "/admin/models",
  "/admin/knowledge-bases",
  "/admin/knowledge-bases/:id",
  "/admin/knowledge-bases/:id/documents",
  "/admin/knowledge-bases/:id/snapshots",
  "/admin/ragas",
  "/admin/qa-sessions",
  "/admin/role-caches",
  "/admin/hit-test",
  "/admin/audit",
  "/admin/guard",
  "/admin/monitor",
  "/admin/fastapi",
  "*",
].forEach((p) => route(p, () => dispatchRender()));

// 管理端默认落到 /admin
if (!location.hash || location.hash === "#" || location.hash === "#/") {
  location.hash = "#/admin";
}
startRouter();
