/**
 * 文档管理 API 客户端
 * @module DocumentAPI
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
    headers: {},
    ...options,
  };
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
}

/**
 * 获取文档列表
 * @param {string} kbId - 知识库ID
 * @param {object} params - 查询参数
 * @param {number} params.page - 页码
 * @param {number} params.page_size - 每页大小
 * @param {string} params.filename - 文件名搜索
 * @param {string} params.file_type - 文件类型筛选
 * @param {string} params.status - 状态筛选
 * @returns {Promise<object>} 响应数据
 */
export async function getDocumentList(kbId, params = {}) {
  const url = new URL(`${BASE_URL}/knowledge-bases/${kbId}/documents`);
  Object.entries(params).forEach(([key, value]) => {
    if (value) url.searchParams.append(key, value);
  });
  const response = await fetch(url.toString(), createRequestConfig());
  return response.json();
}

/**
 * 上传文档
 * @param {string} kbId - 知识库ID
 * @param {FileList} files - 文件列表
 * @returns {Promise<object>} 响应数据
 */
export async function uploadDocuments(kbId, files) {
  const formData = new FormData();
  Array.from(files).forEach((file) => {
    formData.append('files', file);
  });
  const response = await fetch(`${BASE_URL}/knowledge-bases/${kbId}/documents/upload`, {
    method: 'POST',
    ...createRequestConfig(),
    body: formData,
  });
  return response.json();
}

/**
 * 获取文档详情
 * @param {string} kbId - 知识库ID
 * @param {string} docId - 文档ID
 * @returns {Promise<object>} 响应数据
 */
export async function getDocument(kbId, docId) {
  const response = await fetch(`${BASE_URL}/knowledge-bases/${kbId}/documents/${docId}`, createRequestConfig());
  return response.json();
}

/**
 * 删除文档
 * @param {string} kbId - 知识库ID
 * @param {string} docId - 文档ID
 * @returns {Promise<object>} 响应数据
 */
export async function deleteDocument(kbId, docId) {
  const response = await fetch(`${BASE_URL}/knowledge-bases/${kbId}/documents/${docId}`, {
    method: 'DELETE',
    ...createRequestConfig(),
  });
  return response.json();
}

/**
 * 更新分段规则
 * @param {string} kbId - 知识库ID
 * @param {string} docId - 文档ID
 * @param {object} data - 分段规则数据
 * @returns {Promise<object>} 响应数据
 */
export async function updateSegmentRules(kbId, docId, data) {
  const response = await fetch(`${BASE_URL}/knowledge-bases/${kbId}/documents/${docId}/segment-rules`, {
    method: 'PUT',
    ...createRequestConfig({ headers: { 'Content-Type': 'application/json' } }),
    body: JSON.stringify(data),
  });
  return response.json();
}

/**
 * 重新分段文档
 * @param {string} kbId - 知识库ID
 * @param {string} docId - 文档ID
 * @returns {Promise<object>} 响应数据
 */
export async function reSegmentDocument(kbId, docId) {
  const response = await fetch(`${BASE_URL}/knowledge-bases/${kbId}/documents/${docId}/re-segment`, {
    method: 'POST',
    ...createRequestConfig(),
  });
  return response.json();
}

/**
 * 文档规范化
 * @param {string} kbId - 知识库ID
 * @param {string} docId - 文档ID
 * @returns {Promise<object>} 响应数据
 */
export async function normalizeDocument(kbId, docId) {
  const response = await fetch(`${BASE_URL}/knowledge-bases/${kbId}/documents/${docId}/normalize`, {
    method: 'POST',
    ...createRequestConfig(),
  });
  return response.json();
}

/**
 * 获取文档分段列表
 * @param {string} kbId - 知识库ID
 * @param {string} docId - 文档ID
 * @returns {Promise<object>} 响应数据
 */
export async function getDocumentChunks(kbId, docId) {
  const response = await fetch(`${BASE_URL}/knowledge-bases/${kbId}/documents/${docId}/chunks`, createRequestConfig());
  return response.json();
}

/**
 * 更新分段
 * @param {string} kbId - 知识库ID
 * @param {string} docId - 文档ID
 * @param {string} chunkId - 分段ID
 * @param {object} data - 分段更新数据
 * @returns {Promise<object>} 响应数据
 */
export async function updateChunk(kbId, docId, chunkId, data) {
  const response = await fetch(`${BASE_URL}/knowledge-bases/${kbId}/documents/${docId}/chunks/${chunkId}`, {
    method: 'PUT',
    ...createRequestConfig({ headers: { 'Content-Type': 'application/json' } }),
    body: JSON.stringify(data),
  });
  return response.json();
}