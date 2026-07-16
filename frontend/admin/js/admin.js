/**
 * 管理端公共脚本：Token、请求封装、导航高亮
 */
(function () {
  const API_BASE = localStorage.getItem("api_base") || "http://localhost:8000/api/v1";

  function getToken() {
    return localStorage.getItem("access_token") || "";
  }

  async function api(path, options = {}) {
    const headers = Object.assign(
      { "Content-Type": "application/json", "X-Request-Id": crypto.randomUUID() },
      options.headers || {}
    );
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;

    const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const msg = data.message || data.detail || res.statusText;
      throw new Error(msg);
    }
    return data;
  }

  function highlightNav(page) {
    document.querySelectorAll(".sidebar a").forEach((a) => {
      if (a.dataset.page === page) a.classList.add("active");
    });
  }

  window.AdminApp = { API_BASE, getToken, api, highlightNav };
})();
