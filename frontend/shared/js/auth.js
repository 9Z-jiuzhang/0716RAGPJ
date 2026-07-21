/**
 * 认证与本地会话存储
 * 对齐手册 §3：RBAC + 知识库隔离
 * 角色细化：访客 / 注册用户 / A·B 部门员工 / 普通管理员 / 超级管理员
 */

import { toast } from "/assets/js/utils.js?v=gap-opt-0721h";

const KEY_ACCESS = "rag_access_token";
const KEY_REFRESH = "rag_refresh_token";
const KEY_USER = "rag_user";
const KEY_GUEST = "rag_guest_id";
const KEY_REMEMBER = "rag_remember_me";

/** 记住我：true → localStorage；false → sessionStorage（关标签即失效） */
export function getRememberMe() {
  try {
    const v = localStorage.getItem(KEY_REMEMBER);
    if (v === null || v === undefined || v === "") return true;
    return v !== "0";
  } catch {
    return true;
  }
}

export function setRememberMe(remember) {
  try {
    localStorage.setItem(KEY_REMEMBER, remember ? "1" : "0");
  } catch {
    /* ignore */
  }
}

function authStore() {
  return getRememberMe() ? localStorage : sessionStorage;
}

function clearAuthStores() {
  for (const store of [localStorage, sessionStorage]) {
    try {
      store.removeItem(KEY_ACCESS);
      store.removeItem(KEY_REFRESH);
      store.removeItem(KEY_USER);
    } catch {
      /* ignore */
    }
  }
}

export function getAccessToken() {
  return authStore().getItem(KEY_ACCESS) || localStorage.getItem(KEY_ACCESS) || sessionStorage.getItem(KEY_ACCESS) || "";
}

export function getRefreshToken() {
  return authStore().getItem(KEY_REFRESH) || localStorage.getItem(KEY_REFRESH) || sessionStorage.getItem(KEY_REFRESH) || "";
}

export function isLoggedIn() {
  return Boolean(getAccessToken());
}

export function getUser() {
  try {
    const raw = authStore().getItem(KEY_USER) || localStorage.getItem(KEY_USER) || sessionStorage.getItem(KEY_USER) || "null";
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function saveAuth({ access_token, refresh_token, user } = {}) {
  // 先读出当前值：允许只更新 user 或只更新 token，避免把另一半清掉导致「假退出」
  const prevAccess = getAccessToken();
  const prevRefresh = getRefreshToken();
  const prevUser = getUser();

  const nextAccess = access_token !== undefined ? access_token : prevAccess;
  const nextRefresh = refresh_token !== undefined ? refresh_token : prevRefresh;
  const nextUser = user !== undefined ? (user ? normalizeUser(user) : null) : prevUser;

  const store = authStore();
  clearAuthStores();
  if (nextAccess) store.setItem(KEY_ACCESS, nextAccess);
  if (nextRefresh) store.setItem(KEY_REFRESH, nextRefresh);
  if (nextUser) store.setItem(KEY_USER, JSON.stringify(nextUser));
}

/** 规范化用户对象，保证 role / roles / permissions 一致 */
export function normalizeUser(user) {
  if (!user || typeof user !== "object") return user;
  const roles = [].concat(user.role || [], user.roles || []).map(String).filter(Boolean);
  const uniq = [...new Set(roles)];
  // 唯一超管仅绑定固定账号 super；不以可分配角色判定
  const isFixedSuper = String(user.username || "") === "super";
  let role = user.role ? String(user.role) : uniq[0] || "user";
  if (isFixedSuper) {
    role = "super_admin";
  } else if (uniq.includes("admin")) {
    role = "admin";
  } else if (uniq.includes("super_admin")) {
    // 历史脏数据：非 super 账号即使带有 super_admin 也不再视为超管
    role = role === "super_admin" ? "user" : role;
  }
  const normalizedRoles = isFixedSuper
    ? ["super_admin", ...uniq.filter((r) => r !== "super_admin")]
    : uniq.filter((r) => r !== "super_admin");
  return {
    ...user,
    role,
    roles: normalizedRoles.length ? normalizedRoles : [role],
    role_labels: user.role_labels || [],
    permissions: user.permissions || user.permission_codes || [],
    department: user.department || user.dept || "",
    is_super_admin: isFixedSuper,
  };
}

/**
 * 合并本地与远端用户资料：昵称邮箱等可更新，角色权限取「更强」一侧，防止被冲成注册用户
 */
export function mergeUserProfiles(local, remote) {
  const a = normalizeUser(local || {});
  const b = normalizeUser(remote || {});
  const roleRank = (u) => {
    if (String(u.username || "") === "super" || u.is_super_admin) return 40;
    const r = new Set([].concat(u.role || [], u.roles || []));
    if (r.has("admin")) return 30;
    if (r.has("staff_dept_a") || r.has("staff_dept_b") || r.has("kb_admin") || r.has("staff")) return 20;
    if (r.has("user")) return 10;
    return 0;
  };
  const stronger = roleRank(a) >= roleRank(b) ? a : b;
  const weaker = stronger === a ? b : a;
  const perms = [...new Set([...(a.permissions || []), ...(b.permissions || [])])];
  return normalizeUser({
    ...weaker,
    ...stronger,
    nickname: b.nickname || a.nickname,
    email: b.email || a.email,
    last_login_at: b.last_login_at || a.last_login_at,
    role: stronger.role,
    roles: stronger.roles,
    role_labels: stronger.role_labels || weaker.role_labels,
    permissions: perms.length ? perms : stronger.permissions,
    department: stronger.department || weaker.department,
    kb_ids: stronger.kb_ids || weaker.kb_ids,
    is_super_admin: stronger.is_super_admin || weaker.is_super_admin,
  });
}

/** 登录时完整替换会话，避免旧 token 与错误 user 混用 */
export function replaceAuthSession({ access_token, refresh_token, user }) {
  clearAuth();
  if (!access_token || !user) {
    throw new Error("登录响应缺少 access_token 或 user");
  }
  saveAuth({ access_token, refresh_token, user: normalizeUser(user) });
}

export function clearAuth() {
  clearAuthStores();
}

export function getGuestId() {
  let id = localStorage.getItem(KEY_GUEST);
  if (!id) {
    id = crypto.randomUUID ? crypto.randomUUID() : `guest-${Date.now()}`;
    localStorage.setItem(KEY_GUEST, id);
  }
  return id;
}

/** 收集用户角色码 */
function roleSet(user = getUser()) {
  if (!user) return new Set();
  return new Set([].concat(user.role || [], user.roles || []).map(String));
}

function userFlag(key) {
  const u = getUser();
  return Boolean(u && u[key]);
}

/** 超级管理员：仅固定账号 username === "super" */
export function isSuperAdmin() {
  const user = getUser();
  if (!user) return false;
  return String(user.username || "") === "super";
}

/** 普通或超级管理员（可进管理端控制台） */
export function isAdminUser() {
  const user = getUser();
  if (!user) return false;
  if (isSuperAdmin()) return true;
  const roles = roleSet(user);
  if (roles.has("admin") || roles.has("super_admin")) return true;
  const r = String(user.role || "");
  return r === "admin" || r === "super_admin";
}

/**
 * 是否具备权限码（前端隐藏用，不能替代后端）
 * 仅超级管理员默认全放行；普通管理员与员工看 permissions 列表
 */
export function hasPermission(code) {
  const user = getUser();
  if (!user) return false;
  if (isSuperAdmin()) return true;
  const perms = user.permissions || user.permission_codes || [];
  return perms.includes(code);
}

/**
 * 主角色（导航分流）
 * guest | user | staff | admin
 */
export function getPrimaryRole() {
  if (!isLoggedIn()) return "guest";
  if (isAdminUser()) return "admin";
  const roles = roleSet();
  if (
    roles.has("kb_admin") ||
    roles.has("staff") ||
    roles.has("staff_dept_a") ||
    roles.has("staff_dept_b") ||
    roles.has("employee") ||
    hasPermission("kb:upload")
  ) {
    return "staff";
  }
  return "user";
}

/** 部门：A / B / 空（管理员或无部门用户） */
export function getDepartment() {
  const user = getUser();
  if (!user) return "";
  const d = String(user.department || user.dept || "").toUpperCase();
  if (d === "A" || d === "B") return d;
  const roles = roleSet(user);
  if (roles.has("staff_dept_a")) return "A";
  if (roles.has("staff_dept_b")) return "B";
  return "";
}

/** 展示用角色名 */
export function getRoleLabel(roleHint) {
  if (!isLoggedIn()) return "访客";
  const user = getUser() || {};
  if (Array.isArray(user.role_labels) && user.role_labels.length) {
    const dept = getDepartment();
    const base = user.role_labels[0];
    if ((base === "员工" || roleHint === "staff") && dept) return `员工·${dept}部门`;
    return user.role_labels.join("、");
  }
  if (isSuperAdmin()) return "超级管理员";
  if (isAdminUser() || roleHint === "admin") return "管理员";
  const roles = roleSet(user);
  if (roles.has("guest")) return "访客";
  const dept = getDepartment();
  const primary = roleHint || getPrimaryRole();
  if (primary === "staff") {
    return dept ? `员工·${dept}部门` : "员工";
  }
  return "注册用户";
}

/** 可访问的知识库 ID；null=管理员不限制；[]=无显式授权（非管理员） */
export function getAccessibleKbIds() {
  if (!isLoggedIn()) return [];
  if (isAdminUser() || isSuperAdmin()) return null;
  const user = getUser() || {};
  if (Array.isArray(user.kb_ids) && user.kb_ids.length) return user.kb_ids.slice();
  // 有部门时由 canAccessKb 按部门判断；无 kb_ids 不再视为「全库放行」
  return [];
}

/** 某知识库当前用户是否可操作（上传/维护） */
export function canAccessKb(kb) {
  if (!kb) return false;
  if (isSuperAdmin() || isAdminUser()) return true;
  if (!isLoggedIn()) return kb.visibility === "public";
  const ids = getAccessibleKbIds();
  if (ids === null) return true;
  if (ids.length && ids.includes(kb.id)) return true;
  const dept = getDepartment();
  if (dept && Array.isArray(kb.departments) && kb.departments.includes(dept)) return true;
  if (dept && kb.department === dept) return true;
  // 注册用户默认只能碰公开库（问答范围）；上传另受 canUpload 约束
  if (getPrimaryRole() === "user") return kb.visibility === "public";
  return false;
}

/** 是否可上传：员工；管理员在访客端也可上传 */
export function canUpload() {
  return getPrimaryRole() === "staff" || isAdminUser() || hasPermission("kb:upload");
}

/** 是否可进管理端：仅管理员；员工在访客端上传，不对管理台做深链开放 */
export function canAccessAdmin() {
  return isAdminUser();
}

/** 登录后落地页：管理员进控制台，其余进问答 */
export function getPostLoginTarget() {
  if (isAdminUser()) return { type: "admin", href: "/admin/" };
  return { type: "hash", path: "/chat" };
}

export function requireLogin(loginPath = "/login") {
  if (!isLoggedIn()) {
    toast("请先登录", "error");
    location.hash = `#${loginPath}`;
    return false;
  }
  return true;
}
