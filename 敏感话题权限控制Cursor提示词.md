# FAQ 敏感话题权限控制

## 项目路径
`E:\ZY\26.5-上海交大培训\Ai大数据课程\每日学习文件\团队作业\workspace_rag\RAG-JZ\0716RAGPJ`

## 背景
需要在现有FAQ系统中增加敏感话题权限控制，实现：
- 文档/FAQ按敏感等级分类
- 用户按角色访问不同密级内容
- 无权限内容不召回、不泄露

## 敏感等级设计

### 3级密级

| 等级 | 名称 | 含义 | 典型场景 |
|------|------|------|---------|
| `normal` | 普通 | 普通内部信息 | 普通制度、公告 |
| `confidential` | 机密 | 需要特定角色 | 高管薪资、员工PII |
| `restricted` | 极高密 | 仅高管/指定角色 | 核心商业机密 |

### 角色权限配置

| 角色 | 最高可访问等级 |
|------|---------------|
| `guest` / `visitor` | normal |
| `employee` | normal |
| `hr` | confidential |
| `manager` | confidential |
| `admin` | confidential |
| `executive` | restricted |

---

## 数据模型设计

### 1. 新建角色权限表

```sql
-- 角色敏感等级权限配置
CREATE TABLE role_sensitivity_permissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    role VARCHAR(50) NOT NULL,
    max_sensitivity_level VARCHAR(20) NOT NULL DEFAULT 'normal',
    -- normal / confidential / restricted
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(tenant_id, role)
);

CREATE INDEX idx_role_sensitivity_tenant ON role_sensitivity_permissions(tenant_id);

-- 预置数据
INSERT INTO role_sensitivity_permissions (tenant_id, role, max_sensitivity_level) VALUES
    ('default_tenant', 'guest', 'normal'),
    ('default_tenant', 'employee', 'normal'),
    ('default_tenant', 'hr', 'confidential'),
    ('default_tenant', 'manager', 'confidential'),
    ('default_tenant', 'admin', 'confidential'),
    ('default_tenant', 'executive', 'restricted');
```

### 2. 用户权限覆盖表（可选，用于特例）

```sql
-- 用户级权限覆盖（用于少数特例）
CREATE TABLE user_sensitivity_overrides (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    max_sensitivity_level VARCHAR(20) NOT NULL DEFAULT 'normal',
    reason VARCHAR(200),  -- 申请原因
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP,  -- 可选，过期时间
    UNIQUE(tenant_id, user_id)
);
```

### 3. 文档/FAQ增加敏感等级字段

```sql
-- 给documents表增加敏感等级（如果还没有）
ALTER TABLE documents ADD COLUMN IF NOT EXISTS sensitivity_level VARCHAR(20) DEFAULT 'normal';

-- 给kb_cached_faqs表增加敏感等级
ALTER TABLE kb_cached_faqs ADD COLUMN IF NOT EXISTS sensitivity_level VARCHAR(20) DEFAULT 'normal';

-- 给chunks表增加敏感等级（如果向量化时有的话）
ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS sensitivity_level VARCHAR(20) DEFAULT 'normal';
```

### 4. 敏感问答审计日志

```sql
-- 敏感问答访问日志
CREATE TABLE sensitivity_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    user_id UUID,
    conversation_id UUID,
    question TEXT,
    sensitivity_level VARCHAR(20),  -- 被拦截的敏感等级
    action VARCHAR(20),  -- denied / warned
    reason VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_sensitivity_audit_tenant ON sensitivity_audit_log(tenant_id);
CREATE INDEX idx_sensitivity_audit_time ON sensitivity_audit_log(created_at);
```

---

## 核心逻辑

### 1. 获取用户最高可访问密级

```python
# backend/app/services/sensitivity_service.py

class SensitivityService:
    SENSITIVITY_LEVELS = ['normal', 'confidential', 'restricted']
    LEVEL_ORDER = {level: i for i, level in enumerate(SENSITIVITY_LEVELS)}
    
    async def get_user_max_level(self, user_id: UUID, tenant_id: UUID) -> str:
        """
        获取用户最高可访问密级
        优先级：用户覆盖 > 角色权限
        """
        # 1. 检查用户覆盖
        override = await self.get_user_override(user_id, tenant_id)
        if override:
            if not override.expires_at or override.expires_at > datetime.now():
                return override.max_sensitivity_level
        
        # 2. 检查角色权限
        user = await self.get_user(user_id)
        role_perm = await self.get_role_permission(user.tenant_id, user.role)
        if role_perm:
            return role_perm.max_sensitivity_level
        
        # 3. 默认最低级
        return 'normal'
    
    def can_access_level(self, user_max_level: str, content_level: str) -> bool:
        """判断用户是否有权访问某密级内容"""
        return self.LEVEL_ORDER.get(content_level, 0) <= self.LEVEL_ORDER.get(user_max_level, 0)
```

### 2. 检索时按密级过滤

```python
# backend/app/services/retrieval/hybrid.py
# 或 retrieval 调用的地方

class HybridRetriever:
    def __init__(self, sensitivity_service: SensitivityService):
        self.sensitivity = sensitivity_service
    
    async def retrieve(self, req, user_max_level: str, ...):
        # ... 原有检索逻辑 ...
        chunks = await self.vector_search(...)
        chunks = await self.fulltext_search(...)
        
        # ★ 新增：按密级过滤
        filtered_chunks = []
        for chunk in chunks:
            chunk_level = chunk.get('sensitivity_level', 'normal')
            if self.sensitivity.can_access_level(user_max_level, chunk_level):
                filtered_chunks.append(chunk)
            else:
                # 记录：用户无法访问某内容（可选日志）
                pass
        
        return filtered_chunks
```

### 3. FAQ命中时按密级过滤

```python
# backend/app/services/kb_faq_service.py
# check_faq_hit 方法修改

async def check_faq_hit(
    self,
    question: str,
    tenant_id: str,
    authorized_kb_ids: list,
    user_max_level: str,  # ★ 新增参数
    ...
):
    faqs = await self.crud.list_by_normalized(...)
    
    for faq in faqs:
        # 原有检查...
        if faq.kb_id not in authorized_kb_ids:
            continue
        if faq.status == 'pending_review':
            continue
        
        # ★ 新增：密级检查
        faq_level = getattr(faq, 'sensitivity_level', 'normal')
        if not self.sensitivity.can_access_level(user_max_level, faq_level):
            # 记录审计日志
            await self.audit_denied_access(faq, user_id, tenant_id)
            continue  # 跳过，无权访问
        
        # 命中
        return faq
    
    return None
```

### 4. 问答流程整合

```python
# backend/app/core/qa_pipeline.py

async def run(req: QARequest, current_user: User):
    # ... 解析会话 ...
    
    # ★ 获取用户最高密级
    user_max_level = await sensitivity_service.get_user_max_level(
        current_user.id, current_user.tenant_id
    )
    
    # FAQ命中（带密级检查）
    faq_hit = await kb_faq_service.check_faq_hit(
        question=req.question,
        tenant_id=tenant_id,
        authorized_kb_ids=authorized_kb_ids,
        user_max_level=user_max_level,  # ★ 传入
        ...
    )
    
    if faq_hit:
        yield {"type": "cache_hit", ...}
        return
    
    # ★ 检索（带密级过滤）
    chunks = await retriever.retrieve(
        req.question,
        user_max_level=user_max_level,  # ★ 传入
        ...
    )
    
    # ... 后续流程 ...
```

### 5. 无权限时的返回

```python
# backend/app/core/qa_pipeline.py

# 当所有检索结果都被过滤后
if not chunks and faq_not_accessible:
    yield {
        "type": "access_denied",
        "reason": "该内容需要更高权限访问",
        "user_level": user_max_level,
        # 可选：暗示用户可以申请更高权限
    }
    return

# 或者：当命中了高密级FAQ但用户无权时
if faq_level > user_max_level:
    yield {
        "type": "access_denied",
        "reason": "该问题涉及机密内容，需要更高权限"
    }
    # 记录审计日志
    await sensitivity_service.log_access_denied(
        user_id=current_user.id,
        question=req.question,
        sensitivity_level=faq_level,
        tenant_id=tenant_id
    )
```

---

## 管理端功能

### 1. 文档/FAQ密级设置

```python
# backend/app/api/v1/admin/documents.py

@router.put("/admin/documents/{doc_id}")
async def update_document(
    doc_id: UUID,
    data: DocumentUpdate,
    current_user: User = Depends(get_admin)
):
    """更新文档（含密级设置）"""
    # 检查权限：只有admin可以设置confidential/restricted
    if data.sensitivity_level in ['confidential', 'restricted']:
        if current_user.role not in ['admin', 'executive']:
            raise HTTPException(403, "无权限设置高密级")
    
    return await document_service.update(doc_id, data.dict(exclude_unset=True))
```

```python
# backend/app/api/v1/admin/kb_faqs.py

@router.put("/admin/faq/{faq_id}")
async def update_faq(
    faq_id: UUID,
    data: FAQUpdate,
    current_user: User = Depends(get_admin)
):
    """更新FAQ（含密级设置）"""
    # 密级继承源文档，或手动设置
    if data.sensitivity_level:
        # 手动设置的逻辑
        pass
    else:
        # 继承源文档密级
        source_level = await get_max_source_document_level(data.source_document_ids)
        data.sensitivity_level = source_level
    
    return await kb_faq_service.update(faq_id, data.dict(exclude_unset=True))
```

### 2. 角色权限配置

```python
# backend/app/api/v1/admin/sensitivity.py

@router.get("/admin/sensitivity/roles")
async def list_role_permissions(
    current_user: User = Depends(get_admin)
):
    """获取角色密级配置列表"""
    return await sensitivity_service.list_role_permissions(current_user.tenant_id)

@router.put("/admin/sensitivity/roles/{role}")
async def update_role_permission(
    role: str,
    max_level: str,
    current_user: User = Depends(get_admin)
):
    """更新角色密级权限"""
    # 只有executive可以修改
    if current_user.role != 'executive':
        raise HTTPException(403, "只有高管可以修改角色权限配置")
    
    return await sensitivity_service.update_role_permission(
        tenant_id=current_user.tenant_id,
        role=role,
        max_level=max_level
    )

@router.post("/admin/sensitivity/users/{user_id}/override")
async def create_user_override(
    user_id: UUID,
    max_level: str,
    reason: str,
    expires_at: datetime | None = None,
    current_user: User = Depends(get_admin)
):
    """创建用户密级覆盖（特例）"""
    return await sensitivity_service.create_user_override(
        tenant_id=current_user.tenant_id,
        user_id=user_id,
        max_level=max_level,
        reason=reason,
        expires_at=expires_at
    )
```

### 3. 审计日志查询

```python
# backend/app/api/v1/admin/sensitivity.py

@router.get("/admin/sensitivity/audit")
async def list_sensitivity_audit(
    page: int = 1,
    size: int = 50,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    user_id: UUID | None = None,
    current_user: User = Depends(get_admin)
):
    """查询敏感访问审计日志"""
    return await sensitivity_service.list_audit(
        tenant_id=current_user.tenant_id,
        page=page,
        size=size,
        start_date=start_date,
        end_date=end_date,
        user_id=user_id
    )
```

---

## 前端改动

### 访客端 - 无权限提示

```javascript
// frontend/guest/js/app.js

function handleSSEMessage(data) {
    if (data.type === 'access_denied') {
        // 隐藏思考态
        clearThinkingState();
        
        // 显示无权限提示
        showMessage(`
            <div class="access-denied">
                <span class="icon">🔒</span>
                <span>${data.reason || '该内容需要更高权限访问'}</span>
            </div>
        `, 'warning');
        return;
    }
    // ... 其他处理
}
```

### 管理端 - 密级配置UI

```html
<!-- 管理端 FAQ/文档编辑页面 -->

<div class="form-group">
    <label>敏感等级</label>
    <select name="sensitivity_level" class="form-control">
        <option value="normal">普通 (Normal)</option>
        <option value="confidential">机密 (Confidential)</option>
        <option value="restricted">极高密 (Restricted)</option>
    </select>
    <small class="help-text">
        confidential需要HR/管理员权限<br>
        restricted需要高管权限
    </small>
</div>
```

---

## 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `backend/app/models/sensitivity.py` | 新建 | 敏感权限模型 |
| `backend/app/services/sensitivity_service.py` | 新建 | 敏感权限服务 |
| `backend/app/api/v1/admin/sensitivity.py` | 新建 | 管理端API |
| `backend/app/services/kb_faq_service.py` | 修改 | FAQ命中加密级检查 |
| `backend/app/services/retrieval/hybrid.py` | 修改 | 检索结果加密级过滤 |
| `backend/app/core/qa_pipeline.py` | 修改 | 整合敏感权限检查 |
| `backend/app/models/document.py` | 修改 | 加sensitivity_level字段 |
| `backend/app/models/kb_faq.py` | 修改 | 加sensitivity_level字段 |
| `frontend/guest/js/app.js` | 修改 | 无权限提示 |
| `frontend/admin/js/...` | 修改 | 管理端密级配置UI |

### 数据库迁移

```sql
-- 运行迁移脚本或手动执行上述SQL
```

---

## 验收标准

| 测试场景 | 预期结果 |
|---------|---------|
| 普通员工问普通FAQ | 正常回答 ✅ |
| 普通员工问机密FAQ | 提示「需要更高权限」✅ |
| HR问机密FAQ | 正常回答 ✅ |
| 检索结果含机密内容 | 过滤掉，不泄露 ✅ |
| 管理端可设置密级 | 可配置 ✅ |
| 审计日志有记录 | 查看有记录 ✅ |

---

## 注意事项

1. **密级继承**：FAQ默认继承源文档密级，可手动覆盖
2. **访客默认**：未登录/guest只能是normal
3. **不泄露信息**：无权限内容完全不召回，不先展示再拒绝
4. **审计日志**：所有拒绝访问都要记录，便于安全审计
