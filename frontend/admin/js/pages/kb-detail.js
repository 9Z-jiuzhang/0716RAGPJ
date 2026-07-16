/**
 * 知识库详情页面
 * @module KBDetailPage
 */

import { kbStore } from '../store/kb-store.js';
import {
  getKnowledgeBase,
  updateKnowledgeBase,
  reVectorizeKnowledgeBase,
  getVectorizeStatus,
  updateKnowledgeBasePermissions,
} from '../api/knowledge-base-api.js';

let kbId = null;
let statusInterval = null;

/**
 * 初始化页面
 * @param {string} id - 知识库ID
 */
export async function initKBDetailPage(id) {
  kbId = id;
  await loadKBDetail(id);
  renderDetail();
  renderTabs();

  kbStore.on('currentKBChange', renderDetail);
  kbStore.on('vectorizeStatusChange', renderVectorizeStatus);
  kbStore.on('loadingChange', handleLoading);
  kbStore.on('errorChange', handleError);

  window.kbDetailPage = {
    startReVectorize: startReVectorize,
    openEditModal: openEditModal,
    openPermissionsModal: openPermissionsModal,
    closeModal: closeModal,
  };
}

/**
 * 加载知识库详情
 */
async function loadKBDetail(id) {
  kbStore.setLoading(true);
  kbStore.setError(null);
  try {
    const response = await getKnowledgeBase(id);
    if (response.code === 0) {
      kbStore.setCurrentKB(response.data);
    } else {
      kbStore.setError(response.message);
    }
  } catch (error) {
    kbStore.setError('加载知识库详情失败');
  } finally {
    kbStore.setLoading(false);
  }
}

/**
 * 渲染详情
 */
function renderDetail() {
  const { currentKB } = kbStore.getState();
  if (!currentKB) return;

  const detail = document.querySelector('.kb-detail');
  detail.innerHTML = `
    <div class="detail-header">
      <div class="detail-title">
        <h1>${currentKB.name}</h1>
        <span class="status-badge status-${currentKB.status}">${getStatusName(currentKB.status)}</span>
      </div>
      <div class="detail-actions">
        <button class="btn btn-primary" data-action="edit">编辑</button>
        <button class="btn btn-warning" data-action="re-vectorize">重新向量化</button>
        <button class="btn btn-secondary" data-action="permissions">权限配置</button>
        <a href="/admin/knowledge-bases/${currentKB.id}/documents" class="btn btn-info">文档管理</a>
      </div>
    </div>
    <div class="detail-content">
      <div class="detail-section">
        <h3>基本信息</h3>
        <div class="detail-grid">
          <div class="detail-item">
            <label>类型</label>
            <span>${getTypeName(currentKB.type)}</span>
          </div>
          <div class="detail-item">
            <label>可见性</label>
            <span>${currentKB.visibility === 'public' ? '公开' : '受限'}</span>
          </div>
          <div class="detail-item">
            <label>Embedding 模型</label>
            <span>${currentKB.embedding_model}</span>
          </div>
          <div class="detail-item">
            <label>分段大小</label>
            <span>${currentKB.chunk_size} 字符</span>
          </div>
          <div class="detail-item">
            <label>分段重叠</label>
            <span>${currentKB.chunk_overlap} 字符</span>
          </div>
          <div class="detail-item">
            <label>当前索引版本</label>
            <span>${currentKB.current_index_version || '-'}</span>
          </div>
        </div>
      </div>
      <div class="detail-section">
        <h3>统计信息</h3>
        <div class="stat-cards">
          <div class="stat-card">
            <div class="stat-value">${currentKB.document_count}</div>
            <div class="stat-label">文档数量</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">${currentKB.chunk_count}</div>
            <div class="stat-label">分段数量</div>
          </div>
        </div>
      </div>
      <div class="detail-section">
        <h3>描述</h3>
        <p>${currentKB.description || '-'}</p>
      </div>
      <div class="detail-section">
        <h3>标签</h3>
        <div class="tag-list">
          ${currentKB.tags.map((tag) => `<span class="tag">${tag}</span>`).join('') || '-'}
        </div>
      </div>
      <div class="detail-section" id="vectorize-status-section" style="display: none;">
        <h3>向量化进度</h3>
        <div id="vectorize-progress">
          <div class="progress-bar">
            <div class="progress-fill" style="width: 0%"></div>
          </div>
          <div class="progress-info">
            <span id="progress-text">0%</span>
            <span id="progress-count">0/0</span>
          </div>
        </div>
      </div>
    </div>
  `;

  detail.querySelector('[data-action="edit"]').addEventListener('click', openEditModal);
  detail.querySelector('[data-action="re-vectorize"]').addEventListener('click', startReVectorize);
  detail.querySelector('[data-action="permissions"]').addEventListener('click', openPermissionsModal);
}

/**
 * 渲染标签页
 */
function renderTabs() {
  const tabs = document.querySelector('.tabs-container');
  tabs.innerHTML = `
    <div class="tabs">
      <button class="tab active" data-tab="detail">详情</button>
      <button class="tab" data-tab="documents">文档</button>
      <button class="tab" data-tab="snapshots">快照</button>
    </div>
  `;

  tabs.querySelectorAll('.tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      tabs.querySelectorAll('.tab').forEach((t) => t.classList.remove('active'));
      tab.classList.add('active');
      switchTab(tab.dataset.tab);
    });
  });
}

/**
 * 切换标签页
 */
function switchTab(tab) {
  if (tab === 'documents') {
    window.location.href = `/admin/knowledge-bases/${kbId}/documents`;
  } else if (tab === 'snapshots') {
    window.location.href = `/admin/knowledge-bases/${kbId}/snapshots`;
  }
}

/**
 * 渲染向量化状态
 */
function renderVectorizeStatus(status) {
  if (!status) return;

  const section = document.getElementById('vectorize-status-section');
  if (section) {
    section.style.display = 'block';
  }

  const fill = document.querySelector('.progress-fill');
  const text = document.getElementById('progress-text');
  const count = document.getElementById('progress-count');

  if (fill) fill.style.width = `${status.progress}%`;
  if (text) text.textContent = `${status.progress}%`;
  if (count) count.textContent = `${status.processed_count}/${status.total_count}`;

  if (status.status === 'completed' || status.status === 'failed') {
    stopStatusPolling();
    if (status.status === 'failed') {
      alert('向量化失败: ' + (status.error_message || '未知错误'));
    }
  }
}

/**
 * 开始重新向量化
 */
async function startReVectorize() {
  if (!confirm('确定要重新向量化知识库吗？这可能需要一段时间。')) return;

  try {
    const response = await reVectorizeKnowledgeBase(kbId);
    if (response.code === 0) {
      kbStore.setVectorizeStatus(response.data);
      startStatusPolling();
    } else {
      alert(response.message);
    }
  } catch (error) {
    alert('触发向量化失败');
  }
}

/**
 * 开始状态轮询
 */
function startStatusPolling() {
  stopStatusPolling();
  statusInterval = setInterval(async () => {
    try {
      const response = await getVectorizeStatus(kbId);
      if (response.code === 0) {
        kbStore.setVectorizeStatus(response.data);
      }
    } catch (error) {
      console.error('轮询向量化状态失败', error);
    }
  }, 3000);
}

/**
 * 停止状态轮询
 */
function stopStatusPolling() {
  if (statusInterval) {
    clearInterval(statusInterval);
    statusInterval = null;
  }
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
 * 打开编辑模态框
 */
function openEditModal() {
  const { currentKB } = kbStore.getState();
  if (!currentKB) return;

  const modal = document.createElement('div');
  modal.className = 'modal-overlay';
  modal.innerHTML = `
    <div class="modal-content">
      <h3>编辑知识库</h3>
      <form id="edit-form">
        <div class="form-group">
          <label>名称</label>
          <input type="text" name="name" required class="form-input" value="${currentKB.name}">
        </div>
        <div class="form-group">
          <label>类型</label>
          <select name="type" required class="form-select">
            <option value="technical" ${currentKB.type === 'technical' ? 'selected' : ''}>技术文档</option>
            <option value="product" ${currentKB.type === 'product' ? 'selected' : ''}>产品手册</option>
            <option value="faq" ${currentKB.type === 'faq' ? 'selected' : ''}>FAQ</option>
            <option value="general" ${currentKB.type === 'general' ? 'selected' : ''}>通用知识</option>
          </select>
        </div>
        <div class="form-group">
          <label>标签</label>
          <input type="text" name="tags" class="form-input" value="${currentKB.tags.join(',')}">
        </div>
        <div class="form-group">
          <label>描述</label>
          <textarea name="description" class="form-textarea">${currentKB.description || ''}</textarea>
        </div>
        <div class="form-group">
          <label>可见性</label>
          <select name="visibility" required class="form-select">
            <option value="public" ${currentKB.visibility === 'public' ? 'selected' : ''}>公开</option>
            <option value="restricted" ${currentKB.visibility === 'restricted' ? 'selected' : ''}>受限</option>
          </select>
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

  modal.querySelector('#edit-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const formData = new FormData(e.target);
    const data = {
      name: formData.get('name'),
      type: formData.get('type'),
      tags: formData.get('tags').split(',').map((t) => t.trim()).filter((t) => t),
      description: formData.get('description') || null,
      visibility: formData.get('visibility'),
    };

    try {
      const response = await updateKnowledgeBase(kbId, data);
      if (response.code === 0) {
        closeModal();
        loadKBDetail(kbId);
      } else {
        alert(response.message);
      }
    } catch (error) {
      alert('更新失败');
    }
  });
}

/**
 * 打开权限配置模态框
 */
function openPermissionsModal() {
  const modal = document.createElement('div');
  modal.className = 'modal-overlay';
  modal.innerHTML = `
    <div class="modal-content">
      <h3>权限配置</h3>
      <form id="permissions-form">
        <div class="form-group">
          <label>权限列表</label>
          <div class="permission-list">
            <label><input type="checkbox" name="permissions" value="kb:read"> 读取</label>
            <label><input type="checkbox" name="permissions" value="kb:write"> 写入</label>
            <label><input type="checkbox" name="permissions" value="kb:upload"> 上传</label>
            <label><input type="checkbox" name="permissions" value="kb:vectorize"> 向量化</label>
          </div>
        </div>
        <div class="form-group">
          <label>授权方式</label>
          <select name="grant_type" class="form-select">
            <option value="user">按用户授权</option>
            <option value="role">按角色授权</option>
          </select>
        </div>
        <div class="form-group">
          <label>目标ID</label>
          <input type="text" name="target_id" placeholder="用户ID或角色ID" class="form-input">
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

  modal.querySelector('#permissions-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const formData = new FormData(e.target);
    const permissions = formData.getAll('permissions');
    const grantType = formData.get('grant_type');
    const targetId = formData.get('target_id');

    const data = {
      permissions: permissions.map((p) => ({
        [grantType === 'user' ? 'user_id' : 'role_id']: targetId,
        permission: p,
      })),
    };

    try {
      const response = await updateKnowledgeBasePermissions(kbId, data);
      if (response.code === 0) {
        closeModal();
      } else {
        alert(response.message);
      }
    } catch (error) {
      alert('保存权限失败');
    }
  });
}

/**
 * 关闭模态框
 */
function closeModal() {
  const modal = document.querySelector('.modal-overlay');
  if (modal) modal.remove();
}