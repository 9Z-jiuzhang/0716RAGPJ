/**
 * 知识库管理 API 客户端
 * @module KnowledgeBaseAPI
 */

const BASE_URL = '/api/v1';

/**
 * 获取认证 Token
 * @returns {string} Bearer Token
 */
function getToken() {
  return localStorage.getItem('access_token');
}

/**
 * 创建请求配置
 * @param {object} options - 请求选项
 * @returns {object} 请求配置
 */
function createRequestConfig(options = {}) {
  const token = getToken();
  const config = {
    headers: {
      'Content-Type': 'application/json',
    },
    ...options,
  };
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
}

/**
 * 创建知识库
 * @param {object} data - 知识库数据
 * @param {string} data.name - 名称
 * @param {string} data.type - 类型
 * @param {string[]} data.tags - 标签
 * @param {string} data.description - 描述
 * @param {string} data.visibility - 可见性
 * @param {string} data.embedding_model - 嵌入模型
 * @param {number} data.chunk_size - 分段大小
 * @param {number} data.chunk_overlap - 分段重叠
 * @returns {Promise<object>} 响应数据
 */
export async function createKnowledgeBase(data) {
  const response = await fetch(`${BASE_URL}/knowledge-bases`, {
    method: 'POST',
    ...createRequestConfig(),
    body: JSON.stringify(data),
  });
  return response.json();
}

/**
 * 获取知识库列表
 * @param {object} params - 查询参数
 * @param {number} params.page - 页码
 * @param {number} params.page_size - 每页大小
 * @param {string} params.name - 名称筛选
 * @param {string} params.type - 类型筛选
 * @param {string} params.tag - 标签筛选
 * @returns {Promise<object>} 响应数据
 */
export async function getKnowledgeBaseList(params = {}) {
  const url = new URL(`${BASE_URL}/knowledge-bases`);
  Object.entries(params).forEach(([key, value]) => {
    if (value) url.searchParams.append(key, value);
  });
  const response = await fetch(url.toString(), createRequestConfig());
  return response.json();
}

/**
 * 获取知识库详情
 * @param {string} id - 知识库ID
 * @returns {Promise<object>} 响应数据
 */
export async function getKnowledgeBase(id) {
  const response = await fetch(`${BASE_URL}/knowledge-bases/${id}`, createRequestConfig());
  return response.json();
}

/**
 * 更新知识库
 * @param {string} id - 知识库ID
 * @param {object} data - 更新数据
 * @returns {Promise<object>} 响应数据
 */
export async function updateKnowledgeBase(id, data) {
  const response = await fetch(`${BASE_URL}/knowledge-bases/${id}`, {
    method: 'PUT',
    ...createRequestConfig(),
    body: JSON.stringify(data),
  });
  return response.json();
}

/**
 * 删除知识库
 * @param {string} id - 知识库ID
 * @param {boolean} permanent - 是否物理删除
 * @returns {Promise<object>} 响应数据
 */
export async function deleteKnowledgeBase(id, permanent = false) {
  const url = new URL(`${BASE_URL}/knowledge-bases/${id}`);
  url.searchParams.append('permanent', permanent);
  const response = await fetch(url.toString(), {
    method: 'DELETE',
    ...createRequestConfig(),
  });
  return response.json();
}

/**
 * 重新向量化知识库
 * @param {string} id - 知识库ID
 * @returns {Promise<object>} 响应数据
 */
export async function reVectorizeKnowledgeBase(id) {
  const response = await fetch(`${BASE_URL}/knowledge-bases/${id}/re-vectorize`, {
    method: 'POST',
    ...createRequestConfig(),
  });
  return response.json();
}

/**
 * 获取向量化状态
 * @param {string} id - 知识库ID
 * @returns {Promise<object>} 响应数据
 */
export async function getVectorizeStatus(id) {
  const response = await fetch(`${BASE_URL}/knowledge-bases/${id}/vectorize-status`, createRequestConfig());
  return response.json();
}

/**
 * 更新知识库权限
 * @param {string} id - 知识库ID
 * @param {object} data - 权限数据
 * @param {Array} data.permissions - 权限列表
 * @returns {Promise<object>} 响应数据
 */
export async function updateKnowledgeBasePermissions(id, data) {
  const response = await fetch(`${BASE_URL}/knowledge-bases/${id}/permissions`, {
    method: 'PUT',
    ...createRequestConfig(),
    body: JSON.stringify(data),
  });
  return response.json();
}