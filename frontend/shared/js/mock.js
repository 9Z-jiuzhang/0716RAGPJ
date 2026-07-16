/**
 * 演示数据与 Mock 接口（后端未实现时可完整演示 5.1 前端）
 * 角色对齐手册 §3：超级/普通管理员、A/B 部门员工（知识库隔离）
 */

import { uuid } from "./utils.js";
import {
  getUser,
  isAdminUser,
  isSuperAdmin,
  getDepartment,
  getAccessibleKbIds,
} from "./auth.js";

/** 手册权限全集（超级管理员） */
const PERMS_ALL = [
  "user:read", "user:write", "role:read", "role:write",
  "kb:read", "kb:write", "kb:upload", "kb:vectorize",
  "doc:read", "doc:write", "doc:segment", "qa:ask",
  "test:read", "test:write", "snapshot:read", "snapshot:write", "snapshot:restore",
  "model:read", "model:write", "system:read", "audit:read",
];

/** 普通管理员：全量知识库/测试/监控，无用户角色写入与模型写入（手册系统管理能力拆分） */
const PERMS_ADMIN = [
  "qa:ask",
  "kb:read", "kb:write", "kb:upload", "kb:vectorize",
  "doc:read", "doc:write", "doc:segment",
  "test:read", "test:write",
  "snapshot:read", "snapshot:write", "snapshot:restore",
  "model:read",
  "system:read", "audit:read",
  "user:read",
  "role:read",
];

/** 部门员工 ≈ 手册 kb_admin：本部门库维护/上传/测试/快照，无用户角色与全局系统配置 */
const PERMS_STAFF = [
  "qa:ask",
  "kb:read", "kb:upload", "kb:vectorize",
  "doc:read", "doc:write", "doc:segment",
  "test:read", "test:write",
  "snapshot:read", "snapshot:write", "snapshot:restore",
];

/** 超级管理员 */
const demoSuperAdmin = {
  id: "u-super",
  username: "super",
  nickname: "超级管理员",
  email: "super@example.com",
  role: "super_admin",
  roles: ["super_admin", "admin"],
  is_super_admin: true,
  permissions: PERMS_ALL.slice(),
  status: "active",
  created_at: "2026-07-01T10:00:00Z",
  last_login_at: new Date().toISOString(),
};

/** 普通管理员 */
const demoAdmin = {
  id: "u-admin",
  username: "admin",
  nickname: "普通管理员",
  email: "admin@example.com",
  role: "admin",
  roles: ["admin"],
  is_super_admin: false,
  permissions: PERMS_ADMIN.slice(),
  status: "active",
  created_at: "2026-07-01T10:00:00Z",
  last_login_at: new Date().toISOString(),
};

/** A 部门员工（授权 A 部门知识库） */
const demoStaffA = {
  id: "u-staff-a",
  username: "staff_a",
  nickname: "A部门员工",
  email: "staff_a@example.com",
  role: "staff_dept_a",
  roles: ["staff_dept_a", "kb_admin", "staff"],
  department: "A",
  kb_ids: ["kb-dept-a", "kb-public-1"],
  permissions: PERMS_STAFF.slice(),
  status: "active",
  created_at: "2026-06-15T10:00:00Z",
  last_login_at: new Date().toISOString(),
};

/** B 部门员工 */
const demoStaffB = {
  id: "u-staff-b",
  username: "staff_b",
  nickname: "B部门员工",
  email: "staff_b@example.com",
  role: "staff_dept_b",
  roles: ["staff_dept_b", "kb_admin", "staff"],
  department: "B",
  kb_ids: ["kb-dept-b", "kb-public-1"],
  permissions: PERMS_STAFF.slice(),
  status: "active",
  created_at: "2026-06-16T10:00:00Z",
  last_login_at: new Date().toISOString(),
};

/** 注册用户 */
const demoUserOnly = {
  id: "u-user",
  username: "user",
  nickname: "注册用户",
  email: "user@example.com",
  role: "user",
  roles: ["user"],
  permissions: ["qa:ask"],
  status: "active",
  created_at: "2026-06-20T10:00:00Z",
  last_login_at: new Date().toISOString(),
};

/** 兼容旧名 */
const demoUser = demoSuperAdmin;
const demoStaff = demoStaffA;

/** 按用户名解析演示角色（密码任意）；供登录与兜底复用 */
/** 是否为内置演示账号名（与 resolveDemoLoginUser 保持同步） */
export function isBuiltinDemoUsername(username) {
  const name = String(username || "").trim().toLowerCase();
  return [
    "super", "superadmin", "超级管理员", "demo",
    "admin", "管理员", "普通管理员",
    "staff_a", "staffa", "a", "部门a", "dept_a",
    "staff_b", "staffb", "b", "部门b", "dept_b", "staff", "员工",
    "user",
  ].includes(name);
}

export function resolveDemoLoginUser(username) {
  const raw = String(username || "").trim();
  const name = raw.toLowerCase();
  const now = new Date().toISOString();
  if (["super", "superadmin", "超级管理员", "demo"].includes(name)) {
    return { ...demoSuperAdmin, username: raw || "super", last_login_at: now };
  }
  if (["admin", "管理员", "普通管理员"].includes(name)) {
    return { ...demoAdmin, username: raw || "admin", last_login_at: now };
  }
  if (["staff_a", "staffa", "a", "部门a", "dept_a"].includes(name)) {
    return { ...demoStaffA, username: raw || "staff_a", last_login_at: now };
  }
  if (["staff_b", "staffb", "b", "部门b", "dept_b", "staff", "员工"].includes(name)) {
    return { ...demoStaffB, username: raw || "staff_b", last_login_at: now };
  }
  return {
    ...demoUserOnly,
    id: `u-${name || "user"}`,
    username: raw || "user",
    nickname: raw || "注册用户",
    last_login_at: now,
  };
}

/** 兼容旧内部调用 */
let demoKbs = [
  {
    id: "kb-public-1",
    name: "公开产品手册",
    type: "产品手册",
    tags: ["公开", "手册"],
    description: "面向访客的公开知识库",
    visibility: "public",
    department: "",
    departments: [],
    embedding_model: "bge-m3",
    chunk_size: 500,
    chunk_overlap: 50,
    status: "active",
    doc_count: 12,
    chunk_count: 320,
    current_index_version: "v3",
    created_at: "2026-06-01T08:00:00Z",
    updated_at: "2026-07-10T08:00:00Z",
  },
  {
    id: "kb-dept-a",
    name: "A部门·技术文档库",
    type: "技术文档",
    tags: ["A部门", "受限"],
    description: "仅 A 部门员工与管理员可维护",
    visibility: "restricted",
    department: "A",
    departments: ["A"],
    embedding_model: "bge-m3",
    chunk_size: 800,
    chunk_overlap: 80,
    status: "active",
    doc_count: 45,
    chunk_count: 1280,
    current_index_version: "v8",
    created_at: "2026-05-12T08:00:00Z",
    updated_at: "2026-07-15T08:00:00Z",
  },
  {
    id: "kb-dept-b",
    name: "B部门·业务知识库",
    type: "业务文档",
    tags: ["B部门", "受限"],
    description: "仅 B 部门员工与管理员可维护",
    visibility: "restricted",
    department: "B",
    departments: ["B"],
    embedding_model: "bge-m3",
    chunk_size: 600,
    chunk_overlap: 60,
    status: "active",
    doc_count: 28,
    chunk_count: 640,
    current_index_version: "v4",
    created_at: "2026-05-20T08:00:00Z",
    updated_at: "2026-07-14T08:00:00Z",
  },
];

let demoUsers = [
  { ...demoSuperAdmin },
  { ...demoAdmin },
  { ...demoStaffA },
  { ...demoStaffB },
  { ...demoUserOnly },
];

let demoSessions = [
  { id: "s-1", title: "什么是 RAG？", updated_at: "2026-07-15T12:00:00Z", message_count: 4 },
];

function pageOf(items, page = 1, page_size = 20) {
  const p = Number(page) || 1;
  const ps = Number(page_size) || 20;
  const start = (p - 1) * ps;
  return { items: items.slice(start, start + ps), total: items.length, page: p, page_size: ps };
}

/** 按当前登录用户过滤可见知识库 */
function visibleKbs() {
  if (isSuperAdmin() || isAdminUser()) return demoKbs.slice();
  const user = getUser();
  if (!user) return demoKbs.filter((k) => k.visibility === "public");
  const ids = getAccessibleKbIds();
  const dept = getDepartment();
  return demoKbs.filter((k) => {
    if (k.visibility === "public") return true;
    if (Array.isArray(ids) && ids.includes(k.id)) return true;
    if (dept && (k.department === dept || (k.departments || []).includes(dept))) return true;
    return false;
  });
}

export async function handle(path, options = {}) {
  await new Promise((r) => setTimeout(r, 120));
  const method = (options.method || "GET").toUpperCase();
  const body = typeof options.body === "string" ? JSON.parse(options.body || "{}") : options.body || {};
  const url = new URL(path, "http://local");
  const q = Object.fromEntries(url.searchParams.entries());
  const p = url.pathname;

  if (p === "/auth/login" && method === "POST") {
    const user = resolveDemoLoginUser(body.username);
    return {
      access_token: `demo-access-${user.role}`,
      refresh_token: "demo-refresh-token",
      user,
    };
  }
  if (p === "/auth/register" && method === "POST") {
    const u = {
      ...demoUserOnly,
      id: uuid(),
      username: body.username,
      email: body.email,
      nickname: body.nickname || body.username,
    };
    demoUsers.unshift(u);
    return { id: u.id, username: u.username, email: u.email };
  }
  if (p === "/auth/me" && method === "GET") {
    const me = getUser();
    if (me && me.username) return { ...me };
    // 有 token 无用户档案：返回明确错误，禁止写成 anonymous 注册用户
    const err = new Error("UNAUTHORIZED");
    err.status = 401;
    throw err;
  }
  if (p === "/auth/refresh" && method === "POST") {
    return { access_token: "demo-access-token-refreshed", refresh_token: "demo-refresh-token" };
  }

  if (p === "/qa/sessions" && method === "GET") return pageOf(demoSessions, q.page, q.page_size);
  if (p.startsWith("/qa/sessions/") && method === "GET") {
    return {
      id: p.split("/").pop(),
      title: "演示会话",
      messages: [
        { id: "m1", role: "user", content: "什么是 RAG？", created_at: "2026-07-15T12:00:00Z" },
        {
          id: "m2",
          role: "assistant",
          content: "RAG（检索增强生成）先检索知识库，再生成回答。",
          citations: [
            { doc_id: "d1", doc_name: "产品手册.pdf", chunk_index: 3, content: "RAG 结合检索与生成…", score: 0.86 },
          ],
          created_at: "2026-07-15T12:00:05Z",
        },
      ],
    };
  }

  if (p === "/knowledge-bases" && method === "GET") {
    return pageOf(visibleKbs(), q.page, q.page_size);
  }
  if (p === "/knowledge-bases" && method === "POST") {
    const kb = {
      id: uuid(),
      name: body.name,
      type: body.type || "通用知识",
      tags: body.tags || [],
      description: body.description || "",
      visibility: body.visibility || "restricted",
      department: body.department || getDepartment() || "",
      departments: body.department ? [body.department] : getDepartment() ? [getDepartment()] : [],
      embedding_model: body.embedding_model || "bge-m3",
      chunk_size: body.chunk_size || 500,
      chunk_overlap: body.chunk_overlap || 50,
      status: "active",
      doc_count: 0,
      chunk_count: 0,
      current_index_version: "v1",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    demoKbs.unshift(kb);
    return kb;
  }
  if (/^\/knowledge-bases\/[^/]+$/.test(p) && method === "GET") {
    const id = p.split("/")[2];
    const list = visibleKbs();
    const hit = list.find((k) => k.id === id);
    if (!hit) {
      const err = new Error("知识库不存在或无权访问");
      err.status = 404;
      throw err;
    }
    return hit;
  }
  if (/\/documents$/.test(p) && method === "GET") {
    return pageOf(
      [
        { id: "doc-1", filename: "手册V2.1.pdf", status: "ready", size: 2048000, created_at: "2026-07-10T10:00:00Z" },
        { id: "doc-2", filename: "FAQ.md", status: "processing", size: 12000, created_at: "2026-07-15T11:00:00Z" },
      ],
      q.page,
      q.page_size
    );
  }
  if (/\/snapshots$/.test(p) && method === "GET") {
    return pageOf(
      [{ id: "snap-1", version: "v7", note: "重向量化前快照", created_at: "2026-07-12T09:00:00Z" }],
      q.page,
      q.page_size
    );
  }

  if (p === "/users" && method === "GET") return pageOf(demoUsers, q.page, q.page_size);
  if (p.startsWith("/users/") && method === "PATCH") {
    const id = p.split("/")[2];
    const u = demoUsers.find((x) => x.id === id);
    if (u && body.status) u.status = body.status;
    return u;
  }
  if (p === "/roles" && method === "GET") {
    return pageOf(
      [
        {
          id: "r-super",
          name: "super_admin",
          description: "超级管理员（全量权限）",
          builtin: true,
          permission_codes: PERMS_ALL,
        },
        {
          id: "r-admin",
          name: "admin",
          description: "普通管理员（无用户/角色写入、无模型写入）",
          builtin: true,
          permission_codes: PERMS_ADMIN,
        },
        {
          id: "r-staff-a",
          name: "staff_dept_a",
          description: "A部门员工（kb_admin，仅 A 部门库）",
          builtin: true,
          permission_codes: PERMS_STAFF,
        },
        {
          id: "r-staff-b",
          name: "staff_dept_b",
          description: "B部门员工（kb_admin，仅 B 部门库）",
          builtin: true,
          permission_codes: PERMS_STAFF,
        },
        {
          id: "r-user",
          name: "user",
          description: "注册用户",
          builtin: true,
          permission_codes: ["qa:ask"],
        },
      ],
      q.page,
      q.page_size
    );
  }
  if (p === "/models" && method === "GET") {
    return pageOf(
      [
        { id: "m1", name: "qwen2.5:7b", model_type: "llm", is_enabled: true, is_default: true, provider: "ollama" },
        { id: "m2", name: "bge-m3", model_type: "embedding", is_enabled: true, is_default: true, provider: "local" },
        { id: "m3", name: "bge-reranker", model_type: "rerank", is_enabled: false, is_default: false, provider: "local" },
      ],
      q.page,
      q.page_size
    );
  }

  if (p === "/hit-tests/cases" && method === "GET") {
    return pageOf([{ id: "c1", question: "平台主色是什么？", expect_doc: "产品手册", created_at: "2026-07-01T00:00:00Z" }], q.page, q.page_size);
  }
  if (p === "/hit-tests/runs" && method === "GET") {
    return pageOf([{ id: "run1", hit_rate: 0.82, total: 50, created_at: "2026-07-14T00:00:00Z", status: "done" }], q.page, q.page_size);
  }
  if (p === "/hit-tests/runs" && method === "POST") {
    return { id: uuid(), status: "accepted" };
  }
  if (p === "/audit/logs" && method === "GET") {
    return pageOf(
      [
        { id: "a1", user_name: "super", action: "kb.create", resource_type: "knowledge_base", result: "success", created_at: "2026-07-15T08:00:00Z" },
        { id: "a2", user_name: "staff_a", action: "doc.upload", resource_type: "document", result: "success", created_at: "2026-07-15T09:00:00Z" },
      ],
      q.page,
      q.page_size
    );
  }
  if (p === "/monitor/stats" && method === "GET") {
    return {
      kb_count: demoKbs.length,
      doc_count: 85,
      user_count: demoUsers.length,
      active_sessions: 6,
      queue_length: 2,
      qa_trend_7d: [12, 18, 15, 22, 30, 28, 35],
      hit_rate_trend_7d: [0.71, 0.74, 0.76, 0.79, 0.81, 0.8, 0.83],
      cpu: 42,
      memory: 61,
      disk: 55,
      error_24h: [1, 0, 2, 0, 0, 1, 0, 3, 0, 0, 1, 0],
    };
  }
  if (p === "/monitor/health" && method === "GET") {
    return { status: "healthy", checks: { postgres: "ok", redis: "ok", chroma: "ok", minio: "ok" } };
  }

  return {};
}

/** 演示 SSE 打字机效果 */
export async function askStreamMock(body, { onEvent, signal } = {}) {
  const text =
    "根据授权知识库检索：RAG 先检索相关分段，再由大模型生成回答，并附带引用来源与置信提示。";
  const chunks = text.match(/.{1,8}/g) || [text];
  for (const c of chunks) {
    if (signal?.aborted) return;
    await new Promise((r) => setTimeout(r, 40));
    onEvent?.("chunk", { content: c });
  }
  onEvent?.("citations", {
    items: [
      {
        doc_id: "d1",
        doc_name: "公开产品手册.pdf",
        chunk_index: 2,
        content: "回答应展示引用来源、文档名、分段序号和置信提示…",
        score: 0.91,
      },
    ],
  });
  onEvent?.("done", { session_id: body.session_id || uuid(), confidence: "high" });
}
