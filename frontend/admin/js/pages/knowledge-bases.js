/**
 * 知识库列表页面
 * @module KnowledgeBasesPage
 */

import { kbStore } from '../store/kb-store.js';
import {
  getKnowledgeBaseList,
  getKnowledgeBase,
  createKnowledgeBase,
  updateKnowledgeBase,
  deleteKnowledgeBase,
} from '../api/knowledge-base-api.js';

let currentPage = 1;

/**
 * 初始化页面
 */
export async function initKnowledgeBasesPage() {
  renderHeader();
  renderFilters();
  await loadKnowledgeBases(currentPage);

  kbStore.on('knowledgeBasesChange', renderTable);
  kbStore.on('loadingChange', handleLoading);
  kbStore.on('errorChange', handleError);

  window.kbPage = {
    applyFilters: applyFilters,
    clearFilters: clearFilters,
    goToPage: goToPage,
    openCreateModal: openCreateModal,
    openEditModal: openEditModal,
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
    <h1 class="page-title">知识库管理</h1>
    <button class="btn btn-primary" data-action="open-create-modal">创建知识库</button>
  `;
  header.querySelector('[data-action="open-create-modal"]').addEventListener('click', openCreateModal);
}

/**
 * 渲染筛选栏
 */
function renderFilters() {
  const filters = document.querySelector('.filters-container');
  filters.innerHTML = `
    <div class="filter-group">
      <input type="text" id="filter-name" placeholder="按名称搜索" class="form-input">
    </div>
    <div class="filter-group">
      <select id="filter-type" class="form-select">
        <option value="">全部类型</option>
        <option value="technical">技术文档</option>
        <option value="product">产品手册</option>
        <option value="faq">FAQ</option>
        <option value="general">通用知识</option>
      </select>
    </div>
    <div class="filter-group">
      <input type="text" id="filter-tag" placeholder="按标签搜索" class="form-input">
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
  const { knowledgeBases, pageInfo } = kbStore.getState();
  const table = document.querySelector('.data-table');
  table.innerHTML = `
    <thead>
      <tr>
        <th>名称</th>
        <th>类型</th>
        <th>标签</th>
        <th>可见性</th>
        <th>状态</th>
        <th>文档数</th>
        <th>创建时间</th>
        <th>操作</th>
      </tr>
    </thead>
    <tbody>
      ${knowledgeBases.map((kb) => `
        <tr>
          <td><a href="/admin/knowledge-bases/${kb.id}">${kb.name}</a></td>
          <td>${getTypeName(kb.type)}</td>
          <td>${kb.tags.join(', ') || '-'}</td>
          <td>${kb.visibility === 'public' ? '公开' : '受限'}</td>
          <td><span class="status-badge status-${kb.status}">${getStatusName(kb.status)}</span></td>
          <td>${kb.document_count}</td>
          <td>${formatDate(kb.created_at)}</td>
          <td>
            <button class="btn btn-sm btn-secondary" data-action="edit" data-id="${kb.id}">编辑</button>
            <button class="btn btn-sm btn-danger" data-action="delete" data-id="${kb.id}" data-name="${kb.name}">删除</button>
          </td>
        </tr>
      `).join('')}
    </tbody>
  `;

  table.querySelectorAll('[data-action="edit"]').forEach((btn) => {
    btn.addEventListener('click', () => openEditModal(btn.dataset.id));
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
 * 加载知识库列表
 */
async function loadKnowledgeBases(page = 1) {
  currentPage = page;
  kbStore.setLoading(true);
  kbStore.setError(null);
  try {
    const response = await getKnowledgeBaseList({
      page,
      page_size: 20,
      name: document.getElementById('filter-name')?.value || '',
      type: document.getElementById('filter-type')?.value || '',
      tag: document.getElementById('filter-tag')?.value || '',
    });
    if (response.code === 0) {
      kbStore.setKnowledgeBases(response.data.items);
      kbStore.setPageInfo({
        page: response.data.page,
        pageSize: response.data.page_size,
        total: response.data.total,
      });
    } else {
      kbStore.setError(response.message);
    }
  } catch (error) {
    kbStore.setError('加载知识库列表失败');
  } finally {
    kbStore.setLoading(false);
  }
}

/**
 * 应用筛选
 */
function applyFilters() {
  loadKnowledgeBases(1);
}

/**
 * 清空筛选
 */
function clearFilters() {
  document.getElementById('filter-name').value = '';
  document.getElementById('filter-type').value = '';
  document.getElementById('filter-tag').value = '';
  loadKnowledgeBases(1);
}

/**
 * 跳转页面
 */
function goToPage(page) {
  loadKnowledgeBases(page);
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
 * 获取类型名称
 */
function getTypeName(type) {
  const types = {
    technical: '技术文档',
    product: '产品手册',
    faq: 'FAQ',
    general: '通用知识',
  };
  return types[type] || type;
}

/**
 * 获取状态名称
 */
function getStatusName(status) {
  const statuses = {
    active: '活跃',
    vectorizing: '向量化中',
    archived: '已归档',
    deleted: '已删除',
  };
  return statuses[status] || status;
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
 * 打开创建模态框
 */
function openCreateModal() {
  showModal('create');
}

/**
 * 打开编辑模态框
 */
function openEditModal(id) {
  showModal('edit', id);
}

/**
 * 显示模态框
 */
async function showModal(type, id = null) {
  const modal = document.createElement('div');
  modal.className = 'modal-overlay';
  modal.innerHTML = `
    <div class="modal-content">
      <h3>${type === 'create' ? '创建知识库' : '编辑知识库'}</h3>
      <form id="kb-form">
        <div class="form-group">
          <label>名称</label>
          <input type="text" name="name" required class="form-input">
        </div>
        <div class="form-group">
          <label>类型</label>
          <select name="type" required class="form-select">
            <option value="technical">技术文档</option>
            <option value="product">产品手册</option>
            <option value="faq">FAQ</option>
            <option value="general">通用知识</option>
          </select>
        </div>
        <div class="form-group">
          <label>标签</label>
          <input type="text" name="tags" placeholder="逗号分隔" class="form-input">
        </div>
        <div class="form-group">
          <label>描述</label>
          <textarea name="description" class="form-textarea"></textarea>
        </div>
        <div class="form-group">
          <label>可见性</label>
          <select name="visibility" required class="form-select">
            <option value="public">公开</option>
            <option value="restricted">受限</option>
          </select>
        </div>
        <div class="form-group">
          <label>Embedding 模型</label>
          <input type="text" name="embedding_model" required class="form-input" value="text-embedding-3-small">
        </div>
        <div class="form-group">
          <label>分段大小</label>
          <input type="number" name="chunk_size" class="form-input" value="500">
        </div>
        <div class="form-group">
          <label>分段重叠</label>
          <input type="number" name="chunk_overlap" class="form-input" value="50">
        </div>
        <div class="form-actions">
          <button type="button" class="btn btn-secondary" data-action="cancel">取消</button>
          <button type="submit" class="btn btn-primary">保存</button>
        </div>
      </form>
    </div>
  `;
  document.body.appendChild(modal);

  modal.querySelector('[data-action="cancel"]').addEventListener('click', closeModal);

  if (type === 'edit' && id) {
    await loadKBData(id, modal);
  }

  modal.querySelector('#kb-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    await submitForm(type, id, modal);
  });
}

/**
 * 加载知识库数据
 */
async function loadKBData(id, modal) {
  try {
    const response = await getKnowledgeBase(id);
    if (response.code === 0) {
      const data = response.data;
      modal.querySelector('input[name="name"]').value = data.name;
      modal.querySelector('select[name="type"]').value = data.type;
      modal.querySelector('input[name="tags"]').value = data.tags.join(',');
      modal.querySelector('textarea[name="description"]').value = data.description || '';
      modal.querySelector('select[name="visibility"]').value = data.visibility;
      modal.querySelector('input[name="embedding_model"]').value = data.embedding_model;
      modal.querySelector('input[name="chunk_size"]').value = data.chunk_size;
      modal.querySelector('input[name="chunk_overlap"]').value = data.chunk_overlap;
    }
  } catch (error) {
    console.error('加载知识库数据失败', error);
  }
}

/**
 * 提交表单
 */
async function submitForm(type, id, modal) {
  const form = modal.querySelector('#kb-form');
  const formData = new FormData(form);
  const data = {
    name: formData.get('name'),
    type: formData.get('type'),
    tags: formData.get('tags').split(',').map((t) => t.trim()).filter((t) => t),
    description: formData.get('description') || null,
    visibility: formData.get('visibility'),
    embedding_model: formData.get('embedding_model'),
    chunk_size: parseInt(formData.get('chunk_size')),
    chunk_overlap: parseInt(formData.get('chunk_overlap')),
  };

  try {
    let response;
    if (type === 'create') {
      response = await createKnowledgeBase(data);
    } else {
      response = await updateKnowledgeBase(id, data);
    }
    if (response.code === 0) {
      closeModal();
      loadKnowledgeBases(currentPage);
    } else {
      alert(response.message);
    }
  } catch (error) {
    alert('操作失败');
  }
}

/**
 * 关闭模态框
 */
function closeModal() {
  const modal = document.querySelector('.modal-overlay');
  if (modal) modal.remove();
}

/**
 * 确认删除
 */
function confirmDelete(id, name) {
  if (confirm(`确定要删除知识库 "${name}" 吗？`)) {
    performDelete(id);
  }
}

/**
 * 执行删除
 */
async function performDelete(id) {
  try {
    const response = await deleteKnowledgeBase(id);
    if (response.code === 0) {
      loadKnowledgeBases(currentPage);
    } else {
      alert(response.message);
    }
  } catch (error) {
    alert('删除失败');
  }
}