/**
 * 管理端应用（手册 5.1.2）
 * 路由：/admin 仪表盘、users、roles、models、knowledge-bases、
 * documents、snapshots、hit-test、audit、monitor
 * 顶栏提供「智能对话」与「退出」（手册 4.3）
 */

import { route, startRouter, navigate, currentPath } from "/assets/js/router.js";
import { api, isDemoMode } from "/assets/js/api.js";
import { isLoggedIn, getUser, clearAuth, hasPermission, canAccessAdmin, getRoleLabel, isSuperAdmin } from "/assets/js/auth.js";
import { escapeHtml, formatDateTime, toast, confirmDialog } from "/assets/js/utils.js";

/** 管理端菜单（按权限码裁剪；前端隐藏不能替代后端鉴权） */
const MENUS = [
  { path: "/admin", label: "仪表盘", perm: "system:read" },
  { path: "/admin/users", label: "用户管理", perm: "user:read" },
  { path: "/admin/roles", label: "角色管理", perm: "role:read" },
  { path: "/admin/models", label: "大模型管理", perm: "model:read" },
  { path: "/admin/knowledge-bases", label: "知识库管理", perm: "kb:read" },
  { path: "/admin/hit-test", label: "命中率测试", perm: "test:read" },
  { path: "/admin/audit", label: "审计日志", perm: "audit:read" },
  { path: "/admin/monitor", label: "系统监控", perm: "system:read" },
];

/** 页面级权限门禁（防深链绕过菜单隐藏） */
function requirePerm(perm, title) {
  if (!renderShell(title)) return false;
  if (!hasPermission(perm)) {
    document.getElementById("pageRoot").innerHTML = `<div class="card empty-state">无权限访问本页（需要 <code>${escapeHtml(perm)}</code>）</div>`;
    return false;
  }
  return true;
}

/** 演示横幅同步 */
function syncDemoBanner() {
  const el = document.getElementById("demoBanner");
  if (el) el.classList.toggle("hidden", !isDemoMode());
}

/** 登录门禁：未登录或不具备管理权限则回访客登录页 */
function guard() {
  if (!isLoggedIn()) {
    toast("请先登录管理端", "error");
    location.href = "/#/login";
    return false;
  }
  if (!canAccessAdmin()) {
    toast("当前账号无管理端权限", "error");
    location.href = "/#/";
    return false;
  }
  return true;
}

/** 渲染管理端壳层（顶栏主导 + 全宽内容；右上保留智能对话/退出） */
function renderShell(title) {
  if (!guard()) return false;
  const user = getUser() || {};
  const path = currentPath();
  const roleText = `${escapeHtml(user.nickname || user.username || "管理员")} · ${getRoleLabel()}`;

  document.getElementById("app").innerHTML = `
    <div class="app-shell">
      <header class="topnav">
        <div class="topnav-brand" data-go="/admin" title="管理首页">
          <i class="logo-dot"></i>
          <span>管理控制台${isSuperAdmin() ? " · 超管" : ""}</span>
        </div>
        <nav class="topnav-links" aria-label="管理导航">
          ${MENUS.map((m) => {
            // 严格按权限码显示（超级管理员 hasPermission 全放行）
            if (!hasPermission(m.perm)) return "";
            const active = path === m.path || (m.path !== "/admin" && path.startsWith(m.path));
            return `<div class="nav-item ${active ? "active" : ""}" data-go="${m.path}">${m.label}</div>`;
          }).join("")}
        </nav>
        <div class="topnav-actions">
          <span class="text-muted">${roleText}</span>
          <a class="btn btn-secondary btn-sm" href="/#/">智能对话</a>
          <button type="button" class="btn btn-text" id="btnLogout">退出</button>
        </div>
      </header>
      <div class="page-bar">
        <div class="page-bar-title">${escapeHtml(title)}</div>
      </div>
      <main class="content" id="pageRoot"></main>
    </div>`;

  document.querySelectorAll("[data-go]").forEach((el) => {
    el.addEventListener("click", () => navigate(el.getAttribute("data-go")));
  });
  document.getElementById("btnLogout").onclick = async () => {
    const ok = await confirmDialog({ title: "退出", message: "确定退出管理端吗？", confirmText: "退出" });
    if (!ok) return;
    clearAuth();
    location.href = "/#/login";
  };
  return true;
}

/** 条形图渲染 */
function renderBars(values, { percent = false } = {}) {
  const max = Math.max(...values.map(Number), 0.0001);
  return `<div class="bar-chart">${values
    .map((v, i) => {
      const h = Math.round((Number(v) / max) * 100);
      const label = percent ? `${Math.round(Number(v) * 100)}%` : String(v);
      return `<div class="bar" style="height:${h}%" title="${label}"><span>${label}</span></div>`;
    })
    .join("")}</div>`;
}

/** 路由分发 */
async function dispatchRender() {
  syncDemoBanner();
  const path = currentPath();
  // 知识库详情 / 文档 / 快照
  let m;
  if ((m = path.match(/^\/admin\/knowledge-bases\/([^/]+)\/documents$/))) return pageDocuments(m[1]);
  if ((m = path.match(/^\/admin\/knowledge-bases\/([^/]+)\/snapshots$/))) return pageSnapshots(m[1]);
  if ((m = path.match(/^\/admin\/knowledge-bases\/([^/]+)$/))) return pageKbDetail(m[1]);
  if (path === "/admin/users") return pageUsers();
  if (path === "/admin/roles") return pageRoles();
  if (path === "/admin/models") return pageModels();
  if (path === "/admin/knowledge-bases") return pageKbList();
  if (path === "/admin/hit-test") return pageHitTest();
  if (path === "/admin/audit") return pageAudit();
  if (path === "/admin/monitor") return pageMonitor();
  return pageDashboard();
}

/* ========== 仪表盘 /admin ========== */
async function pageDashboard() {
  if (!requirePerm("system:read", "管理首页 / 仪表盘")) return;
  document.getElementById("pageRoot").innerHTML = `<div class="loading">加载统计数据…</div>`;
  try {
    const s = await api.get("/monitor/stats");
    document.getElementById("pageRoot").innerHTML = `
      <div class="stat-grid">
        <div class="stat-card"><div class="label">知识库总数</div><div class="value">${s.kb_count ?? "-"}</div></div>
        <div class="stat-card"><div class="label">文档总数</div><div class="value">${s.doc_count ?? "-"}</div></div>
        <div class="stat-card"><div class="label">用户总数</div><div class="value">${s.user_count ?? "-"}</div></div>
        <div class="stat-card"><div class="label">活跃会话</div><div class="value">${s.active_sessions ?? "-"}</div></div>
        <div class="stat-card"><div class="label">任务队列</div><div class="value">${s.queue_length ?? "-"}</div></div>
      </div>
      <div class="chart-grid">
        <div class="card"><h3 class="card-title">近 7 天问答量</h3>${renderBars(s.qa_trend_7d || [0, 0, 0, 0, 0, 0, 0])}</div>
        <div class="card"><h3 class="card-title">近 7 天命中率</h3>${renderBars(s.hit_rate_trend_7d || [0, 0, 0, 0, 0, 0, 0], { percent: true })}</div>
        <div class="card"><h3 class="card-title">系统资源概览</h3>
          <p>CPU：${s.cpu ?? "-"}%</p>
          <div style="height:8px;background:#E8F0FE;border-radius:4px;margin:6px 0 12px"><div style="height:100%;width:${s.cpu || 0}%;background:var(--color-primary)"></div></div>
          <p>内存：${s.memory ?? "-"}%</p>
          <div style="height:8px;background:#E8F0FE;border-radius:4px;margin:6px 0 12px"><div style="height:100%;width:${s.memory || 0}%;background:var(--color-primary-light)"></div></div>
          <p>磁盘：${s.disk ?? "-"}%</p>
          <div style="height:8px;background:#E8F0FE;border-radius:4px;margin:6px 0"><div style="height:100%;width:${s.disk || 0}%;background:var(--color-primary-dark)"></div></div>
        </div>
        <div class="card"><h3 class="card-title">近 24 小时错误趋势</h3>${renderBars(s.error_24h || [0, 0, 0, 0])}</div>
      </div>`;
  } catch (e) {
    document.getElementById("pageRoot").innerHTML = `<div class="card text-danger">${escapeHtml(e.message)}</div>`;
  }
}

/* ========== 用户管理 ========== */
async function pageUsers() {
  if (!requirePerm("user:read", "用户管理")) return;
  const canWrite = hasPermission("user:write");
  document.getElementById("pageRoot").innerHTML = `<div class="loading">加载用户…</div>`;
  try {
    const data = await api.get("/users?page=1&page_size=50");
    const items = data.items || [];
    document.getElementById("pageRoot").innerHTML = `
      <div class="card">
        <div class="toolbar"><strong>用户列表</strong><span class="spacer"></span>
          <span class="text-muted">${canWrite ? "可新增用户、启用/禁用与变更角色" : "只读（需超级管理员 user:write）"}</span>
          ${canWrite ? `<button class="btn btn-sm" id="btnNewUser">新增用户</button>` : ""}
          <input class="form-control" id="userKw" style="width:200px;height:32px" placeholder="搜索账号/昵称" />
        </div>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>账号</th><th>昵称</th><th>状态</th><th>角色</th><th>部门</th><th>创建时间</th><th>最近登录</th><th>操作</th></tr></thead>
          <tbody>
            ${items
              .map((u) => {
                const st = u.status === "active" ? `<span class="badge badge-success">活跃</span>` : u.status === "disabled" ? `<span class="badge badge-danger">禁用</span>` : `<span class="badge badge-warning">待验证</span>`;
                const ops = canWrite
                  ? `<button class="btn btn-secondary btn-sm" data-toggle="${escapeHtml(u.id)}" data-status="${escapeHtml(u.status)}">${u.status === "disabled" ? "启用" : "禁用"}</button>
                    <button class="btn btn-text btn-sm" data-role="${escapeHtml(u.id)}">变更角色</button>`
                  : `<span class="text-muted">—</span>`;
                return `<tr data-id="${escapeHtml(u.id)}">
                  <td>${escapeHtml(u.username)}</td>
                  <td>${escapeHtml(u.nickname || "-")}</td>
                  <td>${st}</td>
                  <td>${escapeHtml((u.roles || [u.role]).filter(Boolean).join(", "))}</td>
                  <td>${escapeHtml(u.department || "-")}</td>
                  <td>${formatDateTime(u.created_at)}</td>
                  <td>${formatDateTime(u.last_login_at)}</td>
                  <td>${ops}</td>
                </tr>`;
              })
              .join("")}
          </tbody>
        </table></div>
      </div>`;

    if (!canWrite) return;

    // 启用/禁用（危险操作确认）
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

    // 角色变更：管理员只能分配已有角色，密码仍由用户本人管理。
    document.querySelectorAll("[data-role]").forEach((btn) => {
      btn.onclick = async () => {
        const id = btn.getAttribute("data-role");
        try {
          const roleData = await api.get("/roles?page=1&page_size=100");
          const choices = (roleData.items || []).map((role) => `${role.id} = ${role.name}`).join("\n");
          const picked = prompt(`输入要分配的角色 ID（可从下列选择一个）：\n${choices}`);
          if (!picked) return;
          await api.put(`/users/${id}/roles`, { role_ids: [picked.trim()] });
          toast("用户角色已更新", "success");
          pageUsers();
        } catch (e) {
          toast(e.message || "角色更新失败", "error");
        }
      };
    });

    const btnNewUser = document.getElementById("btnNewUser");
    if (btnNewUser) btnNewUser.onclick = async () => {
      const username = prompt("新用户账号（3-50 位）：");
      if (!username) return;
      const email = prompt("新用户邮箱：");
      const password = prompt("初始密码（至少 8 位）：");
      if (!email || !password) return;
      const nickname = prompt("昵称（可留空）：") || username;
      try {
        await api.post("/users", { username, email, password, nickname });
        toast("用户创建成功，已自动分配注册用户角色", "success");
        pageUsers();
      } catch (e) {
        toast(e.message || "用户创建失败", "error");
      }
    };
  } catch (e) {
    document.getElementById("pageRoot").innerHTML = `<div class="card text-danger">${escapeHtml(e.message)}</div>`;
  }
}

/* ========== 角色管理 ========== */
function openRolePermissionForm({ title, role = null, permissionData, onSave }) {
  const dialogId = `roleForm-${Date.now()}`;
  const selected = new Set(role?.permissions || []);
  document.body.insertAdjacentHTML("beforeend", `
    <div id="${dialogId}" class="modal-backdrop" style="display:flex">
      <form class="modal" style="max-width:680px;width:92%">
        <div class="modal-header"><h3>${escapeHtml(title)}</h3></div>
        <div class="modal-body">
          <label class="form-label">角色名称</label>
          <input class="form-control" name="name" value="${escapeHtml(role?.name || "")}" ${role ? "readonly" : "required"} />
          <label class="form-label" style="margin-top:12px">角色说明</label>
          <input class="form-control" name="description" value="${escapeHtml(role?.description || "")}" />
          <p class="text-muted" style="margin-top:14px">功能权限（可不勾选，创建无权限角色）</p>
          <div class="checkbox-grid">${permissionData.map((item) => `<label><input type="checkbox" name="permission" value="${escapeHtml(item.code)}" ${selected.has(item.code) ? "checked" : ""}> ${escapeHtml(item.name)} <small>${escapeHtml(item.code)}</small></label>`).join("")}</div>
        </div>
        <div class="modal-footer"><button type="button" class="btn btn-secondary" data-close>取消</button><button class="btn btn-primary" type="submit">保存</button></div>
      </form>
    </div>`);
  const root = document.getElementById(dialogId);
  root.querySelector("[data-close]").onclick = () => root.remove();
  root.querySelector("form").onsubmit = async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await onSave({ name: String(form.get("name") || "").trim(), description: String(form.get("description") || "").trim(), permission_codes: form.getAll("permission") });
      root.remove();
      pageRoles();
    } catch (error) { toast(error.message || "保存失败", "error"); }
  };
}

async function pageRoles() {
  if (!requirePerm("role:read", "角色管理")) return;
  document.getElementById("pageRoot").innerHTML = `<div class="loading">加载角色…</div>`;
  try {
    const data = await api.get("/roles?page=1&page_size=50");
    const items = data.items || [];
    document.getElementById("pageRoot").innerHTML = `
      <div class="card">
        <div class="toolbar"><strong>角色与权限</strong><span class="spacer"></span>
          ${hasPermission("role:write") ? `<button class="btn btn-sm" id="btnNewRole">新建角色</button>` : `<span class="text-muted">只读（需超级管理员 role:write）</span>`}
        </div>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>名称</th><th>说明</th><th>内置</th><th>权限数</th><th>操作</th></tr></thead>
          <tbody>
            ${items
              .map(
                (r) => `<tr>
                  <td>${escapeHtml(r.name)}</td>
                  <td>${escapeHtml(r.description || "")}</td>
                  <td>${r.is_builtin ? `<span class="badge">内置</span>` : "-"}</td>
                  <td>${(r.permissions || []).length}</td>
                  <td>
                    <button class="btn btn-secondary btn-sm" data-view="${escapeHtml(r.id)}">查看权限</button>
                    ${hasPermission("role:write") ? `<button class="btn btn-text btn-sm" data-edit-perms="${escapeHtml(r.id)}">配置权限</button>` : ""}
                    ${!r.is_builtin && hasPermission("role:write") ? `<button class="btn btn-danger btn-sm" data-del="${escapeHtml(r.id)}">删除</button>` : ""}
                  </td>
                </tr>`
              )
              .join("")}
          </tbody>
        </table></div>
      </div>`;

    const btnNew = document.getElementById("btnNewRole");
    if (btnNew) {
      btnNew.onclick = async () => {
        const permissionData = await api.get("/roles/permissions");
        openRolePermissionForm({ title: "新建角色", permissionData, onSave: async (data) => { await api.post("/roles", data); toast("角色创建成功", "success"); } });
      };
    }

    document.querySelectorAll("[data-view]").forEach((btn) => {
      btn.onclick = () => {
        const r = items.find((x) => x.id === btn.getAttribute("data-view"));
        alert((r?.permissions || []).join("\n") || "无");
      };
    });

    document.querySelectorAll("[data-edit-perms]").forEach((btn) => {
      btn.onclick = async () => {
        const role = items.find((item) => item.id === btn.getAttribute("data-edit-perms"));
        const permissionData = await api.get("/roles/permissions");
        openRolePermissionForm({ title: `配置“${role.name}”权限`, role, permissionData, onSave: async (data) => { await api.put(`/roles/${role.id}/permissions`, { permission_codes: data.permission_codes }); toast("角色权限已更新", "success"); } });
      };
    });

    document.querySelectorAll("[data-del]").forEach((btn) => {
      btn.onclick = async () => {
        const ok = await confirmDialog({ title: "删除角色", message: "内置角色不可删；确定删除该角色？", confirmText: "删除" });
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

/* ========== 大模型管理 ========== */
async function pageModels() {
  if (!requirePerm("model:read", "大模型管理")) return;
  document.getElementById("pageRoot").innerHTML = `<div class="loading">加载模型配置…</div>`;
  try {
    const data = await api.get("/models?page=1&page_size=50");
    const items = data.items || [];
    document.getElementById("pageRoot").innerHTML = `
      <div class="card">
        <h2 class="card-title">LLM / Embedding / Rerank</h2>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>名称</th><th>类型</th><th>提供方</th><th>启用</th><th>默认</th><th>操作</th></tr></thead>
          <tbody>
            ${items
              .map(
                (m) => `<tr>
                  <td>${escapeHtml(m.name)}</td>
                  <td><span class="badge">${escapeHtml(m.model_type)}</span></td>
                  <td>${escapeHtml(m.provider || "-")}</td>
                  <td>${m.is_enabled ? `<span class="badge badge-success">是</span>` : `<span class="badge">否</span>`}</td>
                  <td>${m.is_default ? "✓" : "-"}</td>
                  <td><button class="btn btn-secondary btn-sm" data-toggle="${escapeHtml(m.id)}" data-on="${m.is_enabled ? 1 : 0}">${m.is_enabled ? "停用" : "启用"}</button></td>
                </tr>`
              )
              .join("")}
          </tbody>
        </table></div>
      </div>`;
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

/* ========== 知识库列表 ========== */
async function pageKbList() {
  if (!requirePerm("kb:read", "知识库管理")) return;
  document.getElementById("pageRoot").innerHTML = `<div class="loading">加载知识库…</div>`;
  try {
    const data = await api.get("/knowledge-bases?page=1&page_size=50");
    const items = data.items || [];
    document.getElementById("pageRoot").innerHTML = `
      <div class="card">
        <div class="toolbar">
          <strong>知识库</strong>
          <span class="spacer"></span>
          ${hasPermission("kb:write") ? `<button class="btn btn-sm" id="btnCreateKb">创建知识库</button>` : `<span class="text-muted">只读</span>`}
        </div>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>名称</th><th>类型</th><th>可见性</th><th>文档数</th><th>状态</th><th>更新时间</th><th>操作</th></tr></thead>
          <tbody>
            ${items
              .map(
                (k) => `<tr>
                  <td>${escapeHtml(k.name)}</td>
                  <td>${escapeHtml(k.type || "-")}</td>
                  <td>${k.visibility === "public" ? `<span class="badge badge-success">公开</span>` : `<span class="badge">受限</span>`}</td>
                  <td>${escapeHtml(k.doc_count ?? 0)}</td>
                  <td>${escapeHtml(k.status || "-")}</td>
                  <td>${formatDateTime(k.updated_at)}</td>
                  <td>
                    <button class="btn btn-secondary btn-sm" data-go="/admin/knowledge-bases/${escapeHtml(k.id)}">详情</button>
                    <button class="btn btn-text btn-sm" data-go="/admin/knowledge-bases/${escapeHtml(k.id)}/documents">文档</button>
                  </td>
                </tr>`
              )
              .join("")}
          </tbody>
        </table></div>
      </div>`;
    document.querySelectorAll("[data-go]").forEach((b) => b.addEventListener("click", () => navigate(b.getAttribute("data-go"))));
    const btnCreate = document.getElementById("btnCreateKb");
    if (btnCreate) {
      btnCreate.onclick = async () => {
        const name = prompt("知识库名称");
        if (!name) return;
        try {
          const kb = await api.post("/knowledge-bases", {
            name,
            type: "general",
            visibility: "restricted",
            description: "",
            tags: [],
          });
          toast("创建成功", "success");
          navigate(`/admin/knowledge-bases/${kb.id || ""}`);
        } catch (e) {
          toast(e.message || "创建失败", "error");
        }
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
        <div class="toolbar">
          <button class="btn btn-secondary btn-sm" data-go="/admin/knowledge-bases">返回列表</button>
          <button class="btn btn-sm" data-go="/admin/knowledge-bases/${escapeHtml(id)}/documents">文档管理</button>
          <button class="btn btn-sm" data-go="/admin/knowledge-bases/${escapeHtml(id)}/snapshots">快照管理</button>
          ${canWrite ? `<button class="btn btn-sm" id="btnEditKb">编辑</button>` : ""}
          ${canWrite ? `<button class="btn btn-danger btn-sm" id="btnDeleteKb">删除</button>` : ""}
          ${hasPermission("kb:vectorize") ? `<button class="btn btn-secondary btn-sm" id="btnRevec">重新向量化</button>` : ""}
        </div>
        <div class="detail-grid">
          <div class="card">
            <h3 class="card-title">${escapeHtml(k.name)}</h3>
            <p>${escapeHtml(k.description || "无简介")}</p>
            <p class="text-muted">类型：${escapeHtml(k.type)} · 标签：${escapeHtml((k.tags || []).join(", ") || "-")}</p>
            <p>可见性：${escapeHtml(k.visibility)} · 状态：${escapeHtml(k.status)}</p>
            <p>Embedding：${escapeHtml(k.embedding_model)} · 索引版本：${escapeHtml(k.current_index_version)}</p>
            <p>分段：size=${escapeHtml(k.chunk_size)} overlap=${escapeHtml(k.chunk_overlap)}</p>
          </div>
          <div class="card">
            <h3 class="card-title">概览</h3>
            <div class="stat-grid">
              <div class="stat-card"><div class="label">文档数</div><div class="value">${k.doc_count ?? 0}</div></div>
              <div class="stat-card"><div class="label">分段数</div><div class="value">${k.chunk_count ?? 0}</div></div>
            </div>
            <p class="text-muted">创建：${formatDateTime(k.created_at)}<br/>更新：${formatDateTime(k.updated_at)}</p>
            <h4>权限配置说明</h4>
            <p class="text-muted">可为用户/角色配置只读、上传、维护、回退等资源级权限；变更将记审计日志。前端隐藏菜单不能替代后端鉴权。</p>
          </div>
        </div>`;

      document.querySelectorAll("[data-go]").forEach((b) => b.addEventListener("click", () => navigate(b.getAttribute("data-go"))));

      const btnEdit = document.getElementById("btnEditKb");
      if (btnEdit) {
        btnEdit.onclick = async () => {
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
              <label class="text-muted">可见性</label>
              <select class="form-control" id="editVisibility" style="margin:6px 0 12px">
                <option value="public" ${k.visibility === "public" ? "selected" : ""}>公开</option>
                <option value="restricted" ${k.visibility === "restricted" ? "selected" : ""}>受限</option>
              </select>
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
          const visibility = result.root.querySelector("#editVisibility")?.value;
          const tags = result.root.querySelector("#editTags")?.value?.split(",").map((t) => t.trim()).filter(Boolean) || [];
          const description = result.root.querySelector("#editDesc")?.value?.trim() || undefined;
          result.root.remove();
          if (!name) {
            toast("请填写名称", "error");
            return;
          }
          try {
            await api.put(`/knowledge-bases/${id}`, { name, type, visibility, tags, description });
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
          const ok = await confirmDialog({
            title: "重新向量化",
            message: "将创建变更快照并后台重建索引，期间在线问答不中断。确定开始？",
            confirmText: "开始",
            danger: false,
          });
          if (!ok) return;
          try {
            await api.post(`/knowledge-bases/${id}/re-vectorize`, {});
            toast("已提交向量化任务", "success");
          } catch (e) {
            toast(e.message || "已模拟提交任务", "success");
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
  try {
    const data = await api.get(`/knowledge-bases/${kbId}/documents?page=1&page_size=50`);
    const items = data.items || [];
    document.getElementById("pageRoot").innerHTML = `
      <div class="toolbar">
        <button class="btn btn-secondary btn-sm" data-go="/admin/knowledge-bases/${escapeHtml(kbId)}">返回详情</button>
        <span class="spacer"></span>
        <input type="file" id="adminFile" />
        <button class="btn btn-sm" id="btnAdminUpload">上传</button>
      </div>
      <div class="card">
        <h3 class="card-title">文档列表 · 分段 / 预处理 / 向量化状态</h3>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>文件名</th><th>大小</th><th>状态</th><th>上传时间</th><th>操作</th></tr></thead>
          <tbody>
            ${items
              .map(
                (d) => `<tr>
                  <td>${escapeHtml(d.filename || d.name)}</td>
                  <td>${escapeHtml(d.size ?? "-")}</td>
                  <td><span class="badge">${escapeHtml(d.status)}</span></td>
                  <td>${formatDateTime(d.created_at)}</td>
                  <td><button class="btn btn-danger btn-sm" data-del="${escapeHtml(d.id)}">删除</button></td>
                </tr>`
              )
              .join("")}
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
        await api.upload(`/knowledge-bases/${kbId}/documents`, fd);
        toast("上传成功", "success");
        pageDocuments(kbId);
      } catch (e) {
        toast(e.message || "演示模式：已模拟上传", "success");
      }
    };
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
      <div class="toolbar">
        <button class="btn btn-secondary btn-sm" data-go="/admin/knowledge-bases/${escapeHtml(kbId)}">返回知识库详情</button>
        <span class="spacer"></span>
        ${
          canWrite
            ? `<button class="btn btn-sm" id="btnCreateSnap">手动创建快照</button>`
            : `<span class="text-muted">只读（创建/删除需 snapshot:write）</span>`
        }
      </div>
      <div class="card">
        <h3 class="card-title">历史快照与回退</h3>
        <p class="text-muted" style="margin-top:-4px;margin-bottom:12px">
          变更前会自动留存快照；回退前将强制生成「回退保护」快照，并新建索引版本（不覆盖历史）。默认最多保留 50 份 / 90 天。
        </p>
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
  document.getElementById("pageRoot").innerHTML = `<div class="loading">加载测试数据…</div>`;
  try {
    const cases = await api.get("/hit-tests/cases?page=1&page_size=20");
    const runs = await api.get("/hit-tests/runs?page=1&page_size=20");
    document.getElementById("pageRoot").innerHTML = `
      <div class="detail-grid">
        <div class="card">
          <h3 class="card-title">测试用例</h3>
          <div class="table-wrap"><table class="table">
            <thead><tr><th>问题</th><th>期望文档</th><th>创建时间</th></tr></thead>
            <tbody>${(cases.items || [])
              .map((c) => `<tr><td>${escapeHtml(c.question)}</td><td>${escapeHtml(c.expect_doc || "-")}</td><td>${formatDateTime(c.created_at)}</td></tr>`)
              .join("")}</tbody>
          </table></div>
          <button class="btn btn-sm" id="btnRunTest" style="margin-top:12px">执行测试</button>
        </div>
        <div class="card">
          <h3 class="card-title">运行记录</h3>
          <div class="table-wrap"><table class="table">
            <thead><tr><th>ID</th><th>命中率</th><th>题目数</th><th>状态</th><th>时间</th></tr></thead>
            <tbody>${(runs.items || [])
              .map(
                (r) => `<tr><td>${escapeHtml(r.id)}</td><td>${Math.round((r.hit_rate || 0) * 100)}%</td><td>${escapeHtml(r.total ?? "-")}</td><td>${escapeHtml(r.status)}</td><td>${formatDateTime(r.created_at)}</td></tr>`
              )
              .join("")}</tbody>
          </table></div>
        </div>
      </div>`;
    document.getElementById("btnRunTest").onclick = async () => {
      try {
        await api.post("/hit-tests/runs", { questions: ["平台主色是什么？"] });
        toast("测试任务已受理", "success");
        pageHitTest();
      } catch (e) {
        toast(e.message || "已模拟执行", "success");
      }
    };
  } catch (e) {
    document.getElementById("pageRoot").innerHTML = `<div class="card text-danger">${escapeHtml(e.message)}</div>`;
  }
}

/* ========== 审计日志（产品手册 5.8.5） ========== */
const AUDIT_ACTION_LABELS = {
  "snapshot.create": "创建快照",
  "snapshot.auto_create": "自动创建快照",
  "snapshot.rollback": "回退快照",
  "snapshot.delete": "删除快照",
  "snapshot.index_activate": "激活索引版本",
  "kb.create": "创建知识库",
  "kb.update": "更新知识库",
  "kb.delete": "删除知识库",
  "doc.upload": "上传文档",
  "doc.delete": "删除文档",
  "doc.normalize": "规范化文档",
  "doc.resegment": "重分段",
  "role.permissions": "变更角色权限",
  "user.update": "更新用户",
  "user.status": "变更用户状态",
};

const AUDIT_RESOURCE_LABELS = {
  snapshot: "快照",
  kb: "知识库",
  knowledge_base: "知识库",
  document: "文档",
  user: "用户",
  role: "角色",
};

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
      <div class="card">
        <div class="toolbar">
          <strong>操作审计日志</strong>
          <span class="spacer"></span>
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
        <p class="text-muted" style="margin:0 0 12px">记录操作者、时间、对象、请求标识与结果；回退类操作的 detail 中含前后索引版本。</p>
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
        <p class="text-muted" style="margin-top:8px">共 ${escapeHtml(data.total ?? items.length)} 条</p>
      </div>`;

    const actionEl = document.getElementById("auditAction");
    const resourceEl = document.getElementById("auditResource");
    const resultEl = document.getElementById("auditResult");
    if (actionEl) actionEl.value = filters.action || "";
    if (resourceEl) resourceEl.value = filters.resource_type || "";
    if (resultEl) resultEl.value = filters.result || "";

    document.getElementById("btnAuditFilter").onclick = () =>
      load({
        action: actionEl.value || undefined,
        resource_type: resourceEl.value || undefined,
        result: resultEl.value || undefined,
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
      </ul>`
      : `<p class="text-muted">${escapeHtml(stats?.error || "暂无统计")}</p>`;
  document.getElementById("pageRoot").innerHTML = `
    <div class="card" style="margin-bottom:12px">
      <h3 class="card-title">健康检查</h3>
      <p>总体状态：<strong>${escapeHtml(health.status)}</strong>
        ${health.uptime_seconds != null ? `<span class="text-muted"> · uptime ${health.uptime_seconds}s</span>` : ""}
      </p>
      <ul class="list-plain">${checksHtml || "<li class='text-muted'>无组件检查数据</li>"}</ul>
    </div>
    <div class="card" style="margin-bottom:12px">
      <h3 class="card-title">系统统计</h3>
      ${statsHtml}
    </div>
    <div class="card">
      <h3 class="card-title">Grafana 面板</h3>
      <p class="text-muted">经 Nginx 反代嵌入本地 Grafana（Prometheus 数据源）。直连：
        <a href="http://localhost:8080/grafana/" target="_blank" rel="noopener">http://localhost:8080/grafana/</a>
        或 <a href="http://localhost:3001/" target="_blank" rel="noopener">:3001</a>
      </p>
      <div class="embed-frame" style="padding:0;min-height:640px">
        <iframe
          title="Grafana"
          src="/grafana/d/rag-overview?orgId=1&kiosk"
          style="width:100%;height:640px;border:0;border-radius:8px;background:#0b1220"
          loading="lazy"
          referrerpolicy="no-referrer"
        ></iframe>
      </div>
    </div>`;
}

/* ========== 启动 ========== */
document.addEventListener("rag:demo-mode", syncDemoBanner);

[
  "/admin",
  "/admin/users",
  "/admin/roles",
  "/admin/models",
  "/admin/knowledge-bases",
  "/admin/knowledge-bases/:id",
  "/admin/knowledge-bases/:id/documents",
  "/admin/knowledge-bases/:id/snapshots",
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
syncDemoBanner();
