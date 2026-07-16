/**
 * 知识库状态管理模块
 * 基于发布-订阅模式，管理知识库列表、当前详情、向量化进度等前端状态
 * @module KBStore
 */

class KBStore {
  constructor() {
    this.state = {
      knowledgeBases: [],
      currentKB: null,
      vectorizeStatus: null,
      documents: [],
      currentDocument: null,
      chunks: [],
      pageInfo: {
        page: 1,
        pageSize: 20,
        total: 0,
      },
      loading: false,
      error: null,
    };
    this.listeners = {};
  }

  /**
   * 订阅状态变化
   * @param {string} event - 事件名称
   * @param {function} callback - 回调函数
   */
  on(event, callback) {
    if (!this.listeners[event]) {
      this.listeners[event] = [];
    }
    this.listeners[event].push(callback);
  }

  /**
   * 取消订阅
   * @param {string} event - 事件名称
   * @param {function} callback - 回调函数
   */
  off(event, callback) {
    if (!this.listeners[event]) return;
    this.listeners[event] = this.listeners[event].filter((cb) => cb !== callback);
  }

  /**
   * 触发事件
   * @param {string} event - 事件名称
   * @param {*} data - 事件数据
   */
  emit(event, data) {
    if (!this.listeners[event]) return;
    this.listeners[event].forEach((callback) => callback(data));
  }

  /**
   * 更新状态
   * @param {object} newState - 新状态
   */
  setState(newState) {
    this.state = { ...this.state, ...newState };
    this.emit('change', this.state);
  }

  /**
   * 设置知识库列表
   * @param {Array} knowledgeBases - 知识库列表
   */
  setKnowledgeBases(knowledgeBases) {
    this.setState({ knowledgeBases });
    this.emit('knowledgeBasesChange', knowledgeBases);
  }

  /**
   * 设置当前知识库详情
   * @param {object} currentKB - 知识库详情
   */
  setCurrentKB(currentKB) {
    this.setState({ currentKB });
    this.emit('currentKBChange', currentKB);
  }

  /**
   * 设置向量化状态
   * @param {object} vectorizeStatus - 向量化状态
   */
  setVectorizeStatus(vectorizeStatus) {
    this.setState({ vectorizeStatus });
    this.emit('vectorizeStatusChange', vectorizeStatus);
  }

  /**
   * 设置文档列表
   * @param {Array} documents - 文档列表
   */
  setDocuments(documents) {
    this.setState({ documents });
    this.emit('documentsChange', documents);
  }

  /**
   * 设置当前文档详情
   * @param {object} currentDocument - 文档详情
   */
  setCurrentDocument(currentDocument) {
    this.setState({ currentDocument });
    this.emit('currentDocumentChange', currentDocument);
  }

  /**
   * 设置分段列表
   * @param {Array} chunks - 分段列表
   */
  setChunks(chunks) {
    this.setState({ chunks });
    this.emit('chunksChange', chunks);
  }

  /**
   * 设置分页信息
   * @param {object} pageInfo - 分页信息
   */
  setPageInfo(pageInfo) {
    this.setState({ pageInfo });
    this.emit('pageInfoChange', pageInfo);
  }

  /**
   * 设置加载状态
   * @param {boolean} loading - 是否加载中
   */
  setLoading(loading) {
    this.setState({ loading });
    this.emit('loadingChange', loading);
  }

  /**
   * 设置错误信息
   * @param {string|null} error - 错误信息
   */
  setError(error) {
    this.setState({ error });
    this.emit('errorChange', error);
  }

  /**
   * 获取当前状态
   * @returns {object} 当前状态
   */
  getState() {
    return { ...this.state };
  }
}

export const kbStore = new KBStore();