/**
 * 管理端应用（手册 5.1.2）
 * 路由：/admin 仪表盘、users、roles、models、knowledge-bases、
 * documents、snapshots、hit-test、audit、monitor
 * 顶栏提供「智能对话」与「退出」（手册 4.3）
 */

import { route, startRouter, navigate, currentPath } from "/assets/js/router.js";
import { api, clearDemoFlags } from "/assets/js/api.js";
import { isLoggedIn, getUser, clearAuth, hasPermission, canAccessAdmin, getRoleLabel, isSuperAdmin, isAdminUser } from "/assets/js/auth.js";
import { escapeHtml, formatDateTime, toast, confirmDialog } from "/assets/js/utils.js";
import { initMotion, runCountUps } from "/assets/js/motion.js";
import { initTheme, applyTheme, getTheme } from "/assets/js/theme.js";

clearDemoFlags();
initTheme();
initMotion();

/** 管理端菜单（分组展示；按权限码裁剪；前端隐藏不能替代后端鉴权） */
const MENU_GROUPS = [
  {
    title: "工作台",
    items: [{ path: "/admin", label: "首页", perm: "system:read" }],
  },
  {
    title: "组织与权限",
    items: [
      { path: "/admin/users", label: "用户管理", perm: "user:read" },
      { path: "/admin/roles", label: "角色管理", perm: "role:read" },
      { path: "/admin/departments", label: "部门管理", perm: "department:read" },
    ],
  },
  {
    title: "知识资产",
    items: [
      { path: "/admin/models", label: "大模型管理", perm: "model:read" },
      { path: "/admin/knowledge-bases", label: "知识库管理", perm: "kb:read" },
    ],
  },
  {
    title: "质量与运维",
    items: [
      { path: "/admin/ragas", label: "RAGAS 评估", perm: "system:read" },
      { path: "/admin/qa-sessions", label: "会话分析", perm: "system:read" },
      { path: "/admin/role-caches", label: "角色缓存", perm: "system:read" },
      { path: "/admin/hit-test", label: "命中率测试", perm: "test:read" },
      { path: "/admin/audit", label: "审计日志", perm: "audit:read" },
      { path: "/admin/monitor", label: "系统监控", perm: "system:read" },
    ],
  },
];

/** 扁平菜单（路由/兼容用） */
const MENUS = MENU_GROUPS.flatMap((g) => g.items);

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

  document.getElementById("app").innerHTML = `
    <div class="ambient-orbs" aria-hidden="true"><i></i><i></i><i></i></div>
    <div class="app-shell app-shell-admin">
      <aside class="sidebar" aria-label="管理导航">
        <div class="sidebar-brand" data-go="/admin" title="管理首页">
          <i class="logo-dot"></i>
          <span><b>Knowledge</b> AI<small>智能知识中枢</small></span>
        </div>
        <nav class="sidebar-nav" aria-label="管理导航分组">
          ${MENU_GROUPS.map((group) => {
            const links = group.items
              .filter((m) => hasPermission(m.perm))
              .map((m) => {
                const active = path === m.path || (m.path !== "/admin" && path.startsWith(m.path));
                return `<button type="button" class="nav-item ${active ? "active" : ""}" data-go="${m.path}"><i></i>${m.label}</button>`;
              })
              .join("");
            if (!links) return "";
            return `<div class="sidebar-group">
              <div class="sidebar-caption">${group.title}</div>
              <div class="sidebar-links">${links}</div>
            </div>`;
          }).join("")}
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
            <span class="role-chip">${roleText}</span>
            <button type="button" class="theme-toggle" data-theme-toggle aria-label="切换主题" title="切换主题">
              <span class="icon-sun" aria-hidden="true">☀</span>
              <span class="icon-moon" aria-hidden="true">☾</span>
            </button>
            <a class="btn btn-secondary btn-sm" href="/#/chat">智能对话</a>
            <button type="button" class="btn btn-text" id="btnLogout">退出</button>
          </div>
        </header>
        <main class="content" id="pageRoot"></main>
      </section>
    </div>`;

  document.querySelectorAll("[data-go]").forEach((el) => {
    el.addEventListener("click", () => navigate(el.getAttribute("data-go")));
  });
  document.getElementById("btnLogout").onclick = async () => {
    const ok = await confirmDialog({ title: "退出", message: "确定退出管理端吗？", confirmText: "退出" });
    if (!ok) return;
    clearAuth();
    location.href = "/#/";
  };
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

/** Materio 统一页头：标题 + 说明 + 右侧操作（desc 为纯文本） */
function pageHead({ title, desc = "", actions = "" }) {
  return `<header class="page-head">
    <div>
      <h1>${escapeHtml(title)}</h1>
      ${desc ? `<p class="page-desc">${escapeHtml(desc)}</p>` : ""}
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
  // 知识库详情 / 文档 / 快照
  let m;
  if ((m = path.match(/^\/admin\/knowledge-bases\/([^/]+)\/documents$/))) return pageDocuments(m[1]);
  if ((m = path.match(/^\/admin\/knowledge-bases\/([^/]+)\/snapshots$/))) return pageSnapshots(m[1]);
  if ((m = path.match(/^\/admin\/knowledge-bases\/([^/]+)$/))) return pageKbDetail(m[1]);
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
  if (path === "/admin/monitor") return pageMonitor();
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

async function pageDashboard() {
  if (!requirePerm("system:read", "首页")) return;
  const welcome = renderDashboardWelcome();
  document.getElementById("pageRoot").innerHTML = `${welcome}<div class="loading">加载统计数据…</div>`;
  try {
    const s = await api.get("/monitor/stats");
    const qa = s.qa_trend_7d || [0, 0, 0, 0, 0, 0, 0];
    const hit = s.hit_rate_trend_7d || [0, 0, 0, 0, 0, 0, 0];
    const err = s.error_24h || [0, 0, 0, 0];
    const qaLabels = weekLabels(qa.length);
    const hitLabels = weekLabels(hit.length);
    const errLabels = err.length === 4 ? ["0-6h", "6-12h", "12-18h", "18-24h"] : err.map((_, i) => `#${i + 1}`);

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
          <div class="card-header"><div class="card-header-text"><h3 class="card-title">近 7 天问答量</h3></div></div>
          ${renderBars(qa, { labels: qaLabels })}
        </div>
        <div class="card dash-chart-card span-4">
          <div class="card-header"><div class="card-header-text"><h3 class="card-title">安全窗口</h3></div></div>
          <div class="dash-security-metrics">
            <div><span class="label">近 24h 阻拦</span><strong data-count-up="${s.guard_blocked_24h ?? 0}">0</strong></div>
            <div><span class="label">近 7 天阻拦</span><strong data-count-up="${s.guard_blocked_7d ?? 0}">0</strong></div>
          </div>
          <p class="text-muted dash-security-note">涵盖提示注入、窃密、越权与危险命令。</p>
        </div>
        <div class="card dash-chart-card span-4">
          <div class="card-header"><div class="card-header-text"><h3 class="card-title">近 7 天命中率</h3></div></div>
          ${renderBars(hit, { percent: true, labels: hitLabels })}
        </div>
        <div class="card dash-chart-card span-8">
          <div class="card-header"><div class="card-header-text"><h3 class="card-title">近 24 小时错误</h3></div></div>
          ${renderBars(err, { labels: errLabels })}
        </div>
      </section>
      ${renderDashboardShortcuts()}`;

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
  // 超管可分配 admin / super_admin；普通管理员不可分配 admin 或超管
  const options = (roles || [])
    .filter((r) => {
      if (r.name === "user" || r.name === "kb_admin") return false;
      if (iAmSuper) return true;
      return r.name !== "super_admin" && r.name !== "admin";
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
          <p class="text-muted">${iAmSuper ? "超管可将用户设为管理员或超级管理员。" : "管理员不可将他人设为管理员或超级管理员，也不可改超管账号。"}</p>
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
      if (r.name === "user" || r.name === "kb_admin") return false;
      if (isSuperAdmin()) return true;
      return r.name !== "super_admin" && r.name !== "admin";
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
            <th class="col-name">账号</th>
            <th>昵称</th>
            <th class="col-status">状态</th>
            <th>角色</th>
            <th>部门</th>
            <th class="col-time">创建时间</th>
            <th class="col-time">最近登录</th>
            <th class="col-actions">操作</th>
          </tr></thead>
          <tbody>
            ${items
              .map((u) => {
                const st = u.status === "active" ? `<span class="badge badge-success">活跃</span>` : u.status === "disabled" ? `<span class="badge badge-danger">禁用</span>` : `<span class="badge badge-warning">待验证</span>`;
                const locked = Boolean(u.is_super_admin) && !isSuperAdmin();
                const myRank = isSuperAdmin() ? 100 : isAdminUser() ? 50 : 0;
                const targetRank = maxRoleRankOfUser(u);
                const canManage = canWrite && !locked && targetRank < myRank;
                const ops = canWrite
                  ? locked
                    ? `<span class="cell-muted">权限不足</span>`
                    : canManage
                      ? `<div class="table-actions">
                    <button type="button" class="btn btn-secondary btn-sm" data-toggle="${escapeHtml(u.id)}" data-status="${escapeHtml(u.status)}">${u.status === "disabled" ? "启用" : "禁用"}</button>
                    <button type="button" class="btn btn-secondary btn-sm" data-role="${escapeHtml(u.id)}">角色</button>
                    <button type="button" class="btn btn-danger btn-sm" data-del-user="${escapeHtml(u.id)}">删除</button>
                  </div>`
                      : `<span class="cell-muted">权限不足</span>`
                  : `<span class="cell-muted">—</span>`;
                return `<tr data-id="${escapeHtml(u.id)}">
                  <td class="col-name"><strong class="cell-primary">${escapeHtml(u.username)}</strong></td>
                  <td>${escapeHtml(u.nickname || "-")}</td>
                  <td class="col-status">${st}</td>
                  <td class="cell-role">${escapeHtml(roleLabelOf(u))}</td>
                  <td>${escapeHtml(u.department || "-")}</td>
                  <td class="col-time"><span class="cell-time">${formatDateTime(u.created_at)}</span></td>
                  <td class="col-time"><span class="cell-time">${formatDateTime(u.last_login_at)}</span></td>
                  <td class="col-actions">${ops}</td>
                </tr>`;
              })
              .join("")}
          </tbody>
        </table></div>
      </div>`;

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
            <h3 class="card-title">角色与权限</h3>
            <p class="card-sub">共 ${items.filter((r) => r.name !== "user" && r.name !== "kb_admin").length} 个角色</p>
          </div>
        </div>
        <div class="table-wrap"><table class="table table-roles">
          <thead><tr>
            <th class="col-name">中文名</th>
            <th class="col-code">标识</th>
            <th class="col-desc">说明</th>
            <th class="col-builtin">内置</th>
            <th>权限数</th>
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
                  <td class="col-desc" title="${escapeHtml(desc)}"><span class="cell-clamp">${escapeHtml(desc)}</span></td>
                  <td class="col-builtin">${r.is_builtin ? `<span class="badge">内置</span>` : "-"}</td>
                  <td>${(r.permissions || []).length}</td>
                  <td class="col-actions">
                    <div class="table-actions">
                      <button class="btn btn-secondary btn-sm" data-view="${escapeHtml(r.id)}">查看权限</button>
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
                        <td>${d.is_enabled ? `<span class="badge badge-success">启用</span>` : `<span class="badge">停用</span>`}</td>
                        <td class="col-actions" style="white-space:nowrap">
                          <button type="button" class="btn btn-secondary btn-sm" data-go="/admin/departments/${escapeHtml(d.id)}">管理</button>
                          ${
                            canWrite
                              ? `<button type="button" class="btn btn-secondary btn-sm" data-edit="${escapeHtml(d.id)}">编辑</button>
                                 ${String(d.code).toUpperCase() === "GUEST" ? "" : `<button type="button" class="btn btn-danger btn-sm" data-del="${escapeHtml(d.id)}">删除</button>`}`
                              : ""
                          }
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
                          <td style="white-space:nowrap">
                            <button type="button" class="btn btn-text btn-sm" data-go="/admin/knowledge-bases/${escapeHtml(k.id)}">打开</button>
                            ${
                              canWrite
                                ? `<button type="button" class="btn btn-text btn-sm" data-rm-kb="${escapeHtml(k.id)}" style="color:var(--color-danger)">解除</button>`
                                : ""
                            }
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
          <label style="display:flex;gap:8px;align-items:center;margin-top:12px">
            <input type="checkbox" name="is_default" ${m.is_default ? "checked" : ""} /> 设为同类型默认
          </label>
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
      is_default: form.get("is_default") === "on",
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
        <div class="table-wrap"><table class="table">
          <thead><tr><th>名称</th><th>类型</th><th>模型</th><th>URL</th><th>Key 环境变量</th><th>优先级</th><th>启用</th><th>默认</th><th>操作</th></tr></thead>
          <tbody>
            ${items
              .map(
                (m) => `<tr>
                  <td>${escapeHtml(m.name)}</td>
                  <td><span class="badge">${escapeHtml(m.model_type)}</span></td>
                  <td>${escapeHtml(m.model_name || "-")}</td>
                  <td class="text-muted" style="max-width:160px;overflow:hidden;text-overflow:ellipsis" title="${escapeHtml(m.base_url || "")}">${escapeHtml(m.base_url || "-")}</td>
                  <td><code>${escapeHtml(m.api_key_env || "-")}</code>${m.has_api_key ? ' <span class="badge badge-success">已配置</span>' : ""}</td>
                  <td>${escapeHtml(m.priority ?? 100)}</td>
                  <td>${m.is_enabled ? `<span class="badge badge-success">是</span>` : `<span class="badge">否</span>`}</td>
                  <td>${m.is_default ? "是" : "否"}</td>
                  <td>
                    ${
                      canWrite
                        ? `<button class="btn btn-text btn-sm" data-edit="${escapeHtml(m.id)}">编辑</button>
                           <button class="btn btn-secondary btn-sm" data-toggle="${escapeHtml(m.id)}" data-on="${m.is_enabled ? 1 : 0}">${m.is_enabled ? "停用" : "启用"}</button>
                           ${!m.is_default ? `<button class="btn btn-text btn-sm" data-default="${escapeHtml(m.id)}">设默认</button>` : ""}`
                        : `<span class="text-muted">—</span>`
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
            if (payload.is_default) await api.put(`/models/${model.id}/default`, { is_default: true });
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

    document.querySelectorAll("[data-default]").forEach((btn) => {
      btn.onclick = async () => {
        try {
          await api.put(`/models/${btn.getAttribute("data-default")}/default`, { is_default: true });
          toast("已设为默认", "success");
          pageModels();
        } catch (e) {
          toast(e.message || "设置失败", "error");
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
      ? `<div style="background:#fff7e6;border:1px solid #ffe0a3;color:#8a5a00;border-radius:8px;padding:10px 12px;margin-bottom:12px;font-size:13px">提示：${escapeHtml(data.notice)}</div>`
      : "";

    const statCard = (label, value) =>
      `<div style="flex:1;min-width:120px;background:var(--surface-2,#f6f7f9);border-radius:8px;padding:12px 14px">
         <div class="text-muted" style="font-size:12px">${label}</div>
         <div style="font-size:20px;font-weight:600;margin-top:4px">${value}</div>
       </div>`;

    let html = `
      ${noticeHtml}
      <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:14px">
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

/* ========== 知识库列表 ========== */
async function pageKbList() {
  if (!requirePerm("kb:read", "知识库管理")) return;
  document.getElementById("pageRoot").innerHTML = `<div class="loading">加载知识库…</div>`;
  try {
    const data = await api.get("/knowledge-bases?page=1&page_size=50");
    const items = data.items || [];
    const statusLabel = (status) => ({ active: "已同步", ready: "已就绪", processing: "处理中" }[String(status || "").toLowerCase()] || status || "待配置");
    document.getElementById("pageRoot").innerHTML = `
      ${pageHead({
        title: "知识库管理",
        desc: "管理企业知识资产、文档索引与访问范围。",
        actions: hasPermission("kb:write")
          ? `<button class="btn" id="btnCreateKb">+ 新建知识库</button>`
          : `<span class="role-chip">只读访问</span>`,
      })}
      <div class="kb-summary-row"><span>共 <b>${items.length}</b> 个知识库</span><span>仅展示当前账号有权访问的内容</span></div>
      <section class="kb-card-grid">
        ${hasPermission("kb:write") ? `<button type="button" class="kb-create-card" id="btnCreateKbCard"><span>+</span><b>创建新知识库</b><small>配置类型、访问范围和分段策略</small></button>` : ""}
        ${items.map((k) => `<article class="kb-card">
          <div class="kb-card-cover"><span>${escapeHtml((k.name || "知").slice(0, 1))}</span><em>${escapeHtml(k.type || "通用知识")}</em></div>
          <div class="kb-card-body">
            <div class="kb-card-heading"><h3>${escapeHtml(k.name)}</h3><span class="status-dot ${String(k.status || "").toLowerCase() === "processing" ? "is-processing" : ""}">${escapeHtml(statusLabel(k.status))}</span></div>
            <p>${escapeHtml(k.description || "暂未填写知识库简介，可进入详情页补充说明。")}</p>
            <div class="kb-card-meta"><span>${escapeHtml(k.doc_count ?? 0)} 份文档</span><span>${formatDateTime(k.updated_at)}</span></div>
            <div class="kb-card-access">${accessScopeBadge(k)}</div>
            <div class="kb-card-actions"><button class="btn btn-secondary btn-sm" data-go="/admin/knowledge-bases/${escapeHtml(k.id)}">查看详情</button><button class="btn btn-sm" data-go="/admin/knowledge-bases/${escapeHtml(k.id)}/documents">文档管理</button></div>
          </div>
        </article>`).join("") || `<div class="card empty-state span-12">暂未创建可访问的知识库</div>`}
      </section>`;
    document.querySelectorAll("[data-go]").forEach((b) => b.addEventListener("click", () => navigate(b.getAttribute("data-go"))));
    const btnCreate = document.getElementById("btnCreateKb");
    const btnCreateCard = document.getElementById("btnCreateKbCard");
    if (btnCreateCard) btnCreateCard.onclick = () => btnCreate?.click();
    if (btnCreate) {
      btnCreate.onclick = async () => {
        const departments = await loadDepartmentOptions();
        const deptOptions = departmentSelectHtml(departments, "", { emptyLabel: "私有（仅创建者/授权可见）" });
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
              <p class="text-muted" style="margin:6px 0 0;font-size:12px">访客专用=所有人可见；某部门=仅该部门员工与管理员；私有=仅创建者/被授权者与管理员。</p>
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

/* ========== 知识库详情 ========== */
async function pageKbDetail(id) {
  if (!requirePerm("kb:read", "知识库详情")) return;
  const canWrite = hasPermission("kb:write");

  async function render() {
    document.getElementById("pageRoot").innerHTML = `<div class="loading">加载详情…</div>`;
    try {
      const k = await api.get(`/knowledge-bases/${id}`);
      document.getElementById("pageRoot").innerHTML = `
        ${pageHead({
          title: k.name || "知识库详情",
          desc: `${k.type || "通用"} · ${k.status || "-"} · Embedding ${k.embedding_model || "-"}`,
          actions: `
            <button class="btn btn-secondary btn-sm" data-go="/admin/knowledge-bases">返回列表</button>
            <button class="btn btn-sm" data-go="/admin/knowledge-bases/${escapeHtml(id)}/documents">文档管理</button>
            <button class="btn btn-sm" data-go="/admin/knowledge-bases/${escapeHtml(id)}/snapshots">快照管理</button>
            ${canWrite ? `<button class="btn btn-sm" id="btnEditKb">编辑</button>` : ""}
            ${canWrite ? `<button class="btn btn-danger btn-sm" id="btnDeleteKb">删除</button>` : ""}
            ${hasPermission("kb:vectorize") ? `<button class="btn btn-secondary btn-sm" id="btnRevec">重新向量化</button>` : ""}
          `,
        })}
        <div class="page-grid">
          <div class="card span-7">
            <div class="card-header"><div class="card-header-text"><h3 class="card-title">基本信息</h3></div></div>
            <div class="meta-list">
              <div class="meta-row"><span class="meta-label">简介</span><span class="meta-value">${escapeHtml(k.description || "无简介")}</span></div>
              <div class="meta-row"><span class="meta-label">标签</span><span class="meta-value">${escapeHtml((k.tags || []).join(", ") || "-")}</span></div>
              <div class="meta-row"><span class="meta-label">访问范围</span><span class="meta-value">${accessScopeBadge(k)}</span></div>
              <div class="meta-row"><span class="meta-label">索引版本</span><span class="meta-value">${escapeHtml(k.current_index_version)}</span></div>
              <div class="meta-row"><span class="meta-label">分段</span><span class="meta-value">size=${escapeHtml(k.chunk_size)} · overlap=${escapeHtml(k.chunk_overlap)}</span></div>
            </div>
          </div>
          <div class="card span-5">
            <div class="card-header"><div class="card-header-text"><h3 class="card-title">概览</h3></div></div>
            <div class="stat-grid" style="grid-template-columns:1fr 1fr;margin-bottom:12px">
              <div class="stat-card"><div class="label">文档数</div><div class="value">${k.doc_count ?? 0}</div></div>
              <div class="stat-card"><div class="label">分段数</div><div class="value">${k.chunk_count ?? 0}</div></div>
            </div>
            <div class="meta-list">
              <div class="meta-row"><span class="meta-label">创建</span><span class="meta-value">${formatDateTime(k.created_at)}</span></div>
              <div class="meta-row"><span class="meta-label">更新</span><span class="meta-value">${formatDateTime(k.updated_at)}</span></div>
            </div>
            <p class="page-desc" style="margin-top:12px">知识库可绑定部门；员工仅能上传本部门或授权库。管理员与超管不受部门隔离。</p>
          </div>
        </div>`;

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
                ${departmentSelectHtml(departments, k.department, { emptyLabel: "私有（仅创建者/授权可见）" })}
              </select>
              <p class="text-muted" style="margin:0 0 12px;font-size:12px">访客专用=所有人可见；某部门=仅该部门员工与管理员；私有=仅创建者/被授权者与管理员。</p>
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

      const btnRevec = document.getElementById("btnRevec");
      if (btnRevec) {
        btnRevec.onclick = async () => {
          const result = await openWideModal({
            title: "重新向量化",
            bodyHtml: `
              <p class="text-muted" style="margin-top:0">将先创建变更快照，再按下方分段规则重切并重建索引；在线问答不中断。</p>
              <label class="text-muted">分段长度 chunk_size（100–5000）</label>
              <input class="form-control" id="rvChunkSize" type="number" min="100" max="5000" value="${escapeHtml(k.chunk_size ?? 500)}" style="margin:6px 0 12px" />
              <label class="text-muted">分段重叠 chunk_overlap（0–1000）</label>
              <input class="form-control" id="rvChunkOverlap" type="number" min="0" max="1000" value="${escapeHtml(k.chunk_overlap ?? 50)}" style="margin:6px 0 12px" />
              <label class="text-muted">分段模式</label>
              <select class="form-control" id="rvSplitMode" style="margin:6px 0 12px">
                <option value="fixed">固定长度 fixed</option>
                <option value="sliding">滑动窗口 sliding</option>
                 <option value="paragraph">按段落 paragraph</option>
                 <option value="heading">按标题 heading</option>
                 <option value="markdown">Markdown 结构 markdown</option>
              </select>
              <label class="text-muted">嵌入模型（可留空沿用当前：${escapeHtml(k.embedding_model || "-")}）</label>
              <input class="form-control" id="rvEmbed" value="" placeholder="留空则不改" style="margin:6px 0 12px" />
              <label style="display:flex;gap:8px;align-items:center;margin:8px 0">
                <input type="checkbox" id="rvApplyDocs" checked /> 同步规则到库内全部待处理文档
              </label>
              <label style="display:flex;gap:8px;align-items:center;margin:8px 0">
                <input type="checkbox" id="rvForceAll" /> 强制处理全部文档（含非 ready）
              </label>`,
            actionsHtml: `
              <button type="button" class="btn btn-secondary" data-act="cancel">取消</button>
              <button type="button" class="btn" data-act="ok">开始重建</button>`,
          });
          if (!result) return;
          const chunk_size = Number(result.root.querySelector("#rvChunkSize")?.value || 0);
          const chunk_overlap = Number(result.root.querySelector("#rvChunkOverlap")?.value || 0);
          const split_mode = result.root.querySelector("#rvSplitMode")?.value || "fixed";
          const embedding_model = (result.root.querySelector("#rvEmbed")?.value || "").trim();
          const apply_to_documents = Boolean(result.root.querySelector("#rvApplyDocs")?.checked);
          const force_all = Boolean(result.root.querySelector("#rvForceAll")?.checked);
          result.root.remove();
          if (!Number.isFinite(chunk_size) || chunk_size < 100 || chunk_size > 5000) {
            toast("分段长度须在 100–5000", "error");
            return;
          }
          if (!Number.isFinite(chunk_overlap) || chunk_overlap < 0 || chunk_overlap > 1000) {
            toast("分段重叠须在 0–1000", "error");
            return;
          }
          try {
            const task = await api.post(`/knowledge-bases/${id}/re-vectorize`, {
              chunk_size,
              chunk_overlap,
              split_mode,
              apply_to_documents,
              force_all,
              ...(embedding_model ? { embedding_model } : {}),
            });
            toast(
              `已提交重建任务（${task?.total_count ?? 0} 篇文档）${task?.target_version ? " · " + task.target_version : ""}`,
              "success"
            );
            await render();
          } catch (e) {
            toast(e.message || "提交失败", "error");
          }
        };
      }
    } catch (e) {
      document.getElementById("pageRoot").innerHTML = `<div class="card text-danger">${escapeHtml(e.message)}</div>`;
    }
  }

  await render();
}

/* ========== 文档管理 ========== */
async function pageDocuments(kbId) {
  if (!requirePerm("doc:read", "文档管理")) return;
  document.getElementById("pageRoot").innerHTML = `<div class="loading">加载文档…</div>`;

  const formatSize = (n) => {
    const v = Number(n);
    if (!Number.isFinite(v) || v < 0) return "-";
    if (v < 1024) return `${v} B`;
    if (v < 1024 * 1024) return `${(v / 1024).toFixed(1)} KB`;
    return `${(v / 1024 / 1024).toFixed(1)} MB`;
  };

  const openDocPreview = async (docId, filenameHint) => {
    try {
      const [content, chunksPage] = await Promise.all([
        api.get(`/knowledge-bases/${kbId}/documents/${docId}/content`),
        api
          .get(`/knowledge-bases/${kbId}/documents/${docId}/chunks?page=1&page_size=50`)
          .catch(() => ({ items: [], total: 0 })),
      ]);
      const bodyText =
        content.preview_source === "raw_text"
          ? content.raw_text
          : content.normalized_text || content.raw_text || "";
      const chunks = chunksPage.items || [];
      const rules = content.segment_rules || {};
      const emptyHint =
        content.preview_source === "empty"
          ? `<p class="text-muted">尚无解析正文（状态：${escapeHtml(content.status)}）。上传后流水线完成后可预览。</p>`
          : "";

      const mask = document.createElement("div");
      mask.className = "modal-mask";
      mask.innerHTML = `
        <div class="modal" role="dialog" aria-modal="true" style="width:min(820px,calc(100vw - 24px));max-height:90vh;overflow:auto">
          <h3 class="modal-title">预览 · ${escapeHtml(filenameHint || content.filename || "文档")}</h3>
          <div class="modal-body">
            <p class="text-muted" style="margin-top:0">
              状态 <span class="badge">${escapeHtml(content.status)}</span>
              · 分段 ${escapeHtml(content.chunk_count ?? 0)}
              · 清洗 ${escapeHtml(content.normalized_char_count ?? 0)} 字
              · 原文 ${escapeHtml(content.raw_char_count ?? 0)} 字
              ${content.truncated ? " · <span class='badge badge-warning'>内容已截断</span>" : ""}
              ${content.error_message ? ` · <span class="text-danger">${escapeHtml(content.error_message)}</span>` : ""}
            </p>
            <p class="text-muted" style="margin:0 0 10px">
              分段规则：size=${escapeHtml(rules.chunk_size ?? "-")}
              overlap=${escapeHtml(rules.chunk_overlap ?? "-")}
              mode=${escapeHtml(rules.split_mode || "fixed")}
            </p>
            <div style="display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap">
              <button type="button" class="btn btn-sm" data-tab="normalized">清洗正文</button>
              <button type="button" class="btn btn-sm btn-secondary" data-tab="raw">解析原文</button>
              <button type="button" class="btn btn-sm btn-secondary" data-tab="chunks">分段列表（${escapeHtml(chunksPage.total ?? chunks.length)}）</button>
            </div>
            ${emptyHint}
            <pre id="docPreviewBody" style="background:var(--color-bg-tint,#f8f9fa);padding:12px;border-radius:8px;overflow:auto;max-height:420px;white-space:pre-wrap;word-break:break-word;font-size:13px;line-height:1.5;margin:0"></pre>
            <div id="docPreviewChunks" style="display:none;max-height:420px;overflow:auto">
              ${
                chunks.length
                  ? chunks
                      .map(
                        (c) => `<div style="border:1px solid var(--color-border,#e0e0e0);border-radius:8px;padding:10px;margin-bottom:8px">
                          <div class="text-muted" style="font-size:12px;margin-bottom:6px">#${escapeHtml(c.chunk_index)} · ${escapeHtml(c.char_count)} 字${c.is_enabled === false ? " · 已禁用" : ""}</div>
                          <div style="white-space:pre-wrap;word-break:break-word;font-size:13px;line-height:1.45">${escapeHtml(c.content || "")}</div>
                        </div>`
                      )
                      .join("")
                  : `<p class="text-muted">暂无分段</p>`
              }
            </div>
          </div>
          <div class="modal-actions">
            <button type="button" class="btn btn-secondary" data-close>关闭</button>
          </div>
        </div>`;
      document.body.appendChild(mask);

      const bodyEl = mask.querySelector("#docPreviewBody");
      const chunksEl = mask.querySelector("#docPreviewChunks");
      bodyEl.textContent = bodyText || "（无内容）";

      const setActiveTab = (tab) => {
        mask.querySelectorAll("[data-tab]").forEach((b) => {
          const on = b.getAttribute("data-tab") === tab;
          b.className = on ? "btn btn-sm" : "btn btn-sm btn-secondary";
        });
        if (tab === "chunks") {
          bodyEl.style.display = "none";
          chunksEl.style.display = "block";
          return;
        }
        bodyEl.style.display = "block";
        chunksEl.style.display = "none";
        bodyEl.textContent =
          tab === "raw"
            ? content.raw_text || "（无原文）"
            : content.normalized_text || content.raw_text || "（无内容）";
      };

      mask.querySelectorAll("[data-tab]").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          setActiveTab(btn.getAttribute("data-tab"));
        });
      });
      mask.querySelector("[data-close]").onclick = () => mask.remove();
      mask.addEventListener("click", (e) => {
        if (e.target === mask) mask.remove();
      });
    } catch (e) {
      toast(e.message || "预览失败", "error");
    }
  };

  try {
    const data = await api.get(`/knowledge-bases/${kbId}/documents?page=1&page_size=50`);
    const items = data.items || [];
    document.getElementById("pageRoot").innerHTML = `
      ${pageHead({
        title: "文档管理",
        desc: "支持 PDF、Word（DOC/DOCX）、TXT、Markdown（MD）。",
        actions: `
          <button class="btn btn-secondary btn-sm" data-go="/admin/knowledge-bases/${escapeHtml(kbId)}">返回详情</button>
          <input type="file" id="adminFile" accept=".pdf,.doc,.docx,.txt,.md,text/markdown,application/pdf" />
          <button class="btn btn-sm" id="btnAdminUpload">上传</button>
        `,
      })}
      <div class="card panel-fill">
        <div class="card-header">
          <div class="card-header-text">
            <h3 class="card-title">文档列表</h3>
            <p class="card-sub">分段 / 预处理 / 向量化状态 · 共 ${items.length} 份</p>
          </div>
        </div>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>文件名</th><th>大小</th><th>分段</th><th>状态</th><th>上传时间</th><th>操作</th></tr></thead>
          <tbody>
            ${items
              .map(
                (d) => `<tr>
                  <td>${escapeHtml(d.filename || d.name)}</td>
                  <td>${escapeHtml(formatSize(d.file_size ?? d.size))}</td>
                  <td>${escapeHtml(d.chunk_count ?? 0)}</td>
                  <td><span class="badge">${escapeHtml(d.status)}</span></td>
                  <td>${formatDateTime(d.created_at)}</td>
                  <td>
                    <button class="btn btn-secondary btn-sm" data-preview="${escapeHtml(d.id)}" data-name="${escapeHtml(d.filename || "")}">预览</button>
                    ${hasPermission("doc:write") ? `<button class="btn btn-danger btn-sm" data-del="${escapeHtml(d.id)}">删除</button>` : ""}
                  </td>
                </tr>`
              )
              .join("") || `<tr><td colspan="6" class="text-muted">暂无文档</td></tr>`}
          </tbody>
        </table></div>
      </div>`;
    document.querySelectorAll("[data-go]").forEach((b) => b.addEventListener("click", () => navigate(b.getAttribute("data-go"))));
    document.getElementById("btnAdminUpload").onclick = async () => {
      const f = document.getElementById("adminFile").files[0];
      if (!f) return toast("请选择文件", "error");
      const fd = new FormData();
      fd.append("file", f);
      try {
        await api.upload(`/knowledge-bases/${kbId}/documents/upload`, fd);
        toast("上传成功", "success");
        pageDocuments(kbId);
      } catch (e) {
        toast(e.message || "上传失败", "error");
      }
    };
    document.querySelectorAll("[data-preview]").forEach((btn) => {
      btn.onclick = () => openDocPreview(btn.getAttribute("data-preview"), btn.getAttribute("data-name"));
    });
    document.querySelectorAll("[data-del]").forEach((btn) => {
      btn.onclick = async () => {
        const ok = await confirmDialog({ title: "删除文档", message: "将删除文档及其向量数据，确定？", confirmText: "删除" });
        if (!ok) return;
        try {
          await api.delete(`/knowledge-bases/${kbId}/documents/${btn.getAttribute("data-del")}`);
          toast("已删除", "success");
          pageDocuments(kbId);
        } catch (e) {
          toast(e.message || "删除失败", "error");
        }
      };
    });
  } catch (e) {
    document.getElementById("pageRoot").innerHTML = `<div class="card text-danger">${escapeHtml(e.message)}</div>`;
  }
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
  removed: "将归档",
  modified: "将变更",
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
function openWideModal({ title, bodyHtml, actionsHtml }) {
  return new Promise((resolve) => {
    const mask = document.createElement("div");
    mask.className = "modal-mask";
    mask.innerHTML = `
      <div class="modal" role="dialog" aria-modal="true" style="width:min(760px,calc(100vw - 24px));max-height:85vh;overflow:auto">
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
  });
}

async function pageSnapshots(kbId) {
  if (!requirePerm("snapshot:read", "快照管理")) return;
  const canWrite = hasPermission("snapshot:write");
  const canRestore = hasPermission("snapshot:restore");
  document.getElementById("pageRoot").innerHTML = `<div class="loading">加载快照…</div>`;

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

  const renderList = async () => {
    const data = await api.get(`/knowledge-bases/${kbId}/snapshots?page=1&page_size=50`);
    const items = data.items || [];
    document.getElementById("pageRoot").innerHTML = `
      ${pageHead({
        title: "快照管理",
        desc: "变更前自动留存；回退前强制生成保护快照。默认最多保留 50 份 / 90 天。",
        actions: `
          <button class="btn btn-secondary btn-sm" data-go="/admin/knowledge-bases/${escapeHtml(kbId)}">返回详情</button>
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
            ? `<div class="table-wrap"><table class="table">
          <thead><tr>
            <th>快照名称</th><th>触发方式</th><th>文档数</th><th>分段数</th><th>说明</th><th>创建时间</th><th>操作</th>
          </tr></thead>
          <tbody>
            ${items
              .map((s) => {
                const isProtection = s.trigger === "rollback_protection";
                const ops = [
                  `<button class="btn btn-text btn-sm" data-detail="${escapeHtml(s.id)}">详情</button>`,
                  canRestore
                    ? `<button class="btn btn-secondary btn-sm" data-preview="${escapeHtml(s.id)}">差异预览/回退</button>`
                    : "",
                  canWrite && !isProtection
                    ? `<button class="btn btn-text btn-sm" data-del="${escapeHtml(s.id)}" style="color:var(--color-danger)">删除</button>`
                    : isProtection
                      ? `<span class="text-muted" title="保护快照不可手动删除">不可删</span>`
                      : "",
                ]
                  .filter(Boolean)
                  .join(" ");
                return `<tr>
                  <td><strong>${escapeHtml(s.name || "-")}</strong></td>
                  <td>${triggerBadge(s.trigger)}</td>
                  <td>${escapeHtml(s.document_count ?? 0)}</td>
                  <td>${escapeHtml(s.total_chunks ?? 0)}</td>
                  <td>${escapeHtml(s.description || "—")}</td>
                  <td>${formatDateTime(s.created_at)}</td>
                  <td style="white-space:nowrap">${ops}</td>
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
              <label style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
                <input type="checkbox" id="snapSelective" /> 仅恢复下方勾选的文档（不改整库配置/权限）
              </label>
              <div class="table-wrap"><table class="table">
                <thead><tr><th></th><th>变更</th><th>文件名</th><th>当前分段</th><th>快照分段</th><th>说明</th></tr></thead>
                <tbody>${
                  (preview.affected_documents || []).length
                    ? (preview.affected_documents || [])
                        .map((a) => {
                          const canSelect = a.change_type === "added" || a.change_type === "modified";
                          return `<tr>
                            <td>${
                              canSelect
                                ? `<input type="checkbox" class="snap-doc" value="${escapeHtml(a.document_id)}" ${
                                    a.change_type !== "unchanged" ? "checked" : ""
                                  } />`
                                : ""
                            }</td>
                            <td><span class="badge ${
                              a.change_type === "removed"
                                ? "badge-danger"
                                : a.change_type === "added"
                                  ? "badge-success"
                                  : a.change_type === "modified"
                                    ? "badge-warning"
                                    : ""
                            }">${escapeHtml(SNAPSHOT_CHANGE_LABELS[a.change_type] || a.change_type)}</span></td>
                            <td>${escapeHtml(a.filename)}</td>
                            <td>${escapeHtml(a.current_chunk_count ?? "—")}</td>
                            <td>${escapeHtml(a.snapshot_chunk_count ?? "—")}</td>
                            <td class="text-muted">${escapeHtml(a.detail || "")}</td>
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
          const selective = result.root.querySelector("#snapSelective")?.checked;
          let document_ids;
          if (selective) {
            document_ids = [...result.root.querySelectorAll(".snap-doc:checked")].map((el) => el.value);
            if (!document_ids.length) {
              result.root.remove();
              toast("选择性恢复请至少勾选一份文档", "error");
              return;
            }
          }
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
    document.getElementById("pageRoot").innerHTML = `<div class="card text-danger">${escapeHtml(e.message)}</div>`;
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

  const openRunDetail = async (runId) => {
    try {
      const detail = await api.get(`/hit-tests/runs/${runId}`);
      const summary = detail.summary || detail;
      const results = detail.results || [];
      const mask = document.createElement("div");
      mask.className = "modal-mask";
      mask.innerHTML = `
        <div class="modal" role="dialog" style="width:min(900px,calc(100vw - 24px));max-height:90vh;overflow:auto">
          <h3 class="modal-title">运行详情</h3>
          <div class="modal-body">
            <p class="text-muted" style="margin-top:0">
              策略 ${escapeHtml(strategyLabel(summary.strategy))}
              · TopK ${escapeHtml(summary.top_k)}
              · 命中 ${escapeHtml(summary.hit_count)}/${escapeHtml(summary.total_questions)}
              · 得分（命中率）${pct(summary.score ?? summary.hit_rate ?? summary.recall_at_k)}
              · MRR ${summary.mrr != null ? Number(summary.mrr).toFixed(3) : "-"}
              · 均耗时 ${summary.avg_elapsed_ms != null ? Math.round(summary.avg_elapsed_ms) + "ms" : "-"}
            </p>
            <div class="table-wrap"><table class="table">
              <thead><tr><th>问题</th><th>命中</th><th>排名</th><th>命中片段相关度</th><th>耗时</th><th>召回摘要</th></tr></thead>
              <tbody>
                ${
                  results.length
                    ? results
                        .map((r) => {
                          const chunks = r.actual_chunks || [];
                          const tip = chunks
                            .slice(0, 2)
                            .map((c) => `${c.doc_name || c.doc_id || ""}#${c.chunk_index ?? ""}`)
                            .join("；");
                          return `<tr>
                            <td style="max-width:220px">${escapeHtml(r.question)}</td>
                            <td>${r.is_hit ? `<span class="badge badge-success">是</span>` : `<span class="badge badge-danger">否</span>`}</td>
                            <td>${escapeHtml(r.hit_rank ?? "-")}</td>
                            <td>${r.score != null ? Number(r.score).toFixed(3) : "-"}</td>
                            <td>${escapeHtml(r.elapsed_ms != null ? r.elapsed_ms + "ms" : "-")}</td>
                            <td class="text-muted" style="max-width:240px;font-size:12px">${escapeHtml(tip || "无召回")}</td>
                          </tr>`;
                        })
                        .join("")
                    : `<tr><td colspan="6" class="text-muted">无明细</td></tr>`
                }
              </tbody>
            </table></div>
          </div>
          <div class="modal-actions">
            <a class="btn btn-secondary" href="/api/v1/hit-tests/runs/${escapeHtml(runId)}/export" id="btnExportCsv" target="_blank" rel="noopener">导出 CSV</a>
            <button type="button" class="btn btn-secondary" data-close>关闭</button>
          </div>
        </div>`;
      document.body.appendChild(mask);
      mask.querySelector("[data-close]").onclick = () => mask.remove();
      mask.addEventListener("click", (e) => {
        if (e.target === mask) mask.remove();
      });
      // 带 token 下载 CSV（a[href] 无法带 Authorization）
      const exportBtn = mask.querySelector("#btnExportCsv");
      if (exportBtn) {
        exportBtn.addEventListener("click", async (e) => {
          e.preventDefault();
          try {
            const { getAccessToken } = await import("/assets/js/auth.js");
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
          } catch (err) {
            toast(err.message || "导出失败", "error");
          }
        });
      }
    } catch (e) {
      toast(e.message || "加载详情失败", "error");
    }
  };

  const openCreateCase = async (docsByKb) => {
    const kbOptions = Object.keys(docsByKb)
      .map((id) => {
        const meta = docsByKb[id];
        return `<option value="${escapeHtml(id)}">${escapeHtml(meta.name)}</option>`;
      })
      .join("");
    const mask = document.createElement("div");
    mask.className = "modal-mask";
    mask.innerHTML = `
      <form class="modal" style="width:min(640px,calc(100vw - 24px));max-height:90vh;overflow:auto">
        <div class="modal-header"><h3>新建测试用例</h3></div>
        <div class="modal-body">
          <label class="form-label">用例名称</label>
          <input class="form-control" name="name" required placeholder="如：员工手册回归集" />
          <label class="form-label" style="margin-top:10px">说明</label>
          <input class="form-control" name="description" placeholder="可选" />
          <label class="form-label" style="margin-top:10px">关联知识库（用于选择期望文档）</label>
          <select class="form-control" id="caseKbPick">${kbOptions || "<option value=''>暂无知识库</option>"}</select>
          <label class="form-label" style="margin-top:10px">问题列表（每行一题；必须用「|文档名关键字」标注期望文档）</label>
          <textarea class="form-control" name="questions" rows="8" required placeholder="试用期年假怎么折算？|年假
加班如何申请调休？|考勤
礼品超过多少需要上交？|合规"></textarea>
          <p class="text-muted" style="margin:8px 0 0;font-size:12px">命中率必须与标准答案比较。示例：问题文本|文档名关键字；关键字必须匹配至少一份文档，否则不能创建测试用例。</p>
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
      const name = String(fd.get("name") || "").trim();
      const description = String(fd.get("description") || "").trim() || null;
      const kbId = mask.querySelector("#caseKbPick")?.value || "";
      const docs = (docsByKb[kbId] && docsByKb[kbId].docs) || [];
      const lines = String(fd.get("questions") || "")
        .split(/\r?\n/)
        .map((l) => l.trim())
        .filter(Boolean);
      if (!name || !lines.length) {
        toast("请填写名称与至少一个问题", "error");
        return;
      }
      const invalidLines = [];
      const questions = lines.map((line, index) => {
        const [q, hint] = line.split("|").map((s) => s.trim());
        let expected_doc_ids = null;
        if (hint) {
          const matched = docs.filter((d) => String(d.filename || "").includes(hint));
          if (matched.length) expected_doc_ids = matched.map((d) => d.id);
        }
        if (!q || !hint || !expected_doc_ids?.length) invalidLines.push(index + 1);
        return { question: q || line, expected_doc_ids, expected_chunk_ids: null };
      });
      if (invalidLines.length) {
        toast(`第 ${invalidLines.join("、")} 行缺少有效的期望文档关键字`, "error");
        return;
      }
      try {
        await api.post("/hit-tests/cases", { name, description, questions });
        toast("用例已创建", "success");
        mask.remove();
        pageHitTest();
      } catch (e) {
        toast(e.message || "创建失败", "error");
      }
    };
  };

  try {
    const [casesData, runsData, kbData] = await Promise.all([
      api.get("/hit-tests/cases?page=1&page_size=50"),
      api.get("/hit-tests/runs?page=1&page_size=30"),
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
        desc: "多选用例按序执行；配置期望文档或分段后可计算真实命中率。",
        actions: canWrite ? `<button type="button" class="btn btn-secondary btn-sm" id="btnNewCase">新建用例</button>` : "",
      })}
      <div class="page-grid">
      <div class="card span-12">
        <div class="card-header">
          <div class="card-header-text">
            <h3 class="card-title">执行参数</h3>
            <p class="card-sub">选择知识库与检索策略后执行；可多选用例按序跑完</p>
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
        <div style="margin-top:20px;display:flex;flex-wrap:wrap;gap:8px">
          ${
            canWrite
              ? `<button type="button" class="btn" id="btnRunTest">执行测试</button>
                 <button type="button" class="btn btn-secondary" id="btnCompare">多策略对比</button>
                 <button type="button" class="btn btn-secondary" id="btnClearCase">清除已选</button>`
              : `<span class="text-muted">需要 test:write 才能执行</span>`
          }
        </div>
      </div>

      <div class="card span-6 panel-fill">
          <div class="card-header">
            <div class="card-header-text"><h3 class="card-title">测试用例</h3></div>
            <div class="card-header-actions">
            ${
              cases.length
                ? `<button type="button" class="btn btn-secondary btn-sm" id="btnSelectAllCases">全选</button>
                   <button type="button" class="btn btn-secondary btn-sm" id="btnInvertCases">反选</button>`
                : ""
            }
            </div>
          </div>
          <div class="table-wrap"><table class="table" id="htCaseTable">
            <thead><tr><th style="width:96px">选用</th><th>名称</th><th>题数</th><th>说明</th><th></th></tr></thead>
            <tbody>
              ${
                cases.length
                  ? cases
                      .map((c) => {
                        const cid = String(c.id);
                        return `<tr class="ht-case-row" data-case-row="${escapeHtml(cid)}">
                          <td>
                            <label class="ht-pick" data-pick-wrap="${escapeHtml(cid)}">
                              <input type="checkbox" value="${escapeHtml(cid)}" data-pick-case="${escapeHtml(cid)}" />
                              <span data-pick-label>选用</span>
                            </label>
                          </td>
                          <td>${escapeHtml(c.name)}</td>
                          <td>${escapeHtml(c.question_count)}</td>
                          <td class="text-muted" style="max-width:180px">${escapeHtml(c.description || "-")}</td>
                          <td style="white-space:nowrap">
                            <button type="button" class="btn btn-secondary btn-sm" data-view-case="${escapeHtml(cid)}">查看</button>
                            ${canWrite ? `<button type="button" class="btn btn-danger btn-sm" data-del-case="${escapeHtml(cid)}">删除</button>` : ""}
                          </td>
                        </tr>`;
                      })
                      .join("")
                  : `<tr><td colspan="5" class="text-muted">暂无用例，请点右上角「新建用例」</td></tr>`
              }
            </tbody>
          </table></div>
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
          <div class="table-wrap"><table class="table" id="htRunTable">
            <thead><tr><th>用例</th><th>得分（命中率）</th><th>命中</th><th>策略</th><th>时间</th><th></th></tr></thead>
            <tbody>
              ${
                runs.length
                  ? runs
                      .map((r) => {
                        const rate = r.score ?? r.hit_rate ?? r.recall_at_k;
                        return `<tr data-run-row="${escapeHtml(String(r.id))}">
                          <td style="max-width:140px">${escapeHtml(caseNameOf(r.case_id))}</td>
                          <td><strong>${pct(rate)}</strong></td>
                          <td>${escapeHtml(r.hit_count)}/${escapeHtml(r.total_questions)}</td>
                          <td>${escapeHtml(strategyLabel(r.strategy))}</td>
                          <td>${formatDateTime(r.completed_at || r.created_at)}</td>
                          <td style="white-space:nowrap">
                            <button type="button" class="btn btn-secondary btn-sm" data-run="${escapeHtml(String(r.id))}">详情</button>
                            ${canWrite ? `<button type="button" class="btn btn-danger btn-sm" data-del-run="${escapeHtml(String(r.id))}">清除</button>` : ""}
                          </td>
                        </tr>`;
                      })
                      .join("")
                  : `<tr><td colspan="6" class="text-muted">暂无运行记录</td></tr>`
              }
            </tbody>
          </table></div>
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
        const on = selected.has(input.value);
        input.checked = on;
        const wrap = input.closest(".ht-pick");
        if (wrap) {
          wrap.classList.toggle("is-on", on);
          const label = wrap.querySelector("[data-pick-label]");
          if (label) label.textContent = on ? "已选" : "选用";
        }
      });
      const picked = selectedCaseIds
        .map((id) => cases.find((c) => String(c.id) === id))
        .filter(Boolean);
      if (picked.length) {
        const totalQ = picked.reduce((s, c) => s + Number(c.question_count || 0), 0);
        const names = picked.map((c) => escapeHtml(c.name)).join("、");
        banner.innerHTML = `当前已选用 <strong>${picked.length}</strong> 个用例（共 ${totalQ} 题）：${names}。执行测试将按顺序逐个运行。`;
        banner.style.background = "rgba(52, 211, 153, 0.12)";
      } else {
        banner.textContent = "当前：未选用测试用例";
        banner.style.background = "rgba(255, 255, 255, 0.03)";
      }
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
        const viewBtn = e.target.closest("[data-view-case]");
        if (viewBtn) {
          const c = cases.find((x) => String(x.id) === viewBtn.getAttribute("data-view-case"));
          if (!c) return;
          const qs = (c.questions || [])
            .map((q, i) => `${i + 1}. ${q.question}${q.expected_doc_ids?.length ? " 〔有期望文档〕" : ""}`)
            .join("\n");
          openWideModal({
            title: c.name,
            bodyHtml: `<pre style="white-space:pre-wrap;font-size:13px;margin:0">${escapeHtml(qs || "无问题")}</pre>`,
            actionsHtml: `<button type="button" class="btn btn-secondary" data-act="cancel">关闭</button>`,
          });
          return;
        }
        const delBtn = e.target.closest("[data-del-case]");
        if (delBtn) {
          (async () => {
            const ok = await confirmDialog({
              title: "删除用例",
              message: "确定删除该测试用例？",
              confirmText: "删除",
              danger: true,
            });
            if (!ok) return;
            try {
              await api.delete(`/hit-tests/cases/${delBtn.getAttribute("data-del-case")}`);
              toast("已删除", "success");
              pageHitTest();
            } catch (err) {
              toast(err.message || "删除失败", "error");
            }
          })();
        }
      });
    }

    syncSelectionUi({ persist: false });

    const btnSelectAll = document.getElementById("btnSelectAllCases");
    if (btnSelectAll) {
      btnSelectAll.onclick = () => {
        selectedCaseIds = cases.map((c) => String(c.id));
        syncSelectionUi();
      };
    }
    const btnInvert = document.getElementById("btnInvertCases");
    if (btnInvert) {
      btnInvert.onclick = () => {
        const cur = new Set(selectedCaseIds);
        selectedCaseIds = cases.map((c) => String(c.id)).filter((id) => !cur.has(id));
        syncSelectionUi();
      };
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

    const runTable = document.getElementById("htRunTable");
    if (runTable) {
      runTable.addEventListener("click", (e) => {
        const detailBtn = e.target.closest("[data-run]");
        if (detailBtn) {
          openRunDetail(detailBtn.getAttribute("data-run"));
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
          if (!selectedCaseIds.length) {
            throw new Error("请先勾选至少一个带期望文档或分段的测试用例");
          }
          const summaries = [];
          for (let i = 0; i < selectedCaseIds.length; i += 1) {
            const caseId = selectedCaseIds[i];
            btnRun.textContent = `执行中 ${i + 1}/${selectedCaseIds.length}…`;
            const run = await api.post("/hit-tests/runs", { ...base, case_id: caseId });
            summaries.push(
              `${caseNameOf(caseId)} ${run.hit_count}/${run.total_questions}（${pct(run.score ?? run.hit_rate ?? run.recall_at_k)}）`
            );
          }
          toast(`已完成 ${summaries.length} 个用例：${summaries.join("；")}`, "success");
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
                        return `${x.is_hit ? "命中" : "未命中"} ${x.score != null ? Number(x.score).toFixed(2) : ""}`;
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

/** 把 RAGAS 的 0-1 分数渲染为百分比；缺少标准答案的指标显示未评估。 */
function ragasScore(value) {
  return value == null || Number.isNaN(Number(value)) ? "未评估" : `${(Number(value) * 100).toFixed(1)}%`;
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

    root.innerHTML = `
      ${pageHead({
        title: "RAGAS 评估",
        desc: "从真实问答抽样评估忠实度、答案相关性与上下文精确率。",
      })}
      <div class="page-grid">
      <div class="card span-12">
        <div class="card-header">
          <div class="card-header-text">
            <h3 class="card-title">发起评估</h3>
            <p class="card-sub">缺少标准答案时不计算上下文召回率</p>
          </div>
          <div class="card-header-actions">
            <label><span class="form-label">知识库</span><select class="form-control" id="ragasKb" style="min-width:220px">${kbOptions || `<option value="">暂无知识库</option>`}</select></label>
            <label><span class="form-label">样本数</span><input class="form-control" id="ragasLimit" type="number" min="1" max="50" value="10" style="width:90px" /></label>
            <button type="button" class="btn btn-primary" id="btnRunRagas" ${knowledgeBases.length ? "" : "disabled"}>开始评估</button>
          </div>
        </div>
      </div>
      <div class="card panel-fill span-12">
        <div class="card-header">
          <div class="card-header-text"><h3 class="card-title">评估记录</h3></div>
          <span class="badge">共 ${escapeHtml(runData.total ?? runs.length)} 次</span>
        </div>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>知识库</th><th>状态</th><th>样本</th><th>忠实度</th><th>答案相关性</th><th>上下文精确率</th><th>上下文召回率</th><th>完成时间</th><th></th></tr></thead>
          <tbody>
            ${
              runs.length
                ? runs
                    .map(
                      (run) => `<tr>
                        <td>${escapeHtml(run.kb_name || run.kb_id)}</td>
                        <td><span class="badge">${run.status === "completed" ? "已完成" : run.status === "failed" ? "失败" : "运行中"}</span>${run.error_message ? `<div class="text-danger" style="max-width:220px">${escapeHtml(run.error_message)}</div>` : ""}</td>
                        <td>${escapeHtml(run.sample_count ?? 0)}</td>
                        <td>${ragasScore(run.metric_scores?.faithfulness)}</td>
                        <td>${ragasScore(run.metric_scores?.answer_relevancy)}</td>
                        <td>${ragasScore(run.metric_scores?.context_precision)}</td>
                        <td>${ragasScore(run.metric_scores?.context_recall)}</td>
                        <td>${formatDateTime(run.completed_at || run.created_at)}</td>
                        <td><button type="button" class="btn btn-text btn-sm" data-ragas-detail="${escapeHtml(run.id)}">详细结果</button></td>
                      </tr>`
                    )
                    .join("")
                : `<tr><td colspan="9" class="text-muted">暂无评估记录，请选择知识库开始评估</td></tr>`
            }
          </tbody>
        </table></div>
      </div>
      </div>`;

    document.getElementById("btnRunRagas").onclick = async () => {
      const kbId = document.getElementById("ragasKb").value;
      const sampleLimit = Number(document.getElementById("ragasLimit").value);
      if (!kbId) {
        toast("请选择知识库", "error");
        return;
      }
      if (!Number.isInteger(sampleLimit) || sampleLimit < 1 || sampleLimit > 50) {
        toast("样本数必须是 1-50 的整数", "error");
        return;
      }
      const button = document.getElementById("btnRunRagas");
      button.disabled = true;
      button.textContent = "评估中…";
      toast("RAGAS 评估已开始，指标可能调用多次模型，请等待完成");
      try {
        const result = await api.post("/ragas/runs", { kb_id: kbId, sample_limit: sampleLimit });
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
          <thead><tr><th>会话</th><th>用户</th><th>类型</th><th>消息数</th><th>最后活跃</th><th></th></tr></thead>
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
                        <td>${formatDateTime(session.last_active_at)}</td>
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
        <div class="table-wrap"><table class="table">
          <thead><tr><th>缓存知识库</th><th>角色</th><th>缓存数</th><th>检测周期</th><th>文档分析</th><th>历史分析</th><th>状态</th><th></th></tr></thead>
          <tbody>
            ${
              caches.length
                ? caches
                    .map(
                      (cache) => `<tr data-role-cache-row="${escapeHtml(cache.role_id)}">
                        <td><strong>${escapeHtml(cache.name)}</strong></td>
                        <td>${escapeHtml(cache.role_description || cache.role_name)}</td>
                        <td>${escapeHtml(cache.question_count ?? 0)}</td>
                        <td>
                          <label style="display:flex;align-items:center;gap:6px;white-space:nowrap">
                            <input class="form-control" style="width:76px" type="number" min="1" max="365" value="${escapeHtml(cache.interval_days)}" data-cache-interval ${canWrite ? "" : "disabled"} /> 天
                          </label>
                        </td>
                        <td>${cache.last_document_analysis_at ? formatDateTime(cache.last_document_analysis_at) : "尚未执行"}</td>
                        <td>${cache.last_history_analysis_at ? formatDateTime(cache.last_history_analysis_at) : "尚未执行"}</td>
                        <td><span class="badge">${cache.enabled ? "已启用" : "已停用"}</span></td>
                        <td style="white-space:nowrap">
                          <button type="button" class="btn btn-text btn-sm" data-cache-detail>查看问题</button>
                          ${
                            canWrite
                              ? `<button type="button" class="btn btn-text btn-sm" data-cache-save>保存</button>
                                 <button type="button" class="btn btn-text btn-sm" data-cache-doc>分析文档</button>
                                 <button type="button" class="btn btn-text btn-sm" data-cache-history>检测历史</button>
                                 <button type="button" class="btn btn-text btn-sm" data-cache-toggle>${cache.enabled ? "停用" : "启用"}</button>`
                              : ""
                          }
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
      row.querySelector("[data-cache-detail]").onclick = () => openRoleCacheQuestions(roleId, current.name);
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
      row.querySelector("[data-cache-history]").onclick = () => runRoleCacheAnalysis(roleId, "history");
    });
  } catch (error) {
    root.innerHTML = `<div class="card empty-state">加载角色缓存失败：${escapeHtml(error.message)}</div>`;
  }
}

/** 管理员手动触发文档或历史分析；请求完成后自动刷新统计。 */
async function runRoleCacheAnalysis(roleId, type) {
  const label = type === "documents" ? "文档分析" : "历史高频检测";
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
async function openRoleCacheQuestions(roleId, cacheName) {
  try {
    const data = await api.get(`/role-caches/${roleId}/questions?page=1&page_size=100`);
    const items = data.items || [];
    const mask = document.createElement("div");
    mask.className = "modal-mask";
    mask.innerHTML = `
      <div class="modal" role="dialog" aria-modal="true" style="width:min(1000px,calc(100vw - 24px));max-height:90vh;overflow:auto">
        <div class="modal-header"><h3>${escapeHtml(cacheName || "缓存问题明细")}</h3></div>
        <div class="modal-body">
          <p class="text-muted" style="margin-top:0">共 ${escapeHtml(data.total ?? items.length)} 个缓存问题。文档生成与历史高频问题都必须携带知识库来源范围才能被问答链路命中。</p>
          <div class="table-wrap"><table class="table">
            <thead><tr><th>问题</th><th>答案摘要</th><th>来源</th><th>历史频次</th><th>缓存命中</th><th>更新时间</th></tr></thead>
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
                          <td>${formatDateTime(item.updated_at)}</td>
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
                  <span class="text-muted">识别意图</span><div>${escapeHtml(intent.name || "历史记录未包含意图")} ${intent.confidence != null ? `（${Math.round(Number(intent.confidence) * 100)}%，${intent.detector === "llm" ? "LLM 分类器" : "本地规则"}）` : ""}</div>
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

  const actionLabel = (code) => AUDIT_ACTION_LABELS[code] || code || "-";
  const resourceLabel = (code) => AUDIT_RESOURCE_LABELS[code] || code || "-";

  const load = async (filters = {}) => {
    const qs = new URLSearchParams({ page: "1", page_size: "50" });
    if (filters.action) qs.set("action", filters.action);
    if (filters.resource_type) qs.set("resource_type", filters.resource_type);
    if (filters.result) qs.set("result", filters.result);
    const data = await api.get(`/audit/logs?${qs.toString()}`);
    const items = data.items || [];
    document.getElementById("pageRoot").innerHTML = `
      ${pageHead({
        title: "审计日志",
        desc: "记录操作者、时间、对象、请求标识与结果。",
      })}
      <div class="card panel-fill">
        <div class="card-header">
          <div class="card-header-text">
            <h3 class="card-title">操作审计</h3>
            <p class="card-sub">共 ${escapeHtml(data.total ?? items.length)} 条</p>
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
          <button class="btn btn-secondary btn-sm" id="btnAuditFilter">筛选</button>
          </div>
        </div>
        <div class="table-wrap"><table class="table">
          <thead><tr>
            <th>操作者</th><th>动作</th><th>资源</th><th>资源 ID</th><th>请求标识</th><th>结果</th><th>时间</th><th></th>
          </tr></thead>
          <tbody>${
            items.length
              ? items
                  .map(
                    (a) => `<tr>
                <td>${escapeHtml(a.user_name || (a.user_id ? String(a.user_id).slice(0, 8) + "…" : "系统"))}</td>
                <td title="${escapeHtml(a.action)}">${escapeHtml(actionLabel(a.action))}</td>
                <td>${escapeHtml(resourceLabel(a.resource_type))}</td>
                <td class="text-muted">${escapeHtml(a.resource_id ? String(a.resource_id).slice(0, 8) + "…" : "—")}</td>
                <td class="text-muted">${escapeHtml(a.request_id ? String(a.request_id).slice(0, 10) + "…" : "—")}</td>
                <td>${
                  a.result === "success"
                    ? `<span class="badge badge-success">成功</span>`
                    : `<span class="badge badge-danger">${escapeHtml(a.result || "失败")}</span>`
                }</td>
                <td>${formatDateTime(a.created_at)}</td>
                <td><button class="btn btn-text btn-sm" data-audit="${escapeHtml(a.id)}">详情</button></td>
              </tr>`
                  )
                  .join("")
              : `<tr><td colspan="8" class="text-muted">暂无符合条件的审计记录</td></tr>`
          }</tbody>
        </table></div>
      </div>`;

    const actionEl = document.getElementById("auditAction");
    const resourceEl = document.getElementById("auditResource");
    const resultEl = document.getElementById("auditResult");
    if (actionEl) actionEl.value = filters.action || "";
    if (resourceEl) resourceEl.value = filters.resource_type || "";
    if (resultEl) resultEl.value = filters.result || "";

    const applyFilters = () =>
      load({
        action: (actionEl && actionEl.value) || undefined,
        resource_type: (resourceEl && resourceEl.value) || undefined,
        result: (resultEl && resultEl.value) || undefined,
      });

    const btnFilter = document.getElementById("btnAuditFilter");
    if (btnFilter) btnFilter.onclick = applyFilters;
    // 下拉框变更即筛选（避免「点了没反应」）
    [actionEl, resourceEl, resultEl].forEach((el) => {
      if (el) el.onchange = applyFilters;
    });

    document.querySelectorAll("[data-audit]").forEach((btn) => {
      btn.onclick = async () => {
        const id = btn.getAttribute("data-audit");
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
                  : `<span class="badge badge-danger">${escapeHtml(d.result || "失败")}</span>`
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
    });
  };

  try {
    await load();
  } catch (e) {
    document.getElementById("pageRoot").innerHTML = `<div class="card text-danger">${escapeHtml(e.message)}</div>`;
  }
}

/* ========== 系统监控（Grafana 嵌入） ========== */
async function pageMonitor() {
  if (!requirePerm("system:read", "系统监控")) return;
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
  const checksHtml = Object.entries(health.checks || {})
    .map(([k, v]) => {
      const status = typeof v === "object" ? v.status : v;
      const latency = typeof v === "object" && v.latency_ms != null ? ` (${v.latency_ms}ms)` : "";
      return `<li><code>${escapeHtml(k)}</code> = ${escapeHtml(String(status))}${escapeHtml(latency)}</li>`;
    })
    .join("");
  const statsHtml =
    stats && !stats.error
      ? `<ul class="list-plain">
        <li>用户数：${stats.user_count ?? 0}</li>
        <li>知识库：${stats.kb_count ?? 0}</li>
        <li>文档数：${stats.doc_count ?? 0}</li>
        <li>活跃会话：${stats.active_sessions ?? 0}</li>
        <li>任务队列：${stats.task_queue_size ?? 0}</li>
        <li>LLM Guard 近 24 小时阻拦：${stats.guard_blocked_24h ?? 0}</li>
        <li>LLM Guard 近 7 天阻拦：${stats.guard_blocked_7d ?? 0}</li>
      </ul>`
      : `<p class="text-muted">${escapeHtml(stats?.error || "暂无统计")}</p>`;
  document.getElementById("pageRoot").innerHTML = `
    ${pageHead({
      title: "系统监控",
      desc: "健康检查、运行统计与 Grafana 面板。",
    })}
    <div class="page-grid">
    <div class="card span-6">
      <div class="card-header">
        <div class="card-header-text"><h3 class="card-title">健康检查</h3></div>
        <span class="badge ${health.status === "ok" || health.status === "healthy" ? "badge-success" : ""}">${escapeHtml(health.status)}</span>
      </div>
      <p class="page-desc" style="margin-bottom:12px">${health.uptime_seconds != null ? `Uptime ${health.uptime_seconds}s` : "组件状态一览"}</p>
      <ul class="list-plain">${checksHtml || "<li class='text-muted'>无组件检查数据</li>"}</ul>
    </div>
    <div class="card span-6">
      <div class="card-header">
        <div class="card-header-text"><h3 class="card-title">系统统计</h3></div>
      </div>
      ${statsHtml}
    </div>
    <div class="card span-12">
      <div class="card-header">
        <div class="card-header-text">
          <h3 class="card-title">LLM Guard 最近阻拦</h3>
          <p class="card-sub">仅展示安全分类与原因码，不展示用户完整问题或密钥。</p>
        </div>
      </div>
      <div class="table-wrap"><table class="table">
        <thead><tr><th>时间</th><th>意图</th><th>原因码</th><th>检测层</th><th>置信度</th></tr></thead>
        <tbody>
          ${
            stats?.guard_recent_events?.length
              ? stats.guard_recent_events
                  .map(
                    (event) => `<tr>
                      <td>${formatDateTime(event.created_at)}</td>
                      <td>${escapeHtml(event.intent)}</td>
                      <td><code>${escapeHtml(event.reason_code)}</code></td>
                      <td>${event.detector === "llm" ? "LLM 分类器" : "本地规则"}</td>
                      <td>${Math.round(Number(event.confidence || 0) * 100)}%</td>
                    </tr>`
                  )
                  .join("")
              : `<tr><td colspan="5" class="text-muted">最近没有恶意访问阻拦记录</td></tr>`
          }
        </tbody>
      </table></div>
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
  "/admin/monitor",
  "*",
].forEach((p) => route(p, () => dispatchRender()));

// 管理端默认落到 /admin
if (!location.hash || location.hash === "#" || location.hash === "#/") {
  location.hash = "#/admin";
}
startRouter();
