/**
 * 知识库相关 UI 组件
 * @module KBComponents
 */

/**
 * 渲染状态徽章
 * @param {string} status - 状态值
 * @returns {string} HTML 字符串
 */
export function renderStatusBadge(status) {
  const statusConfig = {
    active: { label: '活跃', class: 'status-active' },
    vectorizing: { label: '向量化中', class: 'status-vectorizing' },
    archived: { label: '已归档', class: 'status-archived' },
    deleted: { label: '已删除', class: 'status-deleted' },
    uploaded: { label: '已上传', class: 'status-uploaded' },
    parsing: { label: '解析中', class: 'status-parsing' },
    processing: { label: '预处理中', class: 'status-processing' },
    pending_segment: { label: '待分段', class: 'status-pending' },
    ready: { label: '已发布', class: 'status-ready' },
    error: { label: '失败', class: 'status-error' },
  };

  const config = statusConfig[status] || { label: status, class: 'status-default' };
  return `<span class="status-badge ${config.class}">${config.label}</span>`;
}

/**
 * 渲染标签列表
 * @param {Array} tags - 标签数组
 * @returns {string} HTML 字符串
 */
export function renderTagList(tags) {
  if (!tags || tags.length === 0) return '-';
  return tags.map((tag) => `<span class="tag">${tag}</span>`).join('');
}

/**
 * 渲染进度条
 * @param {number} progress - 进度百分比
 * @param {string} label - 标签文本
 * @returns {string} HTML 字符串
 */
export function renderProgressBar(progress, label = '') {
  return `
    <div class="progress-container">
      <div class="progress-bar">
        <div class="progress-fill" style="width: ${progress}%"></div>
      </div>
      <div class="progress-label">${label} ${progress}%</div>
    </div>
  `;
}

/**
 * 渲染分页组件
 * @param {object} pageInfo - 分页信息
 * @param {number} pageInfo.page - 当前页
 * @param {number} pageInfo.pageSize - 每页大小
 * @param {number} pageInfo.total - 总数
 * @returns {string} HTML 字符串
 */
export function renderPagination(pageInfo) {
  const totalPages = Math.ceil(pageInfo.total / pageInfo.pageSize);
  const pages = [];

  for (let i = 1; i <= totalPages; i++) {
    if (i === 1 || i === totalPages || (i >= pageInfo.page - 1 && i <= pageInfo.page + 1)) {
      pages.push(i);
    } else if (pages[pages.length - 1] !== '...') {
      pages.push('...');
    }
  }

  return `
    <div class="pagination">
      <button 
        class="pagination-btn" 
        ${pageInfo.page <= 1 ? 'disabled' : ''}
        data-action="prev"
      >
        上一页
      </button>
      ${pages.map((page) => {
        if (page === '...') {
          return '<span class="pagination-ellipsis">...</span>';
        }
        return `
          <button 
            class="pagination-btn ${page === pageInfo.page ? 'active' : ''}"
            data-action="page"
            data-page="${page}"
          >
            ${page}
          </button>
        `;
      }).join('')}
      <button 
        class="pagination-btn" 
        ${pageInfo.page >= totalPages ? 'disabled' : ''}
        data-action="next"
      >
        下一页
      </button>
    </div>
  `;
}

/**
 * 渲染空状态
 * @param {string} message - 提示消息
 * @returns {string} HTML 字符串
 */
export function renderEmptyState(message = '暂无数据') {
  return `
    <div class="empty-state">
      <div class="empty-icon empty-icon-box"></div>
      <div class="empty-message">${message}</div>
    </div>
  `;
}

/**
 * 渲染加载状态
 * @returns {string} HTML 字符串
 */
export function renderLoading() {
  return `
    <div class="loading-state">
      <div class="loading-spinner"></div>
      <div class="loading-message">加载中...</div>
    </div>
  `;
}

/**
 * 渲染错误状态
 * @param {string} message - 错误消息
 * @returns {string} HTML 字符串
 */
export function renderError(message = '加载失败') {
  return `
    <div class="error-state">
      <div class="error-icon error-icon-x"></div>
      <div class="error-message">${message}</div>
    </div>
  `;
}

/**
 * 创建模态框
 * @param {object} options - 模态框选项
 * @param {string} options.title - 标题
 * @param {string} options.content - 内容 HTML
 * @param {Array} options.actions - 按钮配置
 * @param {function} options.onClose - 关闭回调
 * @returns {HTMLElement} 模态框元素
 */
export function createModal(options) {
  const modal = document.createElement('div');
  modal.className = 'modal-overlay';

  const actionsHtml = options.actions?.map((action, index) => `
    <button 
      class="btn btn-${action.style || 'secondary'}"
      data-action="modal-action"
      data-action-index="${index}"
    >
      ${action.label}
    </button>
  `).join('') || '';

  modal.innerHTML = `
    <div class="modal-content">
      <div class="modal-header">
        <h3>${options.title}</h3>
        <button class="modal-close" data-action="modal-close">×</button>
      </div>
      <div class="modal-body">
        ${options.content}
      </div>
      ${actionsHtml ? `
        <div class="modal-footer">
          ${actionsHtml}
        </div>
      ` : ''}
    </div>
  `;

  document.body.appendChild(modal);

  modal.querySelector('[data-action="modal-close"]').addEventListener('click', () => {
    options.onClose?.();
    modal.remove();
  });

  options.actions?.forEach((action, index) => {
    const btn = modal.querySelector(`[data-action-index="${index}"]`);
    if (btn) {
      btn.addEventListener('click', action.onClick);
    }
  });

  return modal;
}

/**
 * 创建确认对话框
 * @param {string} message - 确认消息
 * @param {function} onConfirm - 确认回调
 * @param {function} onCancel - 取消回调
 */
export function createConfirmDialog(message, onConfirm, onCancel) {
  const modal = createModal({
    title: '确认操作',
    content: `<p>${message}</p>`,
    actions: [
      { label: '取消', style: 'secondary', onClick: () => { modal.remove(); onCancel?.(); } },
      { label: '确认', style: 'danger', onClick: () => { modal.remove(); onConfirm(); } },
    ],
    onClose: onCancel,
  });
  return modal;
}

/**
 * 创建表单输入组件
 * @param {object} options - 输入选项
 * @param {string} options.type - 输入类型
 * @param {string} options.name - 字段名
 * @param {string} options.label - 标签
 * @param {string} options.value - 默认值
 * @param {boolean} options.required - 是否必填
 * @param {string} options.placeholder - 占位符
 * @param {Array} options.options - 选项列表（select 类型）
 * @returns {string} HTML 字符串
 */
export function createFormInput(options) {
  const required = options.required ? 'required' : '';
  const label = options.label ? `<label>${options.label}</label>` : '';

  switch (options.type) {
    case 'select':
      const optionsHtml = options.options?.map((opt) => `
        <option value="${opt.value}" ${opt.selected ? 'selected' : ''}>${opt.label}</option>
      `).join('') || '';
      return `
        <div class="form-group">
          ${label}
          <select name="${options.name}" ${required} class="form-select">
            ${optionsHtml}
          </select>
        </div>
      `;

    case 'textarea':
      return `
        <div class="form-group">
          ${label}
          <textarea 
            name="${options.name}" 
            ${required} 
            class="form-textarea"
            placeholder="${options.placeholder || ''}"
          >${options.value || ''}</textarea>
        </div>
      `;

    case 'checkbox':
      return `
        <div class="form-group">
          <label class="checkbox-label">
            <input type="checkbox" name="${options.name}" ${options.checked ? 'checked' : ''}>
            ${options.label}
          </label>
        </div>
      `;

    default:
      return `
        <div class="form-group">
          ${label}
          <input 
            type="${options.type}" 
            name="${options.name}" 
            value="${options.value || ''}" 
            ${required} 
            class="form-input"
            placeholder="${options.placeholder || ''}"
          >
        </div>
      `;
  }
}

/**
 * 渲染统计卡片
 * @param {object} stat - 统计数据
 * @param {string} stat.label - 标签
 * @param {number} stat.value - 值
 * @param {string} stat.unit - 单位
 * @param {string} stat.color - 颜色主题
 * @returns {string} HTML 字符串
 */
export function renderStatCard(stat) {
  return `
    <div class="stat-card stat-${stat.color || 'default'}">
      <div class="stat-value">${stat.value}${stat.unit || ''}</div>
      <div class="stat-label">${stat.label}</div>
    </div>
  `;
}

/**
 * 渲染知识库卡片
 * @param {object} kb - 知识库数据
 * @returns {string} HTML 字符串
 */
export function renderKBCard(kb) {
  return `
    <div class="kb-card" data-action="navigate" data-path="/admin/knowledge-bases/${kb.id}">
      <div class="kb-card-header">
        <h3>${kb.name}</h3>
        ${renderStatusBadge(kb.status)}
      </div>
      <div class="kb-card-body">
        <div class="kb-card-info">
          <span class="kb-type">${getTypeName(kb.type)}</span>
          <span class="kb-visibility">${kb.visibility === 'public' ? '公开' : '受限'}</span>
        </div>
        <p class="kb-description">${kb.description || '暂无描述'}</p>
        <div class="kb-card-tags">
          ${renderTagList(kb.tags)}
        </div>
      </div>
      <div class="kb-card-footer">
        <span>${kb.document_count} 文档</span>
        <span>${kb.chunk_count} 分段</span>
      </div>
    </div>
  `;
}

/**
 * 获取类型名称
 * @param {string} type - 类型值
 * @returns {string} 类型名称
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