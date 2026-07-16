/**
 * 文档管理页面
 * @module DocumentsPage
 */

import { kbStore } from '../store/kb-store.js';
import {
  getDocumentList,
  uploadDocuments,
  getDocument,
  deleteDocument,
  updateSegmentRules,
  reSegmentDocument,
  normalizeDocument,
  getDocumentChunks,
  updateChunk,
} from '../api/document-api.js';

let kbId = null;
let currentPage = 1;

/**
 * 初始化页面
 * @param {string} id - 知识库ID
 */
export async function initDocumentsPage(id) {
  kbId = id;
  await loadDocuments(currentPage);
  renderHeader();
  renderUploadArea();
  renderFilters();

  kbStore.on('documentsChange', renderTable);
  kbStore.on('loadingChange', handleLoading);
  kbStore.on('errorChange', handleError);

  window.documentsPage = {
    applyFilters: applyFilters,
    clearFilters: clearFilters,
    goToPage: goToPage,
    handleUpload: handleUpload,
    viewDocument: viewDocument,
    viewChunks: viewChunks,
    openSegmentRulesModal: openSegmentRulesModal,
    confirmDelete: confirmDelete,
    closeModal: closeModal,
  };
}

/**
 * 渲染页面头部
 */
function renderHeader() {
  const header = document.querySelector('.page-header');
  header.innerHTML = `
    <h1 class="page-title">文档管理</h1>
    <a href="/admin/knowledge-bases/${kbId}" class="btn btn-secondary">返回知识库</a>
  `;
}

/**
 * 渲染上传区域
 */
function renderUploadArea() {
  const uploadArea = document.querySelector('.upload-area');
  uploadArea.innerHTML = `
    <div class="upload-container">
      <input type="file" id="file-input" multiple accept=".pdf,.docx,.doc,.txt,.md" class="hidden">
      <div class="upload-dropzone" onclick="document.getElementById('file-input').click()">
        <div class="upload-icon upload-icon-file"></div>
        <div class="upload-text">点击或拖拽上传文档</div>
        <div class="upload-hint">支持 PDF、DOC、DOCX、TXT、Markdown 格式</div>
      </div>
      <button class="btn btn-primary" data-action="upload">上传</button>
    </div>
  `;
  uploadArea.querySelector('[data-action="upload"]').addEventListener('click', handleUpload);
}

/**
 * 渲染筛选栏
 */
function renderFilters() {
  const filters = document.querySelector('.filters-container');
  filters.innerHTML = `
    <div class="filter-group">
      <input type="text" id="filter-filename" placeholder="按文件名搜索" class="form-input">
    </div>
    <div class="filter-group">
      <select id="filter-type" class="form-select">
        <option value="">全部类型</option>
        <option value="pdf">PDF</option>
        <option value="docx">DOCX</option>
        <option value="doc">DOC</option>
        <option value="txt">TXT</option>
        <option value="md">Markdown</option>
      </select>
    </div>
    <div class="filter-group">
      <select id="filter-status" class="form-select">
        <option value="">全部状态</option>
        <option value="uploaded">已上传</option>
        <option value="parsing">解析中</option>
        <option value="processing">预处理中</option>
        <option value="vectorizing">向量化中</option>
        <option value="ready">已发布</option>
        <option value="error">失败</option>
      </select>
    </div>
    <div class="filter-group">
      <button class="btn btn-secondary" data-action="apply-filters">筛选</button>
      <button class="btn btn-secondary" data-action="clear-filters">重置</button>
    </div>
  `;
  filters.querySelector('[data-action="apply-filters"]').addEventListener('click', applyFilters);
  filters.querySelector('[data-action="clear-filters"]').addEventListener('click', clearFilters);
}

/**
 * 渲染表格
 */
function renderTable() {
  const { documents, pageInfo } = kbStore.getState();
  const table = document.querySelector('.data-table');
  table.innerHTML = `
    <thead>
      <tr>
        <th>文件名</th>
        <th>类型</th>
        <th>大小</th>
        <th>分段数</th>
        <th>状态</th>
        <th>上传时间</th>
        <th>操作</th>
      </tr>
    </thead>
    <tbody>
      ${documents.map((doc) => `
        <tr>
          <td>${doc.filename}</td>
          <td>${getFileTypeName(doc.file_type)}</td>
          <td>${formatFileSize(doc.file_size)}</td>
          <td>${doc.chunk_count}</td>
          <td><span class="status-badge status-${doc.status}">${getStatusName(doc.status)}</span></td>
          <td>${formatDate(doc.created_at)}</td>
          <td>
            <button class="btn btn-sm btn-secondary" data-action="view" data-id="${doc.id}">查看</button>
            <button class="btn btn-sm btn-info" data-action="chunks" data-id="${doc.id}">分段</button>
            <button class="btn btn-sm btn-warning" data-action="segment-rules" data-id="${doc.id}">分段规则</button>
            <button class="btn btn-sm btn-danger" data-action="delete" data-id="${doc.id}" data-name="${doc.filename}">删除</button>
          </td>
        </tr>
      `).join('')}
    </tbody>
  `;

  table.querySelectorAll('[data-action="view"]').forEach((btn) => {
    btn.addEventListener('click', () => viewDocument(btn.dataset.id));
  });
  table.querySelectorAll('[data-action="chunks"]').forEach((btn) => {
    btn.addEventListener('click', () => viewChunks(btn.dataset.id));
  });
  table.querySelectorAll('[data-action="segment-rules"]').forEach((btn) => {
    btn.addEventListener('click', () => openSegmentRulesModal(btn.dataset.id));
  });
  table.querySelectorAll('[data-action="delete"]').forEach((btn) => {
    btn.addEventListener('click', () => confirmDelete(btn.dataset.id, btn.dataset.name));
  });

  renderPagination(pageInfo);
}

/**
 * 渲染分页
 */
function renderPagination(pageInfo) {
  const pagination = document.querySelector('.pagination-container');
  const totalPages = Math.ceil(pageInfo.total / pageInfo.pageSize);
  pagination.innerHTML = `
    <button class="btn btn-sm btn-secondary" data-action="prev" ${pageInfo.page <= 1 ? 'disabled' : ''}>上一页</button>
    <span>第 ${pageInfo.page} / ${totalPages} 页</span>
    <button class="btn btn-sm btn-secondary" data-action="next" ${pageInfo.page >= totalPages ? 'disabled' : ''}>下一页</button>
  `;

  pagination.querySelector('[data-action="prev"]').addEventListener('click', () => {
    if (pageInfo.page > 1) goToPage(pageInfo.page - 1);
  });
  pagination.querySelector('[data-action="next"]').addEventListener('click', () => {
    if (pageInfo.page < totalPages) goToPage(pageInfo.page + 1);
  });
}

/**
 * 加载文档列表
 */
async function loadDocuments(page = 1) {
  currentPage = page;
  kbStore.setLoading(true);
  kbStore.setError(null);
  try {
    const response = await getDocumentList(kbId, {
      page,
      page_size: 20,
      filename: document.getElementById('filter-filename')?.value || '',
      file_type: document.getElementById('filter-type')?.value || '',
      status: document.getElementById('filter-status')?.value || '',
    });
    if (response.code === 0) {
      kbStore.setDocuments(response.data.items);
      kbStore.setPageInfo({
        page: response.data.page,
        pageSize: response.data.page_size,
        total: response.data.total,
      });
    } else {
      kbStore.setError(response.message);
    }
  } catch (error) {
    kbStore.setError('加载文档列表失败');
  } finally {
    kbStore.setLoading(false);
  }
}

/**
 * 处理上传
 */
async function handleUpload() {
  const fileInput = document.getElementById('file-input');
  if (!fileInput.files || fileInput.files.length === 0) {
    alert('请选择文件');
    return;
  }

  kbStore.setLoading(true);
  try {
    const response = await uploadDocuments(kbId, fileInput.files);
    if (response.code === 0) {
      fileInput.value = '';
      loadDocuments(currentPage);
    } else {
      alert(response.message);
    }
  } catch (error) {
    alert('上传失败');
  } finally {
    kbStore.setLoading(false);
  }
}

/**
 * 应用筛选
 */
function applyFilters() {
  loadDocuments(1);
}

/**
 * 清空筛选
 */
function clearFilters() {
  document.getElementById('filter-filename').value = '';
  document.getElementById('filter-type').value = '';
  document.getElementById('filter-status').value = '';
  loadDocuments(1);
}

/**
 * 跳转页面
 */
function goToPage(page) {
  loadDocuments(page);
}

/**
 * 处理加载状态
 */
function handleLoading(loading) {
  const loader = document.querySelector('.loader');
  if (loader) {
    loader.style.display = loading ? 'block' : 'none';
  }
}

/**
 * 处理错误
 */
function handleError(error) {
  const errorContainer = document.querySelector('.error-container');
  if (errorContainer) {
    errorContainer.textContent = error || '';
    errorContainer.style.display = error ? 'block' : 'none';
  }
}

/**
 * 查看文档详情
 */
async function viewDocument(docId) {
  try {
    const response = await getDocument(kbId, docId);
    if (response.code === 0) {
      showDocumentModal(response.data);
    }
  } catch (error) {
    alert('加载文档失败');
  }
}

/**
 * 查看文档分段
 */
async function viewChunks(docId) {
  try {
    const response = await getDocumentChunks(kbId, docId);
    if (response.code === 0) {
      showChunksModal(response.data);
    }
  } catch (error) {
    alert('加载分段失败');
  }
}

/**
 * 打开分段规则模态框
 */
function openSegmentRulesModal(docId) {
  const modal = document.createElement('div');
  modal.className = 'modal-overlay';
  modal.innerHTML = `
    <div class="modal-content">
      <h3>分段规则配置</h3>
      <form id="segment-form">
        <div class="form-group">
          <label>分段大小</label>
          <input type="number" name="chunk_size" class="form-input" value="500">
        </div>
        <div class="form-group">
          <label>分段重叠</label>
          <input type="number" name="chunk_overlap" class="form-input" value="50">
        </div>
        <div class="form-group">
          <label>分段模式</label>
          <select name="split_mode" class="form-select">
            <option value="fixed">固定长度</option>
            <option value="heading">按标题</option>
            <option value="paragraph">按段落</option>
            <option value="sliding">滑动窗口</option>
          </select>
        </div>
        <div class="form-group">
          <label>分隔符</label>
          <input type="text" name="separators" class="form-input" value="\\n\\n,\\n,。,.">
        </div>
        <div class="form-actions">
          <button type="button" class="btn btn-secondary" data-action="cancel">取消</button>
          <button type="button" class="btn btn-warning" data-action="save-rules" data-doc-id="${docId}">保存规则</button>
          <button type="button" class="btn btn-primary" data-action="re-segment" data-doc-id="${docId}">保存并重新分段</button>
        </div>
      </form>
    </div>
  `;
  document.body.appendChild(modal);

  modal.querySelector('[data-action="cancel"]').addEventListener('click', closeModal);
  modal.querySelector('[data-action="save-rules"]').addEventListener('click', (e) => {
    saveSegmentRules(e.target.dataset.docId);
  });
  modal.querySelector('[data-action="re-segment"]').addEventListener('click', (e) => {
    runReSegment(e.target.dataset.docId);
  });
}

/**
 * 保存分段规则
 */
async function saveSegmentRules(docId) {
  const form = document.getElementById('segment-form');
  const formData = new FormData(form);
  const data = {
    chunk_size: parseInt(formData.get('chunk_size')),
    chunk_overlap: parseInt(formData.get('chunk_overlap')),
    split_mode: formData.get('split_mode'),
    separators: formData.get('separators').split(','),
  };

  try {
    const response = await updateSegmentRules(kbId, docId, data);
    if (response.code === 0) {
      closeModal();
      loadDocuments(currentPage);
    } else {
      alert(response.message);
    }
  } catch (error) {
    alert('保存失败');
  }
}

/**
 * 执行重新分段
 */
async function runReSegment(docId) {
  if (!confirm('确定要重新分段文档吗？')) return;

  const form = document.getElementById('segment-form');
  const formData = new FormData(form);
  const data = {
    chunk_size: parseInt(formData.get('chunk_size')),
    chunk_overlap: parseInt(formData.get('chunk_overlap')),
    split_mode: formData.get('split_mode'),
    separators: formData.get('separators').split(','),
  };

  try {
    await updateSegmentRules(kbId, docId, data);
    const response = await reSegmentDocument(kbId, docId);
    if (response.code === 0) {
      closeModal();
      loadDocuments(currentPage);
    } else {
      alert(response.message);
    }
  } catch (error) {
    alert('操作失败');
  }
}

/**
 * 确认删除
 */
function confirmDelete(docId, filename) {
  if (confirm(`确定要删除文档 "${filename}" 吗？`)) {
    performDelete(docId);
  }
}

/**
 * 执行删除
 */
async function performDelete(docId) {
  try {
    const response = await deleteDocument(kbId, docId);
    if (response.code === 0) {
      loadDocuments(currentPage);
    } else {
      alert(response.message);
    }
  } catch (error) {
    alert('删除失败');
  }
}

/**
 * 显示文档详情模态框
 */
function showDocumentModal(doc) {
  const modal = document.createElement('div');
  modal.className = 'modal-overlay';
  modal.innerHTML = `
    <div class="modal-content">
      <h3>文档详情</h3>
      <div class="detail-grid">
        <div class="detail-item">
          <label>文件名</label>
          <span>${doc.filename}</span>
        </div>
        <div class="detail-item">
          <label>类型</label>
          <span>${getFileTypeName(doc.file_type)}</span>
        </div>
        <div class="detail-item">
          <label>大小</label>
          <span>${formatFileSize(doc.file_size)}</span>
        </div>
        <div class="detail-item">
          <label>分段数</label>
          <span>${doc.chunk_count}</span>
        </div>
        <div class="detail-item">
          <label>状态</label>
          <span>${getStatusName(doc.status)}</span>
        </div>
        <div class="detail-item">
          <label>上传时间</label>
          <span>${formatDate(doc.created_at)}</span>
        </div>
      </div>
      ${doc.error_message ? `<div class="error-box">错误: ${doc.error_message}</div>` : ''}
      <div class="form-actions">
        <button type="button" class="btn btn-primary" data-action="normalize" data-doc-id="${doc.id}">规范化</button>
        <button type="button" class="btn btn-secondary" data-action="cancel">关闭</button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);

  modal.querySelector('[data-action="cancel"]').addEventListener('click', closeModal);
  modal.querySelector('[data-action="normalize"]').addEventListener('click', (e) => {
    runNormalize(e.target.dataset.docId);
  });
}

/**
 * 执行规范化
 */
async function runNormalize(docId) {
  try {
    const response = await normalizeDocument(kbId, docId);
    if (response.code === 0) {
      closeModal();
      loadDocuments(currentPage);
    } else {
      alert(response.message);
    }
  } catch (error) {
    alert('规范化失败');
  }
}

/**
 * 显示分段列表模态框
 */
function showChunksModal(chunks) {
  const modal = document.createElement('div');
  modal.className = 'modal-overlay';
  modal.innerHTML = `
    <div class="modal-content large">
      <h3>文档分段列表</h3>
      <div class="chunks-list">
        ${chunks.map((chunk, index) => `
          <div class="chunk-item" data-chunk-id="${chunk.id}">
            <div class="chunk-header">
              <span class="chunk-index">分段 ${index + 1}</span>
              <span class="chunk-status ${chunk.is_active ? 'active' : 'disabled'}">${chunk.is_active ? '启用' : '禁用'}</span>
              <button class="btn btn-sm btn-secondary" data-action="edit-chunk" data-chunk-id="${chunk.id}">编辑</button>
            </div>
            <div class="chunk-content">${chunk.content.substring(0, 200)}${chunk.content.length > 200 ? '...' : ''}</div>
          </div>
        `).join('')}
      </div>
      <div class="form-actions">
        <button type="button" class="btn btn-secondary" data-action="cancel">关闭</button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);

  modal.querySelector('[data-action="cancel"]').addEventListener('click', closeModal);
  modal.querySelectorAll('[data-action="edit-chunk"]').forEach((btn) => {
    btn.addEventListener('click', () => editChunk(btn.dataset.chunkId));
  });
}

/**
 * 编辑分段
 */
function editChunk(chunkId) {
  alert('编辑分段功能开发中');
}

/**
 * 获取文件类型名称
 */
function getFileTypeName(type) {
  const types = {
    pdf: 'PDF',
    docx: 'DOCX',
    doc: 'DOC',
    txt: 'TXT',
    md: 'Markdown',
  };
  return types[type] || type;
}

/**
 * 获取状态名称
 */
function getStatusName(status) {
  const statuses = {
    uploaded: '已上传',
    parsing: '解析中',
    processing: '预处理中',
    pending_segment: '待分段',
    vectorizing: '向量化中',
    ready: '已发布',
    error: '失败',
    archived: '已归档',
  };
  return statuses[status] || status;
}

/**
 * 格式化文件大小
 */
function formatFileSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

/**
 * 格式化日期
 */
function formatDate(dateString) {
  if (!dateString) return '-';
  const date = new Date(dateString);
  return date.toLocaleString('zh-CN');
}

/**
 * 关闭模态框
 */
function closeModal() {
  const modal = document.querySelector('.modal-overlay');
  if (modal) modal.remove();
}