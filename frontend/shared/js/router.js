/**
 * 轻量 Hash 路由（兼容直接打开与 Nginx try_files）
 * 路径形如：#/login 、#/admin/users
 */

/** 当前路由表 */
const routes = [];

/** 注册路由：path 支持精确匹配或 :param */
export function route(path, handler) {
  routes.push({ path, handler });
}

/** 将模式转为正则 */
function compile(path) {
  const keys = [];
  const re = path
    .replace(/\//g, "\\/")
    .replace(/:([A-Za-z_]+)/g, (_, k) => {
      keys.push(k);
      return "([^/]+)";
    });
  return { re: new RegExp(`^${re}$`), keys };
}

/** 解析当前 hash 路径（去掉 #） */
export function currentPath() {
  let h = location.hash || "#/";
  if (!h.startsWith("#")) h = `#${h}`;
  let path = h.slice(1) || "/";
  if (!path.startsWith("/")) path = `/${path}`;
  // 去掉 query
  const qIndex = path.indexOf("?");
  if (qIndex >= 0) path = path.slice(0, qIndex);
  return path;
}

/** 编程式跳转 */
export function navigate(path) {
  const p = path.startsWith("#") ? path : `#${path.startsWith("/") ? path : `/${path}`}`;
  if (location.hash === p) {
    // 相同 hash 也强制刷新一次
    dispatch();
  } else {
    location.hash = p;
  }
}

/** 执行匹配 */
export function dispatch() {
  const path = currentPath();
  for (const r of routes) {
    const { re, keys } = compile(r.path);
    const m = path.match(re);
    if (!m) continue;
    const params = {};
    keys.forEach((k, i) => {
      params[k] = decodeURIComponent(m[i + 1]);
    });
    r.handler({ path, params, query: Object.fromEntries(new URLSearchParams((location.hash.split("?")[1] || ""))) });
    return;
  }
  // 未匹配：尝试 404 处理器
  const notFound = routes.find((x) => x.path === "*");
  if (notFound) notFound.handler({ path, params: {}, query: {} });
}

/** 启动监听 */
export function startRouter() {
  window.addEventListener("hashchange", dispatch);
  // 无 hash 时默认首页
  if (!location.hash) location.hash = "#/";
  else dispatch();
}
