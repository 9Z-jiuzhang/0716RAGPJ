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
          <span class="text-muted">${canWrite ? "可启用/禁用与重置密码" : "只读（需超级管理员 user:write）"}</span>
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
                    <button class="btn btn-text btn-sm" data-reset="${escapeHtml(u.id)}">重置密码</button>`
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

    // 重置密码
    document.querySelectorAll("[data-reset]").forEach((btn) => {
      btn.onclick = async () => {
        const id = btn.getAttribute("data-reset");
        const ok = await confirmDialog({ title: "重置密码", message: "将把密码重置为临时口令 Temp@123456，确定？", confirmText: "重置" });
        if (!ok) return;
        try {
          await api.post(`/users/${id}/reset-password`, { new_password: "Temp@123456" });
          toast("已重置密码", "success");
        } catch (e) {
          toast(e.message || "演示模式已记录操作", "success");
        }
      };
    });
  } catch (e) {
    document.getElementById("pageRoot").innerHTML = `<div class="card text-danger">${escapeHtml(e.message)}</div>`;
  }
}

/* ========== 角色管理 ========== */
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
                  <td>${r.builtin ? `<span class="badge">内置</span>` : "-"}</td>
                  <td>${(r.permission_codes || []).length}</td>
                  <td>
                    <button class="btn btn-secondary btn-sm" data-view="${escapeHtml(r.id)}">查看权限</button>
                    ${!r.builtin && hasPermission("role:write") ? `<button class="btn btn-danger btn-sm" data-del="${escapeHtml(r.id)}">删除</button>` : ""}
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
        const name = prompt("角色名称");
        if (!name) return;
        try {
          await api.post("/roles", { name, description: "", permission_codes: ["qa:ask"] });
          toast("已创建", "success");
          pageRoles();
        } catch (e) {
          toast(e.message || "创建失败（演示可忽略）", "error");
        }
      };
    }

    document.querySelectorAll("[data-view]").forEach((btn) => {
      btn.onclick = () => {
        const r = items.find((x) => x.id === btn.getAttribute("data-view"));
        alert((r?.permission_codes || []).join("\n") || "无");
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
            type: "通用知识",
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
  document.getElementById("pageRoot").innerHTML = `<div class="loading">加载详情…</div>`;
  try {
    const k = await api.get(`/knowledge-bases/${id}`);
    document.getElementById("pageRoot").innerHTML = `
      <div class="toolbar">
        <button class="btn btn-secondary btn-sm" data-go="/admin/knowledge-bases">返回列表</button>
        <button class="btn btn-sm" data-go="/admin/knowledge-bases/${escapeHtml(id)}/documents">文档管理</button>
        <button class="btn btn-sm" data-go="/admin/knowledge-bases/${escapeHtml(id)}/snapshots">快照管理</button>
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

/* ========== 快照管理 ========== */
async function pageSnapshots(kbId) {
  if (!requirePerm("snapshot:read", "快照管理")) return;
  document.getElementById("pageRoot").innerHTML = `<div class="loading">加载快照…</div>`;
  try {
    const data = await api.get(`/knowledge-bases/${kbId}/snapshots?page=1&page_size=50`);
    const items = data.items || [];
    document.getElementById("pageRoot").innerHTML = `
      <div class="toolbar"><button class="btn btn-secondary btn-sm" data-go="/admin/knowledge-bases/${escapeHtml(kbId)}">返回详情</button></div>
      <div class="card">
        <h3 class="card-title">历史快照与回退</h3>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>版本</th><th>备注</th><th>时间</th><th>操作</th></tr></thead>
          <tbody>
            ${items
              .map(
                (s) => `<tr>
                  <td>${escapeHtml(s.version || s.id)}</td>
                  <td>${escapeHtml(s.note || "")}</td>
                  <td>${formatDateTime(s.created_at)}</td>
                  <td><button class="btn btn-secondary btn-sm" data-restore="${escapeHtml(s.id)}">回退到此版本</button></td>
                </tr>`
              )
              .join("")}
          </tbody>
        </table></div>
      </div>`;
    document.querySelectorAll("[data-go]").forEach((b) => b.addEventListener("click", () => navigate(b.getAttribute("data-go"))));
    document.querySelectorAll("[data-restore]").forEach((btn) => {
      btn.onclick = async () => {
        const ok = await confirmDialog({
          title: "回退快照",
          message: "回退将切换当前索引版本，请确认已评估影响。",
          confirmText: "回退",
        });
        if (!ok) return;
        try {
          await api.post(`/knowledge-bases/${kbId}/snapshots/${btn.getAttribute("data-restore")}/restore`, {});
          toast("已提交回退", "success");
        } catch (e) {
          toast(e.message || "演示模式：已记录回退请求", "success");
        }
      };
    });
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

/* ========== 审计日志 ========== */
async function pageAudit() {
  if (!requirePerm("audit:read", "审计日志")) return;
  document.getElementById("pageRoot").innerHTML = `<div class="loading">加载审计…</div>`;
  try {
    const data = await api.get("/audit/logs?page=1&page_size=50");
    const items = data.items || [];
    document.getElementById("pageRoot").innerHTML = `
      <div class="card">
        <h3 class="card-title">操作记录</h3>
        <div class="table-wrap"><table class="table">
          <thead><tr><th>用户</th><th>动作</th><th>资源类型</th><th>结果</th><th>时间</th></tr></thead>
          <tbody>${items
            .map(
              (a) => `<tr>
                <td>${escapeHtml(a.user_name || a.user_id || "-")}</td>
                <td>${escapeHtml(a.action)}</td>
                <td>${escapeHtml(a.resource_type)}</td>
                <td>${a.result === "success" ? `<span class="badge badge-success">成功</span>` : `<span class="badge badge-danger">${escapeHtml(a.result)}</span>`}</td>
                <td>${formatDateTime(a.created_at)}</td>
              </tr>`
            )
            .join("")}</tbody>
        </table></div>
      </div>`;
  } catch (e) {
    document.getElementById("pageRoot").innerHTML = `<div class="card text-danger">${escapeHtml(e.message)}</div>`;
  }
}

/* ========== 系统监控（Grafana 嵌入占位） ========== */
async function pageMonitor() {
  if (!requirePerm("system:read", "系统监控")) return;
  let health = { status: "unknown", checks: {} };
  try {
    health = await api.get("/monitor/health");
  } catch {
    /* ignore */
  }
  document.getElementById("pageRoot").innerHTML = `
    <div class="card" style="margin-bottom:12px">
      <h3 class="card-title">健康检查</h3>
      <p>总体状态：<strong>${escapeHtml(health.status)}</strong></p>
      <p class="text-muted">${Object.entries(health.checks || {})
        .map(([k, v]) => `${k}=${v}`)
        .join(" · ")}</p>
    </div>
    <div class="card">
      <h3 class="card-title">Grafana 面板嵌入</h3>
      <p class="text-muted">正式环境将嵌入本地 Grafana（Prometheus 指标）。以下为占位区域，保持布局可落地。</p>
      <div class="embed-frame">
        <strong>Grafana 面板占位</strong>
        <span>正式环境将嵌入本地 Grafana（Prometheus 指标）</span>
        <span class="text-muted">占位地址：http://localhost:3000</span>
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
